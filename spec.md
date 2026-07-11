# OCI-OcC-Fix — Efficiency & Advanced Capabilities Spec (v2)

> Status: **APPROVED DIRECTION** — all prior `[DECISION]` points resolved to the recommended
> options. This document is the implementation blueprint. It is intentionally comprehensive;
> each item maps to a phase in the roadmap (§14).

## 1. Goal & principles

Turn OCI-OcC-Fix from a single-shot retry script into a **fast, safe, observable,
controllable capacity-hunting service** that:

- **Wins scarce OCI capacity sooner** (broader search, smarter timing).
- **Never gets throttled/banned** (correct backoff + global rate limiting + idempotency).
- **Is operable** (remote control, metrics, health, structured logs, alerts).
- **Is resilient** (persisted state, resume, graceful shutdown, circuit breakers).
- **Is trustworthy** (tests, types, CI, least-privilege IAM, secret hygiene).

Design principles: *stateless-by-default but resumable*, *fail fast on config/auth,
retry forever on capacity*, *observable everything*, *safe defaults*, *back-compat with
existing `.ini` config*.

## 2. Baseline & limitations (from current `bot.py`)

| # | Limitation | Location | Fix phase |
|---|------------|----------|-----------|
| L1 | Sequential AD retry, one attempt per sleep | `run()` | P2 |
| L2 | Backoff **shortens** on `OutOfHostCapacity`, lengthens only on 429 | `adaptive_retry_wait()` | P1 |
| L3 | No jitter; perfectly periodic retries | `run()` | P1 |
| L4 | One-time, hardcoded quota/storage limits (`200`, `4`, `24`) | `validate_resources()` | P3 |
| L5 | Credentials only from `config` file; `sys.exit(1)` on any error | `initialize_oci_clients()` | P3 |
| L6 | `python-dotenv` declared but unused | `requirements.txt` | P3 |
| L7 | Telegram one-way; no runtime control | `initialize_telegram` | P4 |
| L8 | No persisted state; counters reset on restart | whole file | P5 |
| L9 | No metrics/health endpoint; logs only | `setup_logging()` | P4 |
| L10 | Single region/shape/target | config + `run()` | P5 |
| L11 | Broad `except Exception` → `code='Unknown'` mistimes backoff | `run()` | P1 |
| L12 | No tests / lint / types / CI | repo | P0 |
| L13 | Ignores OCI `Retry-After` / rate-limit headers | `create_instance` | P1 |
| L14 | No launch idempotency (`opc-retry-token`) → duplicate-launch risk | `create_instance` | P1 |
| L15 | Monolithic single file; hard to test/extend | `bot.py` | P0 |

## 3. Target architecture

Thin entrypoint + focused modules (package `occfix/`), all OCI access behind an interface
so it can be mocked in tests.

```
bot.py                      # thin CLI entrypoint (back-compat shim)
occfix/
  cli.py                    # argparse/typer, subcommands (run, validate, dry-run, wizard)
  config/
    schema.py               # pydantic models + validation
    loader.py               # layered: defaults < .ini < .env/env < CLI flags
  auth/
    providers.py            # key-file | env | instance-principal | resource-principal | session-token
    vault.py                # optional OCI Vault / HashiCorp Vault secret resolution
  oci_gateway.py            # interface wrapping compute/identity/network/blockstorage (mockable)
  launcher.py               # per-launch-spec state machine (validate → attempt → verify → hand-off)
  backoff.py                # retry policies (capacity vs throttle), decorrelated jitter
  ratelimit.py              # global token bucket + AIMD adaptive rate controller
  scheduler.py              # concurrency (bounded pool), bulkheads per region/AD, windows/quiet-hours
  capacity_intel.py         # success heatmap learning + weighting of AD/region/time
  state/
    store.py                # SQLite/JSON persistence (attempts, per-AD stats, launched IDs)
  notify/
    base.py                 # Notifier interface + registry (plugins)
    telegram.py discord.py slack.py webhook.py email.py ntfy.py
  observability/
    metrics.py              # Prometheus registry + counters/gauges/histograms
    logging.py              # human + JSON formats, secret redaction
    tracing.py              # optional OpenTelemetry spans
  control/
    http_api.py             # FastAPI status/health/control endpoints (+ optional dashboard)
    telegram_cmds.py        # /status /pause /resume /stop /config command handlers
  hooks/
    postlaunch.py           # tag, attach volume, assign reserved IP, run webhook/DNS, ssh-notify
  lifecycle.py              # signal handling (SIGTERM/SIGHUP reload), graceful shutdown, watchdog
```

## 4. Efficiency track

### 4.1 Retry & backoff policy (fixes L2/L3/L11/L13)
Two independent policies keyed by error class:

