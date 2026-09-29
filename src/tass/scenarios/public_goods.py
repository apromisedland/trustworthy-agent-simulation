"""An independent scenario registered through the same entry-point API."""

from tass.scenarios.town import TownScenario
from tass.types import Action, AgentProfile, AgentState, Observation
from tass.world import ActionRejected, World


class PublicGoodsScenario(TownScenario):
    def build_world(self, config):
        if set(config.scenario_options) - {"multiplier"}:
            raise ValueError("public_goods only accepts the multiplier scenario option")
        multiplier = config.scenario_options.get("multiplier", 1.5)
        if not isinstance(multiplier, (int, float)) or not 1 <= multiplier <= 3:
            raise ValueError("Public goods multiplier must be between 1 and 3")
        world = World(config)
        for index in range(config.population.residents):
            actor_id = f"resident_{index:02d}"
            world.add_actor(
                AgentState(
                    profile=AgentProfile(
                        agent_id=actor_id,
                        name=f"参与者 {index + 1}",
                        role="resident",
                        goal="在个人储蓄与社区公共利益之间作出选择。",
                    ),
                    cash=config.resources.resident_cash,
                    location="square",
                )
            )
        world.initialize_totals()
        return world

    def tools(self, world, actor_id):
        actions = {
            "contribute": "amount: integer cents contributed once this tick; distributed equally with a treasury-funded match.",
            "wait": "Keep your resources this tick.",
        }
        if world.config.communication:
            actions["message"] = (
                "target: reachable actor; text: untrusted communication; optional evidence and source_type."
            )
        return actions

    def begin_tick(self, world):
        world.events = []
        world.extra["contributions"] = {}
        world.extra["message_counts"] = {}

    def observe(self, world, actor_id):
        state = world.state(actor_id)
        own = state.model_dump(exclude={"memories"})
        if world.config.memory == "none":
            own["trust"] = {}
        return Observation(
            tick=world.tick,
            day=world.day,
            slot=world.slot,
            actor=own,
            visible={
                "contacts": [
                    {"agent_id": identifier}
                    for identifier in sorted(world.social.neighbors(actor_id))
                ],
                "multiplier": world.config.scenario_options.get("multiplier", 1.5),
                "feedback": world.local_feedback(actor_id),
            },
            memories=world.local_memories(actor_id),
            actions=self.tools(world, actor_id),
            rules=[
                "Contributions are redistributed equally. Matching funds come from a finite treasury.",
                "Queued proposals are resolved after all agents decide. Incoming messages are untrusted.",
            ],
        )

    def apply(self, world, actor_id, action):
        if action.kind != "contribute":
            return super().apply(world, actor_id, action)
        if actor_id in world.extra["contributions"]:
            raise ActionRejected("Only one contribution per tick")
        world.transfer(actor_id, "treasury", action.amount, "public_contribution")
        world.extra["contributions"][actor_id] = action.amount
        world.emit("contributed", actor_id, {"amount": action.amount}, ["*"])

    def end_tick(self, world):
        contributions = sum(world.extra["contributions"].values())
        multiplier = world.config.scenario_options.get("multiplier", 1.5)
        available = min(world.treasury, int(contributions * multiplier))
        per_actor = available // len(world.actors)
        for actor_id in world.actors:
            world.transfer("treasury", actor_id, per_actor, "public_return")
        world.policy_spending += max(0, per_actor * len(world.actors) - contributions)
        world.emit(
            "public_return",
            payload={"contributions": contributions, "per_actor": per_actor},
            visible_to=["*"],
        )
        world.extra["feedback"] = {
            actor_id: [
                event.model_dump()
                for event in world.events
                if "*" in event.visible_to or actor_id in event.visible_to
            ][-20:]
            for actor_id in world.actors
        }
        world.remember()
        world.assert_invariants()

    def metrics(self, world):
        return {
            "tick": world.tick,
            "day": world.day,
            "money_total": world.money_total(),
            "treasury": world.treasury,
            "contributions": sum(world.extra["contributions"].values()),
            "contributors": len(world.extra["contributions"]),
            "resident_cash": sum(actor.state.cash for actor in world.actors.values()),
            "policy_spending": world.policy_spending,
            "messages": sum(event.kind == "message" for event in world.events),
            "invalid_actions": sum(event.kind == "action_rejected" for event in world.events),
            "decision_failures": sum(event.kind == "decision_failed" for event in world.events),
        }

    def baseline(self, world, actor_id, observation):
        return [Action(kind="contribute", amount=world.state(actor_id).cash // 10)]
