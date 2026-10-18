import pytest

from topic_router import TopicRouter


def test_route_matching_canonical_topics():
    """Criterion 4: Parsing of all canonical topic paths from Section 4.1."""
    router = TopicRouter()

    # 1. Telemetry
    m = router.match("plants/plant_demo_membrane/assets/hm_01/telemetry")
    assert m is not None
    assert m.route_type == "telemetry"
    assert m.params == {"plant_id": "plant_demo_membrane", "machine_code": "hm_01"}

    # 2. State
    m = router.match("plants/plant_water_district_9/assets/pump_01/state")
    assert m is not None
    assert m.route_type == "state"
    assert m.params == {"plant_id": "plant_water_district_9", "machine_code": "pump_01"}

    # 3. Stage event
    m = router.match("plants/plant_demo_membrane/modules/traceability/stage_event")
    assert m is not None
    assert m.route_type == "stage_event"
    assert m.params == {"plant_id": "plant_demo_membrane"}

    # 4. Queue depths
    m = router.match("plants/plant_demo_membrane/modules/traceability/queue_depths")
    assert m is not None
    assert m.route_type == "queue_depths"
    assert m.params == {"plant_id": "plant_demo_membrane"}

    # 5. QC result
    m = router.match("plants/plant_demo_membrane/modules/quality/qc_result")
    assert m is not None
    assert m.route_type == "qc_result"
    assert m.params == {"plant_id": "plant_demo_membrane"}

    # 6. Heartbeat control
    m = router.match("plants/plant_demo_membrane/control/heartbeat")
    assert m is not None
    assert m.route_type == "heartbeat"
    assert m.params == {"plant_id": "plant_demo_membrane"}


def test_route_unmatched_topics():
    """Criterion 4: Rejection and non-matching of invalid topic patterns."""
    router = TopicRouter()

    # Legacy topic
    assert router.match("factory/housing/hm_01/telemetry") is None

    # Missing components
    assert router.match("plants/plant_demo_membrane") is None
    assert router.match("plants/plant_demo_membrane/assets") is None
    assert router.match("plants/plant_demo_membrane/random_thing") is None

    # Extra suffix
    assert (
        router.match("plants/plant_demo_membrane/assets/hm_01/telemetry/extra") is None
    )


@pytest.mark.anyio
async def test_router_dispatch_sync_and_async_handlers():
    """Criterion 4: Dispatching messages to registered sync and async handlers."""
    router = TopicRouter()
    dispatched_sync = []
    dispatched_async = []

    @router.on("telemetry")
    def handle_telemetry(payload: dict, plant_id: str, machine_code: str):
        dispatched_sync.append(
            {"payload": payload, "plant_id": plant_id, "machine_code": machine_code}
        )

    @router.on("state")
    async def handle_state(payload: dict, plant_id: str, machine_code: str):
        dispatched_async.append(
            {"payload": payload, "plant_id": plant_id, "machine_code": machine_code}
        )

    telemetry_payload = {"vibration": 1.2}
    await router.dispatch(
        "plants/plant_demo_membrane/assets/hm_01/telemetry",
        telemetry_payload,
    )
    assert len(dispatched_sync) == 1
    assert dispatched_sync[0]["plant_id"] == "plant_demo_membrane"
    assert dispatched_sync[0]["machine_code"] == "hm_01"
    assert dispatched_sync[0]["payload"] == telemetry_payload

    state_payload = {"state": "RUNNING"}
    await router.dispatch(
        "plants/plant_water_district_9/assets/pump_01/state",
        state_payload,
    )
    assert len(dispatched_async) == 1
    assert dispatched_async[0]["plant_id"] == "plant_water_district_9"
    assert dispatched_async[0]["machine_code"] == "pump_01"


def test_router_subscription_patterns():
    """Criterion 4: Topic router provides canonical subscription patterns."""
    router = TopicRouter()
    patterns = router.subscription_patterns()
    assert "plants/#" in patterns or any(p.startswith("plants/") for p in patterns)