- **Capacity errors** (`OutOfHostCapacity`, `OutOfCapacity`): stay aggressive but jittered —
  wait = `uniform(min_interval, min_interval + capacity_jitter_cap)`. Capacity can free up
  at any instant, so we keep retrying quickly, but jitter prevents synchronized bursts.
- **Throttle errors** (`TooManyRequests`/429): **exponential backoff with decorrelated jitter**,
  and **honor `Retry-After`/`opc-*` headers** when present:
  `sleep = max(header_retry_after, min(cap, uniform(base, prev*3)))`.
- **Auth/config errors** (401/404/invalid): **fail fast** (no infinite hammering) → circuit-open + alert.
- **Unknown/transient network**: exponential backoff, capped, with jitter (never the "Unknown" fast path).

```python
# decorrelated jitter (throttle path)
sleep = min(cap, random.uniform(base, prev_sleep * 3))
prev_sleep = sleep
```

### 4.2 Global rate limiting + adaptive control (new, fixes root cause of 429s)
- **Token bucket** shared across all workers/ADs/regions caps launch calls to a safe rate.
- **AIMD adaptive controller**: additively increase allowed rate while clean; multiplicatively
  cut it on any 429. Converges automatically on the tenancy's real throttle ceiling — this is
  the "auto-learn the safe rate" behavior (approved).

### 4.3 Concurrency & bulkheads (fixes L1/L10)
- **Bounded thread pool** (default 3, configurable) sweeping availability domains in parallel,
  all pulling tokens from the shared limiter (breadth without exceeding safe rate).
- **Bulkhead per region**: an outage/throttle in one region can't starve others.
- Multi-region sweep supported (opt-in; single-region remains the default).

### 4.4 Launch idempotency (fixes L14)
- Send an **`opc-retry-token`** per logical launch attempt so SDK/network retries can't create
  duplicate instances. Combined with pre-burst duplicate-name checks and persisted launched IDs.

### 4.5 Capacity intelligence (new)
- Record per-(region, AD, shape, hour-of-day) success/miss counts in the state store.
- **Weight** the sweep toward historically productive ADs/time windows (bandit-style: mostly
  exploit best slots, occasionally explore). Purely heuristic, no heavy ML dependency.
- Optional export of the capacity heatmap (CSV/JSON) for analysis.

### 4.6 Cheap validation (fixes L4)
- Cache identity/tenancy/quota/storage lookups with a TTL; re-validate periodically, not per loop.
- Free-tier and quota limits become configurable (`[Limits]`), defaulting to today's values.
- `occfix validate` / `--dry-run`: check config + auth + quota + connectivity, then exit (fast, cheap).

### 4.7 Client/network tuning
- Reuse HTTP sessions / connection pooling; tune SDK timeouts and retry strategy explicitly.
- Prefer regional endpoints; optional lowest-latency region probe at startup.

## 5. Advanced features

### 5.1 Config & secrets (fixes L5/L6)
- **Layered config** (precedence low→high): built-in defaults → `configuration.ini` → `.env`/env
  vars (activating `python-dotenv`) → CLI flags. `.ini` stays the back-compat source of truth.
- **pydantic schema** validates types/ranges and gives clear errors (replaces ad-hoc checks).
- **Auth providers**: key-file (today), env-config, **instance principals**, **resource principals**,
  **session/security token** — so it can run keyless on an OCI VM/function.
- **Secret backends**: env, **OCI Vault**, optional **HashiCorp Vault**; never persist secrets to state.
- Key-file permission check (warn on world-readable PEM).

### 5.2 Control surface (fixes L7/L9)
- **Telegram commands**: `/status`, `/pause`, `/resume`, `/stop`, `/config`, `/stats` (opt-in, allow-listed uid).
- **HTTP control+status API** (FastAPI/uvicorn): `GET /healthz`, `GET /readyz`, `GET /status`,
  `GET /metrics`, `POST /pause|/resume|/stop`. Enables container healthchecks & dashboards.
- **Optional web dashboard**: live attempts, current interval, per-AD stats, capacity heatmap, log tail.

### 5.3 Observability
- **Prometheus `/metrics`** (catalog in §11).
- **Structured JSON logging** option alongside the current human-readable format, with secret redaction.
- **OpenTelemetry** traces (optional) around launch attempts.
- Optional **Sentry** error reporting (a Sentry SDK-setup skill exists in this workspace).

### 5.4 Notifications (extends existing Telegram)
- Pluggable **Notifier** interface + registry: Telegram, Discord, Slack, generic webhook, email (SMTP),
  ntfy, Pushover, Matrix. Multiple channels at once.
