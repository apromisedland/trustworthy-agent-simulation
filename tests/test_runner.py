import json

import pytest

from tass.config import ScenarioConfig
from tass.runner import RunLease, replay, run_simulation
from tass.scenarios.town import TownScenario
from tass.storage import RunStore, encode


async def test_resume_matches_uninterrupted_run(config, tmp_path):
    complete_dir = tmp_path / "complete"
    resumed_dir = tmp_path / "resumed"
    assert (await run_simulation(config, complete_dir))["status"] == "completed"
    assert (await run_simulation(config, resumed_dir, max_ticks=3))["status"] == "paused"
    assert (await run_simulation(config, resumed_dir, resume=True))["status"] == "completed"
    complete, resumed = RunStore(complete_dir), RunStore(resumed_dir)
    try:
        assert encode(complete.snapshot()) == encode(resumed.snapshot())
        assert complete.events() == resumed.events()
        assert complete.metrics() == resumed.metrics()
        for tick in range(config.total_ticks):
            for actor_id in complete.snapshot()["actors"]:
                assert complete.observation(tick, actor_id) == resumed.observation(tick, actor_id)
        usage = complete.usage()
        assert replay(complete_dir, 2)["snapshot"]["tick"] == 3
        assert complete.usage() == usage
        assert usage["requests"] == 0
    finally:
        complete.close()
        resumed.close()


async def test_plugin_restoration_used_for_resume_and_replay(config, tmp_path, monkeypatch):
    restored_ticks = []
    original = TownScenario.restore_world

    def restore_world(self, saved_config, snapshot):
        restored_ticks.append(snapshot["tick"])
        return original(self, saved_config, snapshot)

    monkeypatch.setattr(TownScenario, "restore_world", restore_world)
    await run_simulation(config, tmp_path, max_ticks=2)
    await run_simulation(config, tmp_path, resume=True)
    replay(tmp_path, 0)
    assert restored_ticks == [2, 1]


async def test_duplicate_worker_cannot_change_status(config, tmp_path):
    await run_simulation(config, tmp_path, max_ticks=1)
    store = RunStore(tmp_path)
    store.set("status", "running")
    with RunLease(tmp_path), pytest.raises(RuntimeError, match="active worker"):
        await run_simulation(config, tmp_path, resume=True)
    assert store.get("status") == "running"
    store.close()


async def test_public_goods_plugin(config, tmp_path):
    config.scenario = "public_goods"
    config.scenario_options = {"multiplier": 1.5}
    result = await run_simulation(config, tmp_path)
    assert result["status"] == "completed"
    store = RunStore(tmp_path)
    try:
        assert store.metrics()[0]["contributions"] > 0
        assert store.snapshot()["policy_spending"] > 0
        assert store.metrics()[-1]["money_total"] == store.metrics()[0]["money_total"]
    finally:
        store.close()


async def test_frozen_configuration(config, tmp_path):
    await run_simulation(config, tmp_path, max_ticks=1)
    modified = config.model_copy(update={"seed": 9})
    with pytest.raises(ValueError, match="exact saved"):
        await run_simulation(modified, tmp_path, resume=True)


async def test_default_town_end_to_end(tmp_path):
    result = await run_simulation(ScenarioConfig(), tmp_path)
    assert result["ticks"] == 28
    assert result["status"] == "completed"
    store = RunStore(tmp_path)
    try:
        assert len(store.snapshot()["actors"]) == 24
        kinds = {event["kind"] for event in store.events()}
        assert {
            "worked",
            "produced",
            "consumed",
            "contract_fulfilled",
            "message",
            "attended",
        } <= kinds
        manifest = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
        assert manifest["validation"] == "offline-baseline"
        assert manifest["usage"]["requests"] == 0
        for tick in range(-1, 28):
            assert replay(tmp_path, tick)["snapshot"]["tick"] == tick + 1
    finally:
        store.close()
