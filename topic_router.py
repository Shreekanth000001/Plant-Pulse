import inspect
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar


@dataclass
class TopicMatch:
    route_type: str
    params: dict[str, str]
    handler: Callable | None = None


class TopicRouter:
    """Dynamic MQTT topic router for PlantPulse platform topics scoped by plant_id."""

    # Canonical route specifications from Section 4.1
    DEFAULT_ROUTES: ClassVar[list[tuple[str, str]]] = [
        (
            "telemetry",
            r"^plants/(?P<plant_id>[a-z0-9_]+)/assets/(?P<machine_code>[a-z0-9_]+)/telemetry$",
        ),
        (
            "state",
            r"^plants/(?P<plant_id>[a-z0-9_]+)/assets/(?P<machine_code>[a-z0-9_]+)/state$",
        ),
        (
            "stage_event",
            r"^plants/(?P<plant_id>[a-z0-9_]+)/modules/traceability/stage_event$",
        ),
        (
            "queue_depths",
            r"^plants/(?P<plant_id>[a-z0-9_]+)/modules/traceability/queue_depths$",
        ),
        ("qc_result", r"^plants/(?P<plant_id>[a-z0-9_]+)/modules/quality/qc_result$"),
        ("heartbeat", r"^plants/(?P<plant_id>[a-z0-9_]+)/control/heartbeat$"),
    ]

    def __init__(self) -> None:
        self._routes: list[tuple[str, re.Pattern]] = [
            (route_type, re.compile(pattern))
            for route_type, pattern in self.DEFAULT_ROUTES
        ]
        self._handlers: dict[str, Callable] = {}

    def add_route(self, route_type: str, pattern: str) -> None:
        """Register a custom regex pattern for a route type."""
        self._routes.append((route_type, re.compile(pattern)))

    def on(self, route_type: str) -> Callable[[Callable], Callable]:
        """Decorator to register a handler for a specific route type."""

        def decorator(handler: Callable) -> Callable:
            self._handlers[route_type] = handler
            return handler

        return decorator

    def match(self, topic: str) -> TopicMatch | None:
        """Match an MQTT topic against registered route patterns."""
        for route_type, pattern in self._routes:
            match = pattern.match(topic)
            if match:
                return TopicMatch(
                    route_type=route_type,
                    params=match.groupdict(),
                    handler=self._handlers.get(route_type),
                )
        return None

    async def dispatch(self, topic: str, payload: Any) -> Any:
        """Dispatch a message to its registered handler, awaiting if coroutine."""
        matched = self.match(topic)
        if not matched or not matched.handler:
            return None

        kwargs = {"payload": payload, **matched.params}
        handler = matched.handler

        if inspect.iscoroutinefunction(handler):
            return await handler(**kwargs)

        res = handler(**kwargs)
        if inspect.isawaitable(res):
            return await res
        return res

    def subscription_patterns(self) -> list[str]:
        """Return MQTT topic filter patterns for broker subscription."""
        return ["plants/#"]
