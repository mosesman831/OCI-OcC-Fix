from __future__ import annotations

from occfix.cli import _normalize_argv, build_parser, main


def test_normalize_inserts_run_default():
    assert _normalize_argv([]) == ["run"]
    assert _normalize_argv(["--config", "x"]) == ["--config", "x", "run"]
    assert _normalize_argv(["--config", "x", "--json-logs"]) == [
        "--config",
        "x",
        "--json-logs",
        "run",
    ]


def test_normalize_keeps_explicit_subcommand():
    assert _normalize_argv(["validate"]) == ["validate"]
    assert _normalize_argv(["--config", "x", "run", "--once"]) == [
        "--config",
        "x",
        "run",
        "--once",
    ]
    assert _normalize_argv(["dry-run"]) == ["dry-run"]


def test_parser_run_flags():
    parser = build_parser()
    args = parser.parse_args(["run", "--once", "--max-attempts", "5"])
    assert args.command == "run"
    assert args.once is True
    assert args.max_attempts == 5


def test_version_command(capsys):
    rc = main(["version"])
    assert rc == 0
    assert "oci-occ-fix" in capsys.readouterr().out


def test_validate_missing_config_returns_1(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rc = main(["validate", "--config", "nope.ini", "--oci-config", "nope"])
    assert rc == 1
    assert "Config invalid" in capsys.readouterr().out
