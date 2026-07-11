"""Launch orchestration: single attempts, per-target retry loop, and the engine.

The :class:`Launcher` is deliberately small and dependency-injected so it can be
unit tested against :class:`occfix.gateway.FakeOciGateway` with no real waiting.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable

from occfix.backoff import BackoffPolicy
from occfix.capacity import CapacityHeatmap
from occfix.config import AppConfig
from occfix.gateway import OciGateway
from occfix.models import (
    AttemptOutcome,
    AttemptResult,
    AuthError,
    LaunchError,
    LaunchResult,
    LaunchSpec,
)
from occfix.notify import Dispatcher, NotifyEvent
from occfix.observability import Metrics, get_metrics
from occfix.ratelimit import AdaptiveRateLimiter
from occfix.scheduler import ConcurrentSweeper
from occfix.state import NullStateStore, StateStore

log = logging.getLogger("occfix.launcher")

# Backoff severity: a throttle in the round should dominate the wait decision.
_SEVERITY = {
    AttemptResult.THROTTLED: 3,
    AttemptResult.TRANSIENT: 2,
    AttemptResult.CAPACITY: 1,
    AttemptResult.SUCCESS: 0,
}


class Launcher:
    """Drives launch attempts for a single target."""

    def __init__(
        self,
        gateway: OciGateway,
        config: AppConfig,
        *,
        backoff: BackoffPolicy | None = None,
        ratelimiter: AdaptiveRateLimiter | None = None,
        state: StateStore | None = None,
        heatmap: CapacityHeatmap | None = None,
        dispatcher: Dispatcher | None = None,
        metrics: Metrics | None = None,
        sleep_func: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        milestone_every: int = 10,
    ) -> None:
        self.gateway = gateway
        self.config = config
        self.backoff = backoff or BackoffPolicy(config.retry)
        self.ratelimiter = ratelimiter or AdaptiveRateLimiter(config.ratelimit)
        self.state = state or NullStateStore()
        self.heatmap = heatmap or CapacityHeatmap()
        self.dispatcher = dispatcher
        self.metrics = metrics or get_metrics()
        self.sleep = sleep_func
        self.clock = clock
        self.milestone_every = milestone_every

    # -- single attempt --------------------------------------------------
    def attempt_once(self, spec: LaunchSpec, ad: str) -> AttemptOutcome:
        """Perform one rate-limited launch attempt against one AD."""

        self.ratelimiter.acquire()
        token = uuid.uuid4().hex
        started = self.clock()
        try:
            instance_id = self.gateway.launch_instance(spec, ad, token)
            outcome = AttemptOutcome(
                result=AttemptResult.SUCCESS,
                ad=ad,
                spec_name=spec.name,
                instance_id=instance_id,
                latency=self.clock() - started,
            )
        except LaunchError as exc:
            outcome = AttemptOutcome(
                result=exc.result,
                ad=ad,
                spec_name=spec.name,
                code=exc.code,
                message=exc.message,
                retry_after=exc.retry_after,
                latency=self.clock() - started,
            )
        except Exception as exc:  # pragma: no cover - defensive
            outcome = AttemptOutcome(
                result=AttemptResult.TRANSIENT,
                ad=ad,
                spec_name=spec.name,
                message=str(exc),
                latency=self.clock() - started,
            )

        self._record(outcome)
        return outcome

    def _record(self, outcome: AttemptOutcome) -> None:
        if outcome.result is AttemptResult.THROTTLED:
            self.ratelimiter.on_throttle()
        else:
            self.ratelimiter.on_success()

        self.state.record_attempt(outcome.spec_name, outcome.ad, outcome.result)
        self.heatmap.record(outcome.ad, outcome.result)
        self.metrics.inc_counter(
            "occfix_attempts_total", result=outcome.result.value, ad=outcome.ad
        )
        if outcome.result is AttemptResult.CAPACITY:
            self.metrics.inc_counter("occfix_capacity_miss_total", ad=outcome.ad)
        elif outcome.result is AttemptResult.THROTTLED:
            self.metrics.inc_counter("occfix_throttled_total", ad=outcome.ad)
        if outcome.latency is not None:
            self.metrics.observe("occfix_attempt_latency_seconds", outcome.latency)

    # -- per-target loop -------------------------------------------------
    def run_target(
        self,
        spec: LaunchSpec,
        *,
        stop_event: threading.Event | None = None,
        max_attempts: int = 0,
        max_rounds: int = 0,
    ) -> LaunchResult | None:
        """Retry until the target launches, a fatal error occurs, or we stop."""

        stop_event = stop_event or threading.Event()
        self._notify("started", f"Hunting capacity: {spec.name}", spec.shape)

        reason = self.validate(spec)
        if reason:
            log.critical("Validation failed for %s: %s", spec.name, reason)
            self._notify("error", "Validation failed", reason)
            return None

        sweeper = ConcurrentSweeper(self.config.ratelimit.concurrency)
        prev_delay = self.backoff.initial()
        attempts = 0
        rounds = 0

        while not stop_event.is_set():
            ads = self.heatmap.order(list(spec.availability_domains))
            outcomes = sweeper.map(lambda ad: self.attempt_once(spec, ad), ads)
            attempts += len(outcomes)
            rounds += 1

            for outcome in outcomes:
                if outcome.is_success and outcome.instance_id:
                    return self._handle_success(spec, outcome, attempts)

            if any(o.result is AttemptResult.AUTH_ERROR for o in outcomes):
                raise AuthError(
                    "authentication/authorization failed during launch; stopping",
                    code=next(
                        (o.code for o in outcomes if o.result is AttemptResult.AUTH_ERROR),
                        None,
                    ),
                )
            if any(o.result is AttemptResult.FATAL for o in outcomes):
                fatal = next(o for o in outcomes if o.result is AttemptResult.FATAL)
                log.critical("Fatal error for %s: %s", spec.name, fatal.message)
                self._notify("error", "Fatal launch error", fatal.message)
                return None

            worst = max(outcomes, key=lambda o: _SEVERITY.get(o.result, 0))
            retry_after = max(
                (o.retry_after or 0.0 for o in outcomes if o.result is AttemptResult.THROTTLED),
                default=0.0,
            )
            delay = self.backoff.next_delay(
                worst.result, prev_delay, retry_after=retry_after or None
            )
            prev_delay = delay
            self.metrics.set_gauge("occfix_current_interval_seconds", delay)
            self.metrics.set_gauge(
                "occfix_rate_limit_permits_per_sec", self.ratelimiter.current_rate
            )

            if attempts % self.milestone_every == 0:
                self._notify(
                    "attempt_milestone",
                    f"Still hunting {spec.name}",
                    f"attempts={attempts} last={worst.result.value} next={delay:.1f}s",
                )
            log.info(
                "%s: %d attempts, last=%s, next retry in %.1fs (rate=%.2f/s)",
                spec.name,
                attempts,
                worst.result.value,
                delay,
                self.ratelimiter.current_rate,
            )

            if max_attempts and attempts >= max_attempts:
                break
            if max_rounds and rounds >= max_rounds:
                break
            if stop_event.wait(delay):
                break

        return None

    def _handle_success(
        self, spec: LaunchSpec, outcome: AttemptOutcome, attempts: int
    ) -> LaunchResult:
        instance_id = outcome.instance_id or ""
        public_ip = None
        try:
            public_ip = self.gateway.get_public_ip(spec.compartment_id, instance_id)
        except Exception as exc:  # pragma: no cover - best effort
            log.warning("Could not fetch public IP: %s", exc)

        self.state.record_launch(spec.name, instance_id, outcome.ad)
        self.metrics.inc_counter("occfix_launch_success_total", ad=outcome.ad)
        log.info("Instance launched: %s (IP: %s)", instance_id, public_ip)
        self._notify(
            "launched",
            "Instance launched!",
            f"id={instance_id} ip={public_ip} ad={outcome.ad} attempts={attempts}",
            data={
                "instance_id": instance_id,
                "public_ip": public_ip,
                "availability_domain": outcome.ad,
                "attempts": attempts,
            },
        )
        return LaunchResult(
            spec_name=spec.name,
            instance_id=instance_id,
            availability_domain=outcome.ad,
            public_ip=public_ip,
            total_attempts=attempts,
        )

    # -- validation ------------------------------------------------------
    def validate(self, spec: LaunchSpec) -> str | None:
        """Pre-flight quota/storage/duplicate checks. Returns a reason or None.

        Raises :class:`AuthError` when the gateway reports an auth/permission
        problem, so the engine can stop instead of looping forever.
        """

        limits = self.config.limits
        try:
            total_storage = sum(
                v.size_in_gbs for v in self.gateway.list_volumes(spec.compartment_id) if v.is_active
            )
            for ad in spec.availability_domains:
                total_storage += sum(
                    bv.size_in_gbs
                    for bv in self.gateway.list_boot_volumes(spec.compartment_id, ad)
                    if bv.is_active
                )
            free = limits.max_total_storage_gb - total_storage
            if not spec.uses_boot_volume() and free < spec.boot_volume_size:
                return f"storage limit exceeded: {free}GB free < {spec.boot_volume_size}GB needed"

            instances = [i for i in self.gateway.list_instances(spec.compartment_id) if i.is_active]
            if spec.display_name in [i.display_name for i in instances]:
                return f"an instance named {spec.display_name!r} already exists"

            if spec.machine_type.upper() == "ARM":
                arm = [i for i in instances if i.shape == "VM.Standard.A1.Flex"]
                used_ocpus = sum(i.ocpus for i in arm)
                used_mem = sum(i.memory_in_gbs for i in arm)
                if used_ocpus + spec.ocpus > limits.arm_max_ocpus:
                    return f"ARM OCPU quota exceeded (max {limits.arm_max_ocpus})"
                if used_mem + spec.memory > limits.arm_max_memory_gb:
                    return f"ARM memory quota exceeded (max {limits.arm_max_memory_gb}GB)"
            return None
        except AuthError:
            raise
        except Exception as exc:
            code = getattr(exc, "code", None)
            status = getattr(exc, "status", None)
            from occfix.models import classify_oci_code

            if classify_oci_code(code, status) is AttemptResult.AUTH_ERROR:
                raise AuthError(str(exc), code=code, status=status) from exc
            return f"validation error: {exc}"

    def _notify(
        self, event_type: str, title: str, message: str, *, data: dict | None = None
    ) -> None:
        if self.dispatcher is None:
            return
        self.dispatcher.notify(
            NotifyEvent(type=event_type, title=title, message=message, data=data or {})
        )


class Engine:
    """Wires config + gateway into launchers and runs all configured targets."""

    def __init__(
        self,
        config: AppConfig,
        gateway: OciGateway,
        *,
        state: StateStore | None = None,
        dispatcher: Dispatcher | None = None,
        metrics: Metrics | None = None,
        sleep_func: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.gateway = gateway
        self.state = state
        self.dispatcher = dispatcher
        self.metrics = metrics or get_metrics()
        self.sleep = sleep_func

    def _make_launcher(self) -> Launcher:
        return Launcher(
            self.gateway,
            self.config,
            state=self.state,
            dispatcher=self.dispatcher,
            metrics=self.metrics,
            sleep_func=self.sleep,
        )

    def validate_all(self) -> dict[str, str | None]:
        """Dry-run: validate every target and return {name: reason_or_None}."""

        launcher = self._make_launcher()
        return {spec.name: launcher.validate(spec) for spec in self.config.targets}

    def run(
        self,
        *,
        stop_event: threading.Event | None = None,
        max_attempts: int = 0,
        max_rounds: int = 0,
    ) -> list[LaunchResult]:
        """Run all targets sequentially; each sweeps its ADs concurrently."""

        results: list[LaunchResult] = []
        launcher = self._make_launcher()
        for spec in self.config.targets:
            result = launcher.run_target(
                spec,
                stop_event=stop_event,
                max_attempts=max_attempts,
                max_rounds=max_rounds,
            )
            if result is not None:
                results.append(result)
        if self.dispatcher is not None:
            self.dispatcher.flush()
        return results
