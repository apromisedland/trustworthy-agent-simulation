"""Validated, portable experiment configuration."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelSettings(Settings):
    base_url: str = "${TASS_BASE_URL}"
    model: str = "${TASS_MODEL}"
    api_key_env: str = "TASS_API_KEY"
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_output_tokens: int = Field(default=600, ge=64, le=8192)
    timeout_seconds: float = Field(default=45, gt=0, le=300)
    retries: int = Field(default=2, ge=0, le=5)


class BudgetSettings(Settings):
    requests: int = Field(default=500, ge=1)
    input_tokens: int = Field(default=1_000_000, ge=1)
    output_tokens: int = Field(default=100_000, ge=1)
    concurrency: int = Field(default=3, ge=1, le=32)
    input_price_per_million: float | None = Field(default=None, ge=0)
    output_price_per_million: float | None = Field(default=None, ge=0)


class Population(Settings):
    residents: int = Field(default=18, ge=2, le=1000)
    shops: int = Field(default=4, ge=1, le=100)
    producers: int = Field(default=2, ge=1, le=100)


class Resources(Settings):
    resident_cash: int = Field(default=3000, ge=0)
    firm_cash: int = Field(default=25000, ge=0)
    treasury: int = Field(default=100000, ge=0)
    wage: int = Field(default=300, gt=0)
    food_price: int = Field(default=100, gt=0)
    goods_price: int = Field(default=200, gt=0)
    initial_food: int = Field(default=12, ge=1)
    initial_goods: int = Field(default=8, ge=1)
    production_per_labor: int = Field(default=3, ge=1)


class Location(Settings):
    name: str
    x: float
    y: float
    neighbors: list[str] = Field(default_factory=list)


class NetworkSettings(Settings):
    kind: Literal["ring", "complete", "random"] = "ring"
    probability: float = Field(default=0.2, ge=0, le=1)


class PolicySettings(Settings):
    subsidy: int = Field(default=0, ge=0)
    subsidy_day: int = Field(default=2, ge=0)
    source_disclosure: bool = False
    shock_day: int | None = Field(default=None, ge=0)
    shock_production_multiplier: float = Field(default=0.5, ge=0, le=1)
    shock_duration_days: int = Field(default=2, ge=1)


class AgentOverride(Settings):
    name: str | None = None
    goal: str | None = None
    cash: int | None = Field(default=None, ge=0)
    preferences: dict[str, float] | None = None


class ScenarioConfig(Settings):
    schema_version: Literal[1] = 1
    name: str = "small-town"
    scenario: str = "small_town"
    seed: int = Field(default=42, ge=0)
    days: int = Field(default=7, ge=1, le=365)
    slots_per_day: int = Field(default=4, ge=1, le=24)
    mode: Literal["baseline", "llm"] = "baseline"
    population: Population = Field(default_factory=Population)
    resources: Resources = Field(default_factory=Resources)
    network: NetworkSettings = Field(default_factory=NetworkSettings)
    policies: PolicySettings = Field(default_factory=PolicySettings)
    model: ModelSettings = Field(default_factory=ModelSettings)
    role_models: dict[str, ModelSettings] = Field(default_factory=dict)
    budget: BudgetSettings = Field(default_factory=BudgetSettings)
    memory: Literal["none", "summary", "provenance"] = "provenance"
    communication: bool = True
    memory_limit: int = Field(default=12, ge=1, le=100)
    max_actions_per_tick: int = Field(default=6, ge=1, le=12)
    max_messages_per_tick: int = Field(default=2, ge=0, le=8)
    locations: list[Location] = Field(default_factory=list)
    agents: dict[str, AgentOverride] = Field(default_factory=dict)
    scenario_options: dict = Field(default_factory=dict)

    @property
    def total_ticks(self) -> int:
        return self.days * self.slots_per_day

    @model_validator(mode="after")
    def validate_locations(self):
        names = [location.name for location in self.locations]
        if len(names) != len(set(names)):
            raise ValueError("Location names must be unique")
        if any(
            neighbor not in names for location in self.locations for neighbor in location.neighbors
        ):
            raise ValueError("Location neighbors must refer to declared locations")
        return self


def load_config(path: str | Path) -> ScenarioConfig:
    with Path(path).open(encoding="utf-8") as stream:
        return ScenarioConfig.model_validate(yaml.safe_load(stream))