- **Event model**: `started`, `attempt_milestone`, `throttled`, `capacity_miss_streak`, `launched`,
  `error`, `stopped`. Per-channel event filters + **digest/rate-limited** mode to avoid spam.
- Rich success payload: instance OCID, public/private IP, shape, region/AD, total attempts, elapsed.

### 5.5 State & persistence (fixes L8)
- **SQLite (default) or JSON** store: total attempts, per-AD/region/shape stats, launched instance IDs,
  last error per target, capacity heatmap, adaptive rate state.
- **Resume** cleanly after restart; **cross-restart dedupe** of already-launched targets.

### 5.6 Multi-target / multi-region / multi-tenancy (fixes L10)
- Config expresses a **list of launch specs** (shape/ocpus/memory/image/region/count), each with its
  own success criteria and its own bulkhead.
- Launch **N** instances of a spec; stop that spec when its target count is met, keep hunting others.
- Optional **multi-tenancy/profile rotation** to spread hunting across accounts (each with own limiter).

### 5.7 Post-launch automation hooks (new)
On success, optionally: wait for `RUNNING`, verify SSH reachability, **tag** the instance,
**attach a block volume**, **assign a reserved public IP**, update **DNS** (OCI DNS/Cloudflare),
run a **cloud-init**/user-data, and fire a **completion webhook** with connection details.

### 5.8 Scheduling & budget guards (new)
- Run windows / **quiet hours**; `--max-runtime` and `--max-attempts` stop conditions.
- Optional cost/budget guard notes for PAYG (warn before exceeding always-free limits).

### 5.9 Lifecycle
- **Graceful shutdown** on SIGTERM (Docker/systemd/k8s friendly), **SIGHUP → hot config reload**.
- **Watchdog**/self-heal: detect stuck loops, auto-restart internal workers.

## 6. Quality, tooling & packaging (fixes L12/L15)
- **pytest** unit + integration tests against a **mocked `oci_gateway`** (no live calls): config
  parsing, backoff math, rate limiter/AIMD, idempotency token use, state persistence, scheduler,
  notifier dispatch. Target ≥85% coverage on core logic.
- **ruff** (lint+format), **mypy** (types), **pre-commit** hooks, **bandit** + **pip-audit** (security).
- **GitHub Actions CI**: lint → type → test (matrix py3.10–3.13) → build Docker → security scan; on PRs.
- **pyproject.toml** packaging with a `oci-occ-fix` console entry point; pinned/locked deps.
- **Docs**: mkdocs site (config reference, IAM policy, deployment, metrics), keep README quickstart.
- **Dependabot/Renovate** + `CHANGELOG.md` + semver + release-drafter (already present).

## 7. Security & IAM
- Ship a **least-privilege IAM policy** doc (only `INSTANCE_LAUNCH`, read on subnets/images/volumes,
  scoped to the target compartment).
- Secret **redaction** in all logs/metrics; secrets never written to state files.
- Support keyless auth (instance/resource principals) to avoid distributing PEM keys.
- Optional **encrypted state at rest**; strict file permissions on key file + state.

## 8. Deployment
- **Docker**: multi-stage build, pinned non-EOL base, **non-root user**, `HEALTHCHECK` hitting `/healthz`,
  smaller final image; keep `docker-compose.yml` working.
- **Kubernetes**: manifests + optional **Helm chart** (Deployment, liveness/readiness probes, secrets).
- **systemd** unit for bare-metal/VM runs.
- Keep the Heroku-style `Procfile` working.

## 9. CLI UX
- Subcommands via typer/argparse: `run`, `validate`, `dry-run`, `wizard`, `status`, `stats`, `export-heatmap`.
- Optional **rich** TUI dashboard for local runs (live table of ADs, interval, attempts, 429 rate).
- Wizard upgrades: validate OCID formats, **auto-detect availability domains via API**, live
  **credential test**, and offer to write `.env` in addition to `.ini`.

