import json

from conftest import ControlledProvider

from tass.experiments import run_batch


async def test_policy_matrix_uses_independent_runs(config, tmp_path):
    config.days = 3
    result = await run_batch(config, tmp_path, seeds=(11, 22))
    assert result["runs"] == 8
    assert result["status"] == "completed"
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert all(record["independent_runs"] == 2 for record in summary)
    effects = json.loads((tmp_path / "paired_effects.json").read_text())
    subsidy = next(
        record
        for record in effects
        if record["condition"] == "subsidy-500_disclosure-0"
        and record["metric"] == "policy_spending"
    )
    assert subsidy["mean"] == 2500
    assert subsidy["ci95_low"] == subsidy["ci95_high"] == 2500


async def test_batch_has_one_persistent_llm_budget(llm_config, tmp_path):
    llm_config.days = 1
    llm_config.slots_per_day = 1
    llm_config.budget.requests = 18
    provider = ControlledProvider()
    result = await run_batch(
        llm_config, tmp_path, seeds=(11, 22), controller_factory=provider.controller
    )
    assert result["runs"] == 1
    assert result["status"] == "budget_exhausted"
    assert len(provider.requests) == result["usage"]["requests"] == 18
    again = await run_batch(
        llm_config, tmp_path, seeds=(11, 22), controller_factory=provider.controller
    )
    assert again["usage"]["requests"] == 18
    assert len(provider.requests) == 18
