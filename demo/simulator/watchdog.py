import logging
import time
from collections.abc import Callable

logger = logging.getLogger("simulator-watchdog")


class Watchdog:
    """Heartbeat-as-run watchdog with runtime cap.

    - The presence of heartbeats is the run signal.
    - If 30 seconds elapse with no heartbeat received, watchdog stops simulation.
    - When a new heartbeat is received, simulation resumes immediately.
    - If total running time reaches max_runtime_seconds, simulation stops and
      remains stopped even if heartbeats continue (runtime cap, section 6.2).
    - Clock is injectable for deterministic tests without real sleeps.
    """

    def __init__(
        self,
        timeout_seconds: float = 30.0,
        max_runtime_seconds: float = 7200.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_runtime_seconds = max_runtime_seconds
        self.clock = clock

        self._running = False
        self._last_heartbeat_at: float | None = None
        self._total_runtime: float = 0.0
        self._last_check_at: float | None = None

    def is_running(self) -> bool:
        return self._running

    def cap_exceeded(self) -> bool:
        return self._total_runtime >= self.max_runtime_seconds

    def on_heartbeat(self) -> None:
        """Called when a heartbeat message is received from the platform."""
        now = self.clock()
        self._last_heartbeat_at = now

        if self.cap_exceeded():
            logger.info(
                "Heartbeat received but simulator runtime cap exceeded (%.1fs); staying idle",
                self.max_runtime_seconds,
            )
            self._running = False
            return

        if not self._running:
            logger.info("Heartbeat received: resuming simulation")
            self._running = True
            self._last_check_at = now

    def should_run(self) -> bool:
        """Update runtime tracking, evaluate watchdog timeout and runtime cap."""
        now = self.clock()

        if not self._running:
            return False

        # Accumulate runtime if currently running
        if self._last_check_at is not None:
            delta = max(0.0, now - self._last_check_at)
            self._total_runtime += delta
        self._last_check_at = now

        # 1. Check runtime cap
        if self._total_runtime >= self.max_runtime_seconds:
            logger.warning(
                "Simulator reached max runtime cap (%.1f / %.1fs); entering idle",
                self._total_runtime,
                self.max_runtime_seconds,
            )
            self._running = False
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
