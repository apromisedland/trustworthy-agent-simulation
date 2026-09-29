# Writing a scenario plugin

The runner discovers installed Python entry points. Register your plugin in
your package's `pyproject.toml`:

```toml
[project.entry-points."tass.scenarios"]
my_scenario = "my_package.scenario:MyScenario"
```

The entry point resolves to a no-argument class implementing the structural
`ScenarioPlugin` protocol in `tass.scenarios.base`. Set `scenario: my_scenario`
in YAML. The first-release substrate supports people, graph locations, social
edges, integer resources, memories and JSON-serializable extra state.

| Method | Responsibility |
| --- | --- |
| `build_world(config) -> World` | Construct Mesa actors and call `initialize_totals()` once. |
| `restore_world(config, snapshot) -> World` | Restore a checkpoint for continuation, replay and the dashboard. |
| `begin_tick(world)` | Reset tick-local data and apply exogenous events. |
| `observe(world, actor_id) -> Observation` | Construct an independent, authorized local observation. |
| `tools(world, actor_id) -> dict[str, str]` | Describe the allowed action kinds and their arguments. |
| `resolve(world, decisions)` | Validate and execute proposals with deterministic ordering. |
| `end_tick(world)` | Apply end-period effects, deliver observations and check invariants. |
| `metrics(world) -> dict` | Return consistent named scalar measurements for every tick. |
| `baseline(world, actor_id, observation) -> list[Action]` | Supply an explicitly labeled offline policy. |

`Action` supports `kind`, `target`, `good`, `quantity`, `amount`, `text`, `evidence`
and `source_type`. New kinds reuse this envelope. Extensions needing different
argument types should introduce a versioned contract instead of embedding
executable code in YAML. AgentScope exposes one native `submit_actions` tool;
scenario action descriptions are included in each local observation.

Use `World.transfer` for money and `World.emit` for events. `visible_to=["*"]`
means public; explicit IDs mean private; an empty list means audit-only. Record
inventory sources and sinks so invariants can be checked. Reject invalid domain
operations with `ActionRejected` before making changes.

Put scenario-specific serializable state in `world.extra`, which is included in
the standard snapshot. Core actors, social edges, offers, contracts, activities,
accounts and RNG states are also checkpointed. Implement `restore_world` using
`World.restore` for the standard restoration path, as `TownScenario` does.
Custom subclasses must provide compatible JSON snapshots and restore all their
additional state; non-serializable state is outside this v1 plugin contract.

`PublicGoodsScenario` is a complete example: it registers a `contribute` action,
redistributes contributions with finite treasury matching, implements independent
observations and metrics, and reuses communication/ledger behavior from the town.
Only `population.residents` is used in that scenario; shop/producer counts are
ignored. Its configurable `scenario_options.multiplier` defaults to 1.5.

Town configuration supports population sizes, resource endowments, `agents`
overrides by ID (`name`, `goal`, `cash`, `preferences`), social network topology,
locations and graph edges, role models and policies. Custom town maps must retain
the six named functional locations (`homes`, `square`, `market`, `farm`,
`workshop`, `town_hall`); new scenarios can define their own map conventions.

Add invariant, visibility, serialization, replay and baseline smoke tests for
every new plugin. Compare a resumed run against an uninterrupted run before
using a plugin for experiments.
