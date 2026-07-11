# OCI-OcC-Fix — Efficiency & Advanced Capabilities Spec

> Status: **DRAFT for review**. Sections marked **[DECISION]** need your input before implementation.
> This is a living document — we refine it together, then implement in phases.

## 1. Goal

Make OCI-OcC-Fix (a) *faster and smarter* at winning scarce OCI capacity while
(b) staying safely under OCI rate limits, and (c) grow it from a single-shot script
into a robust, observable, controllable service.

Two independent tracks:
- **Efficiency** — win capacity sooner, waste fewer API calls, avoid rate-limit bans.
- **Advanced** — multi-target/region, control surface, observability, resilience.

## 2. Current architecture (baseline)

Single Python process (`bot.py`, class `OciOccFix`):

1. `load_config` → validate `configuration.ini` sections.
2. `initialize_oci_clients` → build compute/identity/network/blockstorage clients from `config`.
3. `initialize_telegram` → optional one-way notifier.
4. `validate_resources` → one-time quota/storage/duplicate checks.
5. `run` → infinite loop over availability domains, `create_instance` per AD, `sleep(wait_seconds)` after each attempt.

### 2.1 Concrete limitations found in code
| # | Issue | Location | Impact |
|---|-------|----------|--------|
| L1 | Retry loop is sequential across ADs, one attempt per `sleep` cycle | `run()` | Slow coverage of AD space |
| L2 | Backoff **decreases** wait on `OutOfHostCapacity` (÷1.5), **increases** only on `TooManyRequests` | `adaptive_retry_wait()` | Hammers hardest exactly when capacity is out → risks 429 bans |
| L3 | No jitter; perfectly periodic retries | `run()` / `adaptive_retry_wait()` | Predictable, collision-prone |
| L4 | `validate_resources` runs once, hardcodes `200` GB and ARM `4`/`24` | `validate_resources()` | Breaks for PAYG / non-free tiers; stale after first check |
| L5 | Credentials only from `config` file; `sys.exit(1)` on any load error | `initialize_oci_clients()` | No env/instance-principal/vault auth; brittle |
| L6 | `python-dotenv` declared but unused | `requirements.txt` | Dead dependency / missed feature |
| L7 | Telegram is one-way; no runtime control | `initialize_telegram`, `send_telegram_update` | Can't pause/stop/query remotely |
| L8 | No persisted state; counters reset on restart | whole file | No resume, no dedupe across restarts |
| L9 | No metrics / health endpoint; file+stdout logs only | `setup_logging()` | Hard to monitor at scale |
| L10 | Single region, single shape, single target instance | config + `run()` | Limited capacity-hunting surface |
| L11 | Broad `except Exception` with `code='Unknown'` fallback | `run()` | Masks real errors, mistimes backoff |
| L12 | No automated tests / lint / type checks | repo | Regressions likely as it grows |
| L13 | Ignores OCI `Retry-After` / rate-limit response headers | `create_instance` | Suboptimal backoff |

## 3. Efficiency track

### 3.1 Correct the backoff model **[DECISION]**
Replace `adaptive_retry_wait` with an explicit policy:
- `OutOfHostCapacity` / `OutOfCapacity` → **short, jittered** interval (capacity can appear any second). Keep aggressive but bounded (e.g. base `min_interval`, full jitter up to a small cap).
- `TooManyRequests` (429) → **exponential backoff with jitter**, honoring the OCI `Retry-After` header when present (fixes L2, L13).
- Distinguish "capacity" vs "throttle" states so throttling never gets *shorter* waits.
- Add "decorrelated jitter" (AWS-style) to avoid synchronized retries (fixes L3).

**Decision needed:** target request rate ceiling. OCI LaunchInstance is roughly a few
requests/sec/tenancy before throttling. Do we (a) tune conservative defaults, or
(b) auto-learn the safe rate from observed 429s? Recommendation: start with (a), add (b) later.

### 3.2 Concurrent AD / region sweep **[DECISION]**
Attempt multiple availability domains (and optionally regions) in parallel instead of
strictly sequential (fixes L1, L10). Options:
- **A. Thread pool** (small, e.g. 2–4 workers) — simplest, OCI SDK is sync/threadsafe per client.
- **B. asyncio** — more scalable but requires async OCI calls (SDK is sync; needs `run_in_executor`).

Recommendation: **A (bounded thread pool)** with a *global* rate limiter (token bucket)
shared across workers so concurrency never exceeds the 429-safe rate. This gets breadth
without triggering throttling.

**Decision needed:** max concurrency and whether multi-region is in scope for v1.

### 3.3 Cheaper validation
- Cache identity/tenancy/quota lookups; re-validate on an interval, not every loop.
- Make free-tier limits configurable (`[Limits]` section) instead of hardcoded (fixes L4).
- Add a `--dry-run` that validates config + auth + quota and exits (fast feedback, cheap).

