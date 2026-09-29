"""Run-level policy and ablation comparisons with a shared matrix budget."""

import csv
import json
import math
import statistics
from pathlib import Path

from scipy.stats import t as student_t

from tass.config import ScenarioConfig
from tass.runner import RunLease, run_simulation
from tass.storage import RunStore


def conditions(config: ScenarioConfig, suite: str):
    result = []
    if suite == "policy":
        for subsidy in (0, 500):
            for disclosure in (False, True):
                variant = config.model_copy(deep=True)
                variant.policies.subsidy = subsidy
                variant.policies.source_disclosure = disclosure
                result.append((f"subsidy-{subsidy}_disclosure-{int(disclosure)}", variant))
    elif suite == "ablation":
        for name, memory, communication in (
            ("full", "provenance", True),
            ("no-communication", "provenance", False),
            ("no-memory", "none", True),
            ("summary", "summary", True),
        ):
            variant = config.model_copy(deep=True)
            variant.memory = memory
            variant.communication = communication
            result.append((name, variant))
    else:
        raise ValueError("Suite must be policy or ablation")
    return result


def describe(values):
    mean = statistics.mean(values)
    standard_error = statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else None
    radius = (
        float(student_t.ppf(0.975, len(values) - 1) * standard_error)
        if standard_error is not None
        else None
    )
    return {
        "independent_runs": len(values),
        "mean": mean,
        "standard_error": standard_error,
        "ci95_low": mean - radius if radius is not None else None,
        "ci95_high": mean + radius if radius is not None else None,
    }


def export_comparison(directory, records, variants):
    if not records:
        return
    with (directory / "runs.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    summaries, effects = [], []
    reference = variants[0][0]
    reference_runs = {
        record["seed"]: record for record in records if record["condition"] == reference
    }
    for condition, _ in variants:
        selected = [record for record in records if record["condition"] == condition]
        if not selected:
            continue
        for metric in records[0]:
            if metric in ("condition", "seed", "tick", "day"):
                continue
            values = [record[metric] for record in selected]
            if any(not isinstance(value, (int, float)) for value in values):
                continue
            summaries.append({"condition": condition, "metric": metric, **describe(values)})
            differences = [
                record[metric] - reference_runs[record["seed"]][metric]
                for record in selected
                if record["seed"] in reference_runs
                and isinstance(reference_runs[record["seed"]][metric], (int, float))
            ]
            if condition != reference and differences:
                effects.append(
                    {
                        "condition": condition,
                        "reference": reference,
                        "metric": metric,
                        **describe(differences),
                    }
                )
    for name, data in (("summary", summaries), ("paired_effects", effects)):
        (directory / f"{name}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


async def run_batch(config, directory, suite="policy", seeds=(11, 22, 33), controller_factory=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    records = []
    usage = {"requests": 0, "input_tokens": 0, "output_tokens": 0}
    variants = conditions(config, suite)
    specification = {"config": config.model_dump(), "suite": suite, "seeds": list(seeds)}
    manifest_path = directory / "batch.json"
    with RunLease(directory):
        if manifest_path.exists():
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
            if previous["specification"] != specification:
                raise ValueError("Batch directory belongs to a different frozen specification")
        status = "completed"
        for condition, variant in variants:
            for seed in seeds:
                current = variant.model_copy(update={"seed": seed}, deep=True)
                run_dir = directory / f"{condition}_seed-{seed}"
                existing = (run_dir / "run.sqlite").exists()
                if existing:
                    store = RunStore(run_dir)
                    try:
                        current = ScenarioConfig.model_validate(store.get("config"))
                    finally:
                        store.close()
                elif config.mode == "llm":
                    remaining = {
                        name: getattr(config.budget, name) - amount
                        for name, amount in usage.items()
                    }
                    if min(remaining.values()) <= 0:
                        status = "budget_exhausted"
                        break
                    for name, amount in remaining.items():
                        setattr(current.budget, name, amount)
                manifest_path.write_text(
                    json.dumps({"specification": specification, "status": "running"}, indent=2),
                    encoding="utf-8",
                )
                result = await run_simulation(
                    current, run_dir, resume=existing, controller_factory=controller_factory
                )
                for name in usage:
                    usage[name] += result["usage"][name]
                store = RunStore(run_dir)
                try:
                    metrics = store.metrics()
                    if result["status"] == "completed" and metrics:
                        records.append({"condition": condition, "seed": seed, **metrics[-1]})
                    else:
                        status = result["status"]
                        break
                finally:
                    store.close()
            if status != "completed":
                break
        export_comparison(directory, records, variants)
        result = {
            "runs": len(records),
            "directory": str(directory.resolve()),
            "status": status,
            "unit": "independent simulation run",
            "usage": usage,
            "interval_method": "Student t interval over independent runs or paired run differences",
        }
        manifest_path.write_text(
            json.dumps({"specification": specification, **result}, indent=2), encoding="utf-8"
        )
        return result
