"""Shared execution service for the CLI and dashboard."""

import asyncio
import importlib.metadata
import os
from pathlib import Path

from tass.config import ScenarioConfig
from tass.llm import BudgetExceeded, LLMController
from tass.scenarios import load_scenario
from tass.storage import RunStore
from tass.types import Decision


class RunLease:
    def __init__(self, directory):
        self.path = Path(directory) / ".runner.lock"
        self.handle = None

    def __enter__(self):
        self.handle = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.handle.close()
            raise RuntimeError("This run already has an active worker") from error
        return self

    def __exit__(self, *arguments):
        self.handle.close()


async def run_simulation(
    config: ScenarioConfig,
    directory: str | Path,
    *,
    resume=False,
    max_ticks: int | None = None,
    controller_factory=None,
) -> dict:
    store = RunStore(directory)
    started = False
    try:
        with RunLease(directory):
            existing = store.get("config")
            if existing and not resume:
                raise ValueError("Run already exists; choose another output directory or resume it")
            if resume and not existing:
                raise ValueError("Cannot resume a run without a saved configuration")
            if existing and existing != config.model_dump():
                raise ValueError("Resume requires the exact saved configuration, including budgets")
            scenario = load_scenario(config.scenario)
            saved = store.snapshot()
            world = scenario.restore_world(config, saved) if saved else scenario.build_world(config)
            if not existing:
                store.set("config", config.model_dump())
                store.set(
                    "versions",
                    {
                        package: importlib.metadata.version(package)
                        for package in (
                            "trustworthy-agent-simulation",
                            "agentscope",
                            "mesa",
                            "pydantic",
                        )
                    },
                )
                store.commit_tick(-1, world.snapshot(), {}, [])
            store.set("pause_requested", False)
            store.set("status", "running")
            started = True
            store.set(
                "validation",
                "offline-baseline"
                if config.mode == "baseline"
                else ("controlled-provider" if controller_factory else "live-provider"),
            )
            controller = None
            if config.mode == "llm":
                controller = (controller_factory or LLMController)(config, store)
            start_tick = world.tick
            semaphore = asyncio.Semaphore(config.budget.concurrency)
            stopped = asyncio.Event()

            async def decide(actor_id, observation):
                previous = store.decision(world.tick, actor_id)
                if previous is not None:
                    return previous
                async with semaphore:
                    if stopped.is_set():
                        raise BudgetExceeded("Budget exhausted by another participant")
                    if controller:
                        try:
                            decision = await controller.decide(actor_id, observation)
                        except BudgetExceeded:
                            stopped.set()
                            raise
                    else:
                        decision = Decision(actions=scenario.baseline(world, actor_id, observation))
                    store.save_decision(world.tick, actor_id, decision)
                    return decision

            try:
                while world.tick < config.total_ticks:
                    if store.get("pause_requested") or (
                        max_ticks is not None and world.tick - start_tick >= max_ticks
                    ):
                        store.set("status", "paused")
                        break
                    scenario.begin_tick(world)
                    observations = {
                        actor_id: scenario.observe(world, actor_id) for actor_id in world.actors
                    }
                    store.save_observations(world.tick, observations)
                    results = await asyncio.gather(
                        *(
                            decide(actor_id, observation)
                            for actor_id, observation in observations.items()
                        ),
                        return_exceptions=True,
                    )
                    if any(isinstance(result, BudgetExceeded) for result in results):
                        store.set("status", "budget_exhausted")
                        break
                    for result in results:
                        if isinstance(result, BaseException):
                            raise result
                    decisions = dict(zip(observations, results, strict=True))
                    scenario.resolve(world, decisions)
                    scenario.end_tick(world)
                    metrics = scenario.metrics(world)
                    metrics.update(store.usage())
                    metrics["estimated_cost"] = estimated_cost(store.usage(), config)
                    world.current_metrics = metrics
                    world.steps = world.tick
                    for name in metrics:
                        if name not in world.collector.model_reporters:
                            world.collector._new_model_reporter(
                                name, lambda model, metric=name: model.current_metrics[metric]
                            )
                    world.collector.collect(world)
                    completed_tick = world.tick
                    world.tick += 1
                    store.commit_tick(completed_tick, world.snapshot(), metrics, world.events)
                else:
                    store.set("status", "completed")
            except BaseException as error:
                store.set(
                    "status",
                    "interrupted"
                    if isinstance(error, (KeyboardInterrupt, asyncio.CancelledError))
                    else "failed",
                )
                store.set("last_error", type(error).__name__)
                raise
            finally:
                store.export()
            return {
                "directory": str(Path(directory).resolve()),
                "status": store.get("status"),
                "ticks": (store.snapshot() or {}).get("tick", 0),
                "usage": store.usage(),
            }
    except Exception:
        if started and store.get("status") == "running":
            store.set("status", "failed")
            store.export()
        raise
    finally:
        store.close()


def estimated_cost(usage, config):
    budget = config.budget
    if budget.input_price_per_million is None or budget.output_price_per_million is None:
        return None
    return round(
        (
            usage["input_tokens"] * budget.input_price_per_million
            + usage["output_tokens"] * budget.output_price_per_million
        )
        / 1_000_000,
        6,
    )


def request_pause(directory):
    store = RunStore(directory)
    try:
        store.set("pause_requested", True)
    finally:
        store.close()


def replay(directory, tick=None):
    if not (Path(directory) / "run.sqlite").is_file():
        raise ValueError("Run database does not exist")
    store = RunStore(directory)
    try:
        snapshot = store.snapshot(tick)
        if snapshot is None:
            raise ValueError("No committed checkpoint at this tick")
        config = ScenarioConfig.model_validate(store.get("config"))
        world = load_scenario(config.scenario).restore_world(config, snapshot)
        world.assert_invariants()
        return {
            "status": store.get("status"),
            "snapshot": snapshot,
            "metrics": store.metrics(),
            "usage": store.usage(),
        }
    finally:
        store.close()