### 3.4 Rate limiting & circuit breaker
- Central token-bucket limiter for all launch calls.
- Circuit breaker on repeated auth/config errors (stop hammering on a 401 — today a 401
  in `validate_resources` exits, but launch-path errors don't short-circuit).

## 4. Advanced track

### 4.1 Configuration & secrets **[DECISION]**
- Support layered config: `configuration.ini` → environment variables → CLI flags
  (activate the already-present `python-dotenv`, fixes L5/L6).
- Support OCI auth methods beyond a key file: env-based config and **instance principals**
  (so it can run on an existing OCI VM with no key file).
- **Decision needed:** keep `.ini` as source of truth, or migrate to `.env` + optional
  `config.yaml`? Recommendation: keep `.ini` for back-compat, layer env/flags on top.

### 4.2 Runtime control surface **[DECISION]**
Add a way to control a running bot:
- **Telegram command handler**: `/status`, `/pause`, `/resume`, `/stop`, `/config` (fixes L7).
- Optional **local HTTP control+status API** (FastAPI/uvicorn): `GET /status`, `GET /healthz`,
  `POST /pause`. Enables dashboards and container healthchecks.
- **Decision needed:** Telegram-only, HTTP-only, or both? Recommendation: Telegram commands
  first (already a dependency), HTTP status endpoint second.

### 4.3 Observability
- Structured JSON logging option alongside the current human format.
- Prometheus `/metrics` (attempts, successes, 429s, capacity-misses, current interval).
- Optional pluggable notifiers: Telegram (exists) + Discord/Slack/webhook/email.

### 4.4 Resilience & state
- Persist lightweight state (JSON/SQLite): total attempts, last error per AD, launched
  instance IDs — enables clean resume after restart and cross-restart dedupe (fixes L8).
- Idempotency: check for an existing instance with the target `display_name` before each
  launch burst, not only at startup (reduces duplicate-launch races).
- Graceful shutdown on SIGTERM (Docker/systemd friendly), not just `KeyboardInterrupt`.

### 4.5 Multi-target
- Launch **N** instances / multiple shapes / multiple regions from one config
  (list of "launch specs"), each with its own success criteria (extends L10).

## 5. Quality & tooling
- Add `pytest` unit tests with a **mocked OCI client** (no live calls) covering: config
  parsing/validation, backoff math, rate limiter, state persistence (fixes L12).
- Add `ruff` (lint) + `mypy` (types) + a GitHub Actions CI job running lint+tests on PRs.
- Refactor `bot.py` into modules: `config`, `auth`, `launcher`, `backoff`, `ratelimit`,
  `notifiers`, `state`, `cli` — keep `bot.py` as a thin entrypoint.

## 6. Proposed phased roadmap
Ordered by value-to-effort; each phase ships independently and is testable.

- **Phase 0 — Safety net:** module refactor scaffolding + pytest + mocked OCI + CI (lint/type/test).
- **Phase 1 — Backoff correctness (biggest bang):** fix L2/L3/L13 — jittered, header-aware
  backoff; separate capacity vs throttle policies; central rate limiter.
- **Phase 2 — Concurrency:** bounded thread-pool AD sweep under the shared rate limiter (L1).
- **Phase 3 — Config/secrets/auth:** env + dotenv + CLI layering; instance principals; `--dry-run` (L4/L5/L6).
- **Phase 4 — Control & observability:** Telegram commands, status/health endpoint, metrics, JSON logs (L7/L9).
- **Phase 5 — State & multi-target:** persistence, resume, dedupe, SIGTERM, N-instance/multi-region (L8/L10).

## 7. Non-goals (for now)
- Rewriting to another language/runtime.
- A full web UI (status endpoint only).
- Managing instance lifecycle after successful launch (this tool wins capacity, then hands off).

## 8. Success metrics
- **Time-to-capacity**: median attempts / wall-clock until a successful launch (lower is better).
- **Throttle rate**: fraction of attempts that return 429 (should trend toward ~0 with correct backoff).
- **API efficiency**: launch attempts per successful launch, and validation calls per hour.
- **Reliability**: successful resume after restart; zero duplicate instances.

## 9. Open decisions summary (need your call)
1. **[3.1]** Conservative fixed rate defaults now, auto-learned rate later? (rec: yes)
2. **[3.2]** Concurrency model = bounded thread pool? Max workers? Multi-region in v1? (rec: thread pool, 2–4 workers, region later)
3. **[4.1]** Config source of truth — keep `.ini` + layer env/flags? (rec: yes)
4. **[4.2]** Control surface — Telegram commands first, HTTP status second? (rec: yes)
5. **Scope/priority:** which phases do you want first? (rec: Phase 0 → 1 → 2)
