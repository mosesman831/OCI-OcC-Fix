# AGENTS.md

## Cursor Cloud specific instructions

### What this project is
OCI-OcC-Fix hunts for scarce Oracle Cloud (OCI) compute capacity: it repeatedly
calls the OCI API to launch an instance, retrying until Oracle has capacity. There
is **no web server, no database, and no listening ports** in the core loop (an
optional Prometheus metrics port and optional HTTP control API can be enabled).
Optional Telegram/Discord/Slack/webhook notifications self-disable when unset.

### Architecture
- `occfix/` — the modular engine (the real implementation). Key modules:
  `models` (types/exceptions), `config` (layered ini→env→flags), `gateway` +
  `gateway_real`/`auth` (OCI access behind a mockable interface), `backoff`,
  `ratelimit` (token bucket + AIMD), `scheduler` (concurrency/quiet-hours),
  `capacity` (heatmap learning), `state` (sqlite/json), `notify`, `observability`
  (logging + metrics), `launcher` (attempt/loop + `Engine`), `cli`.
- `bot.py` — thin back-compat shim delegating to `occfix.cli:main`.
- `setup_wizard.py` — interactive config generator (legacy, untyped).
- `spec.md` — the design blueprint / roadmap.

### Setup / run / test
- Runtime deps: `pip install -r requirements.txt` (handled by the startup update script).
- Dev tools (tests/lint/types): `pip install pytest ruff mypy` (also in the update script)
  or `pip install -e .[dev]` once `pyproject.toml` is present.
- Run: `python3 bot.py` or `python3 -m occfix.cli run` (see `python3 -m occfix.cli --help`).
  Subcommands: `run` (default), `validate`/`dry-run`, `wizard`, `stats`, `version`.
- Tests: `python3 -m pytest` (fast; no live OCI — everything runs against `FakeOciGateway`).
- Lint/format: `ruff check .` and `ruff format .`. Types: `mypy occfix`.
- CI mirrors this in `.github/workflows/ci.yml` (ruff + mypy + pytest, py3.10–3.13).

### Non-obvious gotchas
- All OCI access goes through the `OciGateway` interface; write unit tests against
  `occfix.gateway.FakeOciGateway` (scriptable launch outcomes) — never hit real OCI in tests.
- `python3 bot.py --config X --oci-config Y` still works: the CLI injects a default
  `run` subcommand when none is given, and global flags are accepted before or after it.
- The committed `configuration.ini` and `config` are **placeholder templates** — never
  commit real secrets. Real capacity launches need a genuine OCI tenancy + API key.
- Without valid credentials the engine still runs the full pipeline and reaches the live
  OCI API, then **fails fast** with `401 NotAuthenticated` (classified as an auth error and
  stopped) at validation. That 401 is the expected proof the environment is wired correctly.
- Optional deps are imported lazily and degrade gracefully: `prometheus_client` (metrics
  fall back to an in-memory registry), `fastapi`/`uvicorn` (HTTP control), so the core
  runs with just `requirements.txt`.
- `bot.py`'s authenticated run loops until an instance launches; wrap with `timeout` when testing.
