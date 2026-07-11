"""Command-line interface for occfix.

Back-compatible with the original ``python3 bot.py --config ... --oci-config ...``
invocation: when no subcommand is given, ``run`` is assumed.
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
from collections.abc import Sequence

from occfix import __version__
from occfix.config import AppConfig, load_config
from occfix.models import AuthError, ConfigError, OccfixError
from occfix.observability import get_metrics, setup_logging

log = logging.getLogger("occfix.cli")

_SUBCOMMANDS = {"run", "validate", "dry-run", "wizard", "version", "stats"}


def _add_global_args(parser: argparse.ArgumentParser, *, suppress: bool) -> None:
    """Global options shared by the top-level parser and every subparser.

    Subparsers use ``SUPPRESS`` defaults so they never clobber values already set
    before the subcommand (back-compat: ``bot.py --config x`` -> implicit run).
    """

    parser.add_argument(
        "--config",
        default=argparse.SUPPRESS if suppress else "configuration.ini",
        help="Path to configuration.ini",
    )
    parser.add_argument(
        "--oci-config",
        default=argparse.SUPPRESS if suppress else "config",
        help="Path to OCI SDK config file (default: ./config)",
    )
    parser.add_argument(
        "--log-level",
        default=argparse.SUPPRESS if suppress else None,
        help="Override log level (DEBUG/INFO/...)",
    )
    parser.add_argument(
        "--json-logs",
        action="store_true",
        default=argparse.SUPPRESS if suppress else False,
        help="Emit structured JSON logs",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oci-occ-fix",
        description="Win scarce OCI capacity: adaptive, concurrent, observable retries.",
    )
    _add_global_args(parser, suppress=False)

    common = argparse.ArgumentParser(add_help=False)
    _add_global_args(common, suppress=True)

    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", parents=[common], help="Run the capacity-hunting loop")
    run_p.add_argument("--once", action="store_true", help="Do a single sweep round then exit")
    run_p.add_argument("--max-attempts", type=int, default=0, help="Stop after N attempts (0=inf)")

    sub.add_parser("validate", parents=[common], help="Validate config + auth + quota, then exit")
    sub.add_parser("dry-run", parents=[common], help="Alias for validate")
    sub.add_parser("wizard", parents=[common], help="Run the interactive setup wizard")
    sub.add_parser("stats", parents=[common], help="Print persisted run stats")
    sub.add_parser("version", parents=[common], help="Print version and exit")
    return parser


def _normalize_argv(argv: Sequence[str]) -> list[str]:
    """Insert the default ``run`` subcommand when none is provided."""

    args = list(argv)
    i = 0
    while i < len(args):
        tok = args[i]
        if tok in _SUBCOMMANDS:
            return args
        if not tok.startswith("-"):
            # First positional that isn't a known subcommand -> treat as run.
            return args[:i] + ["run"] + args[i:]
        # Value-consuming flags: skip the flag AND its value.
        if tok in ("--config", "--oci-config", "--log-level"):
            i += 2
            continue
        i += 1
    return args + ["run"]


def _load(args: argparse.Namespace) -> AppConfig:
    overrides: dict[str, object] = {}
    if args.log_level:
        overrides["observability.log_level"] = args.log_level.upper()
    if getattr(args, "json_logs", False):
        overrides["observability.log_format"] = "json"
    cfg = load_config(args.config, args.oci_config, overrides=overrides)
    setup_logging(cfg.observability)
    return cfg


def _build_gateway(cfg: AppConfig):
    from occfix.gateway_real import RealOciGateway

    return RealOciGateway.from_auth(cfg.auth)


def _cmd_run(args: argparse.Namespace) -> int:
    from occfix.launcher import Engine
    from occfix.notify import build_dispatcher
    from occfix.state import open_state

    cfg = _load(args)
    try:
        cfg.validate()
    except ConfigError as exc:
        log.critical("Invalid configuration: %s", exc)
        return 1

    metrics = get_metrics()
    if cfg.observability.metrics_enabled:
        metrics.start_http_server(cfg.observability.metrics_port)

    state = open_state(cfg.state)
    dispatcher = build_dispatcher(cfg.notify)
    gateway = _build_gateway(cfg)

    engine = Engine(cfg, gateway, state=state, dispatcher=dispatcher, metrics=metrics)
    stop_event = threading.Event()
    try:
        results = engine.run(
            stop_event=stop_event,
            max_attempts=getattr(args, "max_attempts", 0),
            max_rounds=1 if getattr(args, "once", False) else 0,
        )
    except AuthError as exc:
        log.critical("Auth error, stopping: %s", exc)
        return 1
    except KeyboardInterrupt:
        log.info("Interrupted by user; shutting down")
        stop_event.set()
        return 0
    finally:
        state.close()

    return 0 if results else (0 if getattr(args, "once", False) else 1)


def _cmd_validate(args: argparse.Namespace) -> int:
    from occfix.launcher import Engine

    cfg = _load(args)
    try:
        cfg.validate()
    except ConfigError as exc:
        print(f"Config invalid: {exc}")
        return 1

    try:
        gateway = _build_gateway(cfg)
        results = Engine(cfg, gateway).validate_all()
    except AuthError as exc:
        print(f"Auth/permission error: {exc}")
        return 1
    except OccfixError as exc:
        print(f"Error: {exc}")
        return 1

    ok = True
    for name, reason in results.items():
        if reason:
            ok = False
            print(f"[FAIL] {name}: {reason}")
        else:
            print(f"[OK]   {name}: passed validation")
    return 0 if ok else 1


def _cmd_stats(args: argparse.Namespace) -> int:
    import json

    from occfix.state import open_state

    cfg = _load(args)
    store = open_state(cfg.state)
    try:
        print(
            json.dumps(
                {"total_attempts": store.total_attempts(), "stats": store.get_stats()}, indent=2
            )
        )
    finally:
        store.close()
    return 0


def _cmd_wizard(args: argparse.Namespace) -> int:
    import setup_wizard

    setup_wizard.main()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(_normalize_argv(argv))

    command = args.command or "run"
    if command == "version":
        print(f"oci-occ-fix {__version__}")
        return 0
    if command == "wizard":
        return _cmd_wizard(args)
    if command in ("validate", "dry-run"):
        return _cmd_validate(args)
    if command == "stats":
        return _cmd_stats(args)
    return _cmd_run(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
