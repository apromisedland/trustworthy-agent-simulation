import httpx2 as httpx
import pytest
from conftest import ControlledProvider

from tass.llm import BudgetExceeded, BudgetTransport
from tass.runner import run_simulation
from tass.storage import RunStore


async def test_real_agentscope_toolchain_with_controlled_provider(llm_config, tmp_path):
    provider = ControlledProvider()
    result = await run_simulation(
        llm_config, tmp_path, max_ticks=2, controller_factory=provider.controller
    )
    assert result["status"] == "paused"
    store = RunStore(tmp_path)
    try:
        assert store.snapshot()["actors"]["resident_00"]["consumed"] == 2
        assert store.snapshot()["actors"]["resident_01"]["consumed"] == 1
        assert any(event["kind"] == "message" for event in store.events())
        assert all(metric["decision_failures"] == 0 for metric in store.metrics())
        assert store.get("validation") == "controlled-provider"
        assert result["usage"]["requests"] == len(provider.requests)
        assert result["usage"]["requests"] > 0
        raw = "".join(row[0] for row in store.connection.execute("SELECT request FROM calls"))
        assert "fixture-only-not-a-real-key" not in raw
        assert store.connection.execute("SELECT COUNT(*) FROM traces").fetchone()[0] == 16
    finally:
        store.close()


async def test_budget_is_persistent_and_has_no_baseline_fallback(llm_config, tmp_path):
    provider = ControlledProvider()
    llm_config.budget.requests = 2
    first = await run_simulation(llm_config, tmp_path, controller_factory=provider.controller)
    assert first["status"] == "budget_exhausted"
    assert first["ticks"] == 0
    assert first["usage"]["requests"] == 2
    second = await run_simulation(
        llm_config, tmp_path, resume=True, controller_factory=provider.controller
    )
    assert second["status"] == "budget_exhausted"
    assert len(provider.requests) == 2


async def test_retries_count_actual_http_requests(llm_config, tmp_path, monkeypatch):
    async def immediate_sleep(delay):
        return None

    monkeypatch.setattr("tass.llm.asyncio.sleep", immediate_sleep)
    llm_config.model.retries = 2
    attempts = []

    def failure(request):
        attempts.append(request)
        return httpx.Response(503, json={"error": "temporary outage"})

    store = RunStore(tmp_path)
    transport = BudgetTransport(
        store,
        llm_config,
        llm_config.model,
        0,
        "resident_00",
        "test-key",
        httpx.MockTransport(failure),
    )
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.post(
            "https://fixture.invalid/v1/chat/completions", json={"max_tokens": 100, "messages": []}
        )
    assert response.status_code == 503
    assert len(attempts) == store.usage()["requests"] == 3
    assert store.usage()["estimated_calls"] == 3
    assert store.usage()["output_tokens"] == 300
    store.close()


async def test_token_reservation_stops_before_network(llm_config, tmp_path):
    llm_config.budget.input_tokens = 1
    store = RunStore(tmp_path)

    def forbidden(request):
        pytest.fail("Network transport must not run when budget cannot reserve the request")

    transport = BudgetTransport(
        store, llm_config, llm_config.model, 0, "resident_00", "key", httpx.MockTransport(forbidden)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(BudgetExceeded):
            await client.post("https://fixture.invalid", json={"messages": []})
    assert store.usage()["requests"] == 0
    store.close()


async def test_missing_credentials_does_not_call_provider(config, tmp_path, monkeypatch):
    config.mode = "llm"
    monkeypatch.delenv("TASS_API_KEY", raising=False)
    with pytest.raises(ValueError, match="Configure"):
        await run_simulation(config, tmp_path)
    store = RunStore(tmp_path)
    assert store.get("status") == "failed"
    assert store.usage()["requests"] == 0
    store.close()


async def test_completed_http_responses_are_reused_after_interrupted_decision(llm_config, tmp_path):
    from tass.scenarios.town import TownScenario

    scenario = TownScenario()
    world = scenario.build_world(llm_config)
    scenario.begin_tick(world)
    observation = scenario.observe(world, "resident_00")
    provider = ControlledProvider()
    store = RunStore(tmp_path)
    controller = provider.controller(llm_config, store)
    first = await controller.decide("resident_00", observation)
    usage = store.usage()
    second = await controller.decide("resident_00", observation)
    assert first.model_dump() == second.model_dump()
    assert first.actions
    assert store.usage() == usage
    assert len(provider.requests) == usage["requests"]
    store.close()


async def test_failed_provider_never_executes_baseline_actions(llm_config, tmp_path):
    from tass.llm import LLMController

    def failure(request):
        return httpx.Response(503, json={"error": {"message": "offline test failure"}})

    def controller(config, store):
        return LLMController(config, store, lambda: httpx.MockTransport(failure))

    await run_simulation(llm_config, tmp_path, max_ticks=1, controller_factory=controller)
    store = RunStore(tmp_path)
    try:
        assert store.metrics()[0]["decision_failures"] == 8
        assert store.metrics()[0]["consumption"] == 0
        assert not any(event["kind"] == "action_accepted" for event in store.events())
    finally:
        store.close()
