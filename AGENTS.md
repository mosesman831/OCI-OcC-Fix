# AGENTS.md

## Cursor Cloud specific instructions

### What this project is
Single-product Python worker: **OCI-OcC-Fix** (`bot.py`). It repeatedly calls the
Oracle Cloud (OCI) API to launch a compute instance, retrying with adaptive backoff
until Oracle has capacity. There is **no web server, no listening ports, and no local
database/queue/cache** — do not try to provision any. Optional Telegram notifications
self-disable when their config is left as `xxxx`.

### Setup / run / test
- Dependencies: `pip install -r requirements.txt` (handled by the startup update script).
- Run the bot: `python3 bot.py` (see `README.md` for `--config` / `--oci-config` flags).
- Config wizard: `python3 setup_wizard.py` (interactive; `--gui` needs tkinter).
- There is **no test suite and no configured linter** (the `.github/workflows` only do
  auto-release + traffic badges). Lightweight sanity check: `python3 -m py_compile bot.py setup_wizard.py`.

### Non-obvious gotchas
- `bot.py` needs both `configuration.ini` (app settings) and `config` (OCI SDK
  credentials file, standard OCI format) in the working directory, plus the PEM private
  key referenced by `key_file`. The committed `configuration.ini` and `config` are
  **placeholder templates** — never commit real secrets into them.
- Real end-to-end capacity-launch behavior requires a genuine OCI tenancy + API key
  (secrets not in the repo). Without valid credentials the bot still runs the full
  pipeline (config load → OCI client init → live OCI API call) and then exits with
  `401 NotAuthenticated` at resource validation. That 401 is the expected proof the
  environment is wired correctly, not an environment bug.
- To exercise the bot without touching the committed templates, generate config in a
  temp dir and pass `--config` / `--oci-config`. `setup_wizard.py` can be driven
  non-interactively by piping newline-separated answers to stdin.
- `bot.py`'s normal (authenticated) run loops forever until an instance is launched;
  when testing, wrap it with `timeout`.