## 10. Configuration schema (illustrative; back-compat with current `.ini`)
```ini
[Auth]
method = key_file            ; key_file | env | instance_principal | resource_principal | session_token
# key_file specifics remain in the existing OCI `config` file

[Targets]                    ; one or more launch specs (repeatable sections Targets.<name>)
specs = arm_free

[Targets.arm_free]
region = us-ashburn-1
availability_domains = ["Uocm:US-ASHBURN-AD-1","Uocm:US-ASHBURN-AD-2"]
shape = VM.Standard.A1.Flex
ocpus = 4
memory = 24
count = 1
image_id = ocid1.image....
subnet_id = ocid1.subnet....
display_name = OCI-ARM-01
ssh_keys = ssh-rsa AAAA...

[Retry]
min_interval = 1
max_interval = 60
capacity_jitter_cap = 3
throttle_backoff_cap = 300
backoff_factor = 1.5

[RateLimit]
mode = adaptive             ; fixed | adaptive(AIMD)
max_calls_per_sec = 2
concurrency = 3

[Limits]
max_total_storage_gb = 200
arm_max_ocpus = 4
arm_max_memory_gb = 24

[Control]
http_enabled = true
http_port = 8080
telegram_commands = true

[Observability]
log_format = human          ; human | json
metrics_enabled = true

[State]
backend = sqlite            ; sqlite | json | none
path = occfix_state.db

[Notify]
channels = telegram         ; comma list: telegram,discord,slack,webhook,email,ntfy
digest = false

[Schedule]
quiet_hours =               ; e.g. 01:00-06:00
max_runtime =               ; e.g. 12h
max_attempts =              ; e.g. 100000
```

## 11. Metrics catalog (Prometheus)
| Metric | Type | Labels | Meaning |
|--------|------|--------|---------|
| `occfix_attempts_total` | counter | region, ad, shape, result | launch attempts by outcome |
| `occfix_capacity_miss_total` | counter | region, ad, shape | OutOfHostCapacity responses |
| `occfix_throttled_total` | counter | region | 429 responses |
| `occfix_launch_success_total` | counter | region, ad, shape | successful launches |
| `occfix_current_interval_seconds` | gauge | target | current backoff interval |
| `occfix_rate_limit_permits_per_sec` | gauge | — | adaptive limiter current rate |
| `occfix_attempt_latency_seconds` | histogram | region | LaunchInstance call latency |
| `occfix_time_to_capacity_seconds` | histogram | region, shape | wall-clock until success |
| `occfix_up` / `occfix_paused` | gauge | — | liveness / paused state |

## 12. Success metrics (KPIs)
- **Time-to-capacity** (median attempts & wall-clock) ↓.
- **Throttle rate** (429 / total attempts) → ~0.
- **API efficiency**: attempts per success ↓; validation calls/hour ↓.
- **Reliability**: successful resume after restart; **zero** duplicate instances.
- **Ops**: MTTR via alerts; coverage ≥85% core.

## 13. Risks & mitigations
| Risk | Mitigation |
|------|------------|
| Concurrency triggers throttling | Global token bucket + AIMD; concurrency pulls from shared limiter |
| Duplicate instance launches | `opc-retry-token` + pre-burst dedupe + persisted launched IDs |
| Aggressive retries → account flags | Adaptive rate learning, backoff, fail-fast on auth errors |
| Config migration breaks users | Keep `.ini` back-compat; layered overrides; schema-validated with clear errors |
| Scope creep | Strict phasing; each phase independently shippable & tested |
| Secret leakage | Redaction, keyless auth options, no secrets in state, perms checks |

## 14. Phased roadmap (expanded)
Each phase is independently shippable, test-covered, and behind safe defaults.

- **P0 — Safety net & refactor:** package scaffolding (`occfix/`), `oci_gateway` interface,
  pytest + mocked OCI, ruff/mypy/pre-commit, GitHub Actions CI, `pyproject.toml`. *(fixes L12/L15)*
- **P1 — Backoff correctness + rate control:** dual retry policies, decorrelated jitter,
  `Retry-After` handling, token bucket + AIMD, `opc-retry-token`, fail-fast auth.
  *(fixes L2/L3/L11/L13/L14 — biggest win)*
- **P2 — Concurrency & bulkheads:** bounded thread-pool AD sweep under shared limiter, per-region bulkheads. *(fixes L1)*
- **P3 — Config, secrets, auth, validation:** layered config + pydantic + dotenv, auth providers
  (incl. instance principals) + vaults, configurable limits, `--dry-run`/`validate`, cached validation. *(fixes L4/L5/L6)*
- **P4 — Control & observability:** Telegram commands, HTTP status/health/control API, Prometheus
  metrics, JSON logs, optional tracing/Sentry, multi-channel notifiers + digests. *(fixes L7/L9)*
- **P5 — State, resume, multi-target, lifecycle:** SQLite/JSON state, resume + dedupe, SIGTERM/SIGHUP,
  multi-region/shape/tenancy, N-instance launches, capacity intelligence, post-launch hooks, scheduling. *(fixes L8/L10)*
- **P6 — Deploy & docs polish:** hardened Docker, Helm/k8s + systemd, mkdocs site, rich TUI, wizard upgrades.

## 15. Non-goals
- Rewrite to another language/runtime.
- Full instance lifecycle management after hand-off (this tool wins capacity, then hands off; post-launch hooks are optional conveniences only).
- A hosted multi-tenant SaaS control plane.
