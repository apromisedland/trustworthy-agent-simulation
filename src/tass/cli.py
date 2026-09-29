"""Command-line interface shared with dashboard workers."""

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from tass.config import ScenarioConfig, load_config
from tass.experiments import run_batch
from tass.runner import replay as replay_run
from tass.runner import request_pause, run_simulation
from tass.scenarios import load_scenario
from tass.storage import RunStore

app = typer.Typer(
    no_args_is_help=True, help="Auditable LLM town simulation with AgentScope and Mesa."
)


def report(value):
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2))


@app.command("validate")
def validate(config: Annotated[Path, typer.Option(exists=True)]):
    """Check configuration and world invariants without calling a provider."""
    settings = load_config(config)
    world = load_scenario(settings.scenario).build_world(settings)
    world.assert_invariants()
    report(
        {
            "valid": True,
            "scenario": settings.scenario,
            "actors": len(world.actors),
            "ticks": settings.total_ticks,
            "mode": settings.mode,
            "provider_called": False,
        }
    )


@app.command("run")
def run(
    config: Annotated[Path | None, typer.Option(exists=True)] = None,
    output: Annotated[Path | None, typer.Option()] = None,
    mode: Annotated[str | None, typer.Option()] = None,
    resume: Annotated[Path | None, typer.Option(exists=True)] = None,
    max_ticks: Annotated[int | None, typer.Option(min=1)] = None,
):
    """Run a scenario, or resume a saved run using its frozen configuration."""
    load_dotenv()
    if resume:
        if config or output or mode:
            raise typer.BadParameter(
                "--resume uses saved configuration; do not combine with --config, --output or --mode"
            )
        store = RunStore(resume)
        try:
            settings = ScenarioConfig.model_validate(store.get("config"))
        finally:
            store.close()
        directory = resume
    else:
        if config is None or output is None:
            raise typer.BadParameter("Provide --config and --output")
        settings = load_config(config)
        if mode:
            settings = ScenarioConfig.model_validate({**settings.model_dump(), "mode": mode})
        directory = output
    try:
        result = asyncio.run(
            run_simulation(settings, directory, resume=resume is not None, max_ticks=max_ticks)
        )
    except (ValueError, RuntimeError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    report(result)
    if result["status"] == "budget_exhausted":
        raise typer.Exit(2)


@app.command()
def pause(directory: Annotated[Path, typer.Argument(exists=True)]):
    """Request a pause at the next committed tick boundary."""
    request_pause(directory)
    report({"pause_requested": True})


@app.command()
def batch(
    config: Annotated[Path, typer.Option(exists=True)],
    output: Annotated[Path, typer.Option()],
    suite: str = "policy",
    seeds: str = "11,22,33",
):
    """Run a policy or ablation matrix with one shared API budget."""
    load_dotenv()
    settings = load_config(config)
    seed_values = tuple(int(value.strip()) for value in seeds.split(","))
    if not seed_values or len(set(seed_values)) != len(seed_values) or min(seed_values) < 0:
        raise typer.BadParameter("Provide distinct nonnegative seeds")
    report(asyncio.run(run_batch(settings, output, suite, seed_values)))


@app.command("replay")
def replay(directory: Annotated[Path, typer.Argument(exists=True)], tick: int | None = None):
    """Read and verify a checkpoint; never contacts a model."""
    result = replay_run(directory, tick)
    report(
        {
            "status": result["status"],
            "next_tick": result["snapshot"]["tick"],
            "actors": len(result["snapshot"]["actors"]),
            "usage": result["usage"],
        }
    )


@app.command()
def dashboard(runs_dir: Path = Path("runs"), port: int = 8501):
    """Open the local research dashboard."""
    script = Path(__file__).with_name("dashboard.py")
    raise typer.Exit(
        subprocess.call(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(script),
                "--server.address",
                "127.0.0.1",
                "--server.port",
                str(port),
                "--",
                "--runs-dir",
                str(runs_dir.resolve()),
            ]
        )
    )


if __name__ == "__main__":
    app()
