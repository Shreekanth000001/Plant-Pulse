import logging
import os
import time
from collections.abc import Callable

logger = logging.getLogger("simulator-watchdog")


class Watchdog:
    """Heartbeat-as-run watchdog with runtime cap and idle-period auto-reset.

    - The presence of heartbeats is the run signal.
    - If 30 seconds elapse with no heartbeat received, watchdog stops simulation.
    - When a new heartbeat is received, simulation resumes immediately.
    - If total running time reaches max_runtime_seconds, simulation stops and
      remains stopped even if heartbeats continue (runtime cap, section 6.2).
    - Heartbeats arriving while capped do NOT restart it early.
    - After a configurable idle period with no heartbeats (cap_reset_idle_seconds,
      env var SIMULATOR_CAP_RESET_IDLE_SECONDS, default 600s), a new heartbeat
      starts a fresh run with the accumulated runtime reset.
    - Clock is injectable for deterministic tests without real sleeps.
    """

    def __init__(
        self,
        timeout_seconds: float = 30.0,
        max_runtime_seconds: float = 7200.0,
        cap_reset_idle_seconds: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_runtime_seconds = max_runtime_seconds
        self.cap_reset_idle_seconds = (
            cap_reset_idle_seconds
            if cap_reset_idle_seconds is not None
            else float(
                os.getenv(
                    "SIMULATOR_CAP_RESET_IDLE_SECONDS",
                    os.getenv("CAP_RESET_IDLE_SECONDS", "600.0"),
                )
            )
        )
        self.clock = clock

        self._running = False
        self._last_heartbeat_at: float | None = None
        self._total_runtime: float = 0.0
        self._last_check_at: float | None = None
        self._capped = False
        self._just_capped = False

    def is_running(self) -> bool:
        return self._running

    def cap_exceeded(self) -> bool:
        return self._capped or self._total_runtime >= self.max_runtime_seconds

    def pop_just_capped(self) -> bool:
        """Return True once when the transition into capped state happens."""
        val = self._just_capped
        self._just_capped = False
        return val

    def _accumulate_runtime(self, now: float) -> None:
        if self._running and self._last_check_at is not None:
            delta = max(0.0, now - self._last_check_at)
            self._total_runtime += delta
            self._last_check_at = now
            if self._total_runtime >= self.max_runtime_seconds:
                logger.warning(
                    "Simulator reached max runtime cap (%.1f / %.1fs); entering idle",
                    self._total_runtime,
                    self.max_runtime_seconds,
                )
                if not self._capped:
                    self._just_capped = True
                self._capped = True
                self._running = False

    def on_heartbeat(self) -> None:
        """Called when a heartbeat message is received from the platform."""
        now = self.clock()
        self._accumulate_runtime(now)

        if self.cap_exceeded():
            idle_silence = (
                (now - self._last_heartbeat_at)
                if self._last_heartbeat_at is not None
                else float("inf")
            )
            if idle_silence >= self.cap_reset_idle_seconds:
                logger.info(
                    "Heartbeat received after %.1fs idle silence (>= %.1fs); resetting runtime and starting fresh run",
                    idle_silence,
                    self.cap_reset_idle_seconds,
                )
                self._total_runtime = 0.0
                self._capped = False
                self._just_capped = False
                self._running = True
                self._last_heartbeat_at = now
                self._last_check_at = now
                return

            logger.info(
                "Heartbeat received but simulator runtime cap exceeded (%.1fs) and idle silence (%.1fs < %.1fs); staying idle",
                self.max_runtime_seconds,
                idle_silence,
                self.cap_reset_idle_seconds,
            )
            self._last_heartbeat_at = now
            self._running = False
            return

        self._last_heartbeat_at = now

        if not self._running:
            logger.info("Heartbeat received: resuming simulation")
            self._running = True
            self._last_check_at = now

    def should_run(self) -> bool:
        """Update runtime tracking, evaluate watchdog timeout and runtime cap."""
        now = self.clock()

        if not self._running:
            return False

        self._accumulate_runtime(now)

        # 1. Check runtime cap
        if self._total_runtime >= self.max_runtime_seconds:
            return False

        # 2. Check heartbeat silence
        if (
            self._last_heartbeat_at is None
            or (now - self._last_heartbeat_at) > self.timeout_seconds
        ):
            logger.info(
                "Watchdog triggered: no heartbeat received for >%.1fs; entering idle",
                self.timeout_seconds,
            )
            self._running = False
            return False

        return True
