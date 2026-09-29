"""Mesa world state, money ledger, visibility and evidence memory."""

from copy import deepcopy

import networkx as nx
from mesa import Agent, Model
from mesa.datacollection import DataCollector
from mesa.space import NetworkGrid

from tass.config import ScenarioConfig
from tass.types import AgentState, CommunityEvent, Contract, Event, Offer


class ActionRejected(Exception):
    """An invalid proposal; the rejection itself is an observable event."""


class TownActor(Agent):
    def __init__(self, model, state: AgentState):
        super().__init__(model)
        self.state = state


def tuple_tree(value):
    return tuple(tuple_tree(item) for item in value) if isinstance(value, list) else value


class World(Model):
    def __init__(self, config: ScenarioConfig):
        super().__init__(rng=config.seed)
        self.config = config
        self.tick = 0
        self.actors: dict[str, TownActor] = {}
        self.locations = nx.Graph()
        default_locations = {
            "homes": (0, 0),
            "square": (1, 1),
            "market": (2, 0),
            "farm": (0, 2),
            "workshop": (2, 2),
            "town_hall": (1, 3),
        }
        if config.locations:
            for location in config.locations:
                self.locations.add_node(location.name, pos=(location.x, location.y))
            for location in config.locations:
                self.locations.add_edges_from(
                    (location.name, neighbor) for neighbor in location.neighbors
                )
        else:
            for name, position in default_locations.items():
                self.locations.add_node(name, pos=position)
            self.locations.add_edges_from(
                ("square", name) for name in default_locations if name != "square"
            )
        self.space = NetworkGrid(self.locations)
        self.social = nx.Graph()
        self.offers: dict[str, Offer] = {}
        self.contracts: dict[str, Contract] = {}
        self.activities: dict[str, CommunityEvent] = {}
        self.jobs: dict[str, dict] = {}
        self.applications: dict[str, list[str]] = {}
        self.treasury = config.resources.treasury
        self.escrow = 0
        self.initial_money = self.treasury
        self.events: list[Event] = []
        self.event_counter = 0
        self.worked: set[str] = set()
        self.produced: set[str] = set()
        self.goods_created: dict[str, int] = {}
        self.goods_consumed: dict[str, int] = {}
        self.initial_goods: dict[str, int] = {}
        self.policy_spending = 0
        self.extra: dict = {}
        self.current_metrics: dict = {}
        self.collector = DataCollector(model_reporters={"money": lambda model: model.money_total()})

    @property
    def day(self):
        return self.tick // self.config.slots_per_day

    @property
    def slot(self):
        return self.tick % self.config.slots_per_day

    def add_actor(self, state: AgentState):
        actor_id = state.profile.agent_id
        override = self.config.agents.get(actor_id)
        if override:
            if override.cash is not None:
                state.cash = override.cash
            for attribute in ("name", "goal", "preferences"):
                value = getattr(override, attribute)
                if value is not None:
                    setattr(state.profile, attribute, value)
        actor = TownActor(self, state)
        self.actors[actor_id] = actor
        self.space.place_agent(actor, state.location)
        self.social.add_node(actor_id)

    def initialize_totals(self):
        self.initial_money = self.money_total()
        self.initial_goods = self.inventory_totals()
        identifiers = list(self.actors)
        if self.config.network.kind == "complete":
            self.social.add_edges_from(
                (left, right)
                for index, left in enumerate(identifiers)
                for right in identifiers[index + 1 :]
            )
        elif self.config.network.kind == "ring":
            for index, actor_id in enumerate(identifiers):
                for offset in (1, 2):
                    neighbor = identifiers[(index + offset) % len(identifiers)]
                    if actor_id != neighbor:
                        self.social.add_edge(actor_id, neighbor)
        else:
            self.social.add_edges_from(
                (left, right)
                for index, left in enumerate(identifiers)
                for right in identifiers[index + 1 :]
                if self.random.random() < self.config.network.probability
            )

    def state(self, actor_id: str) -> AgentState:
        if actor_id not in self.actors:
            raise ActionRejected(f"Unknown actor: {actor_id}")
        return self.actors[actor_id].state

    def emit(
        self,
        kind: str,
        actor: str | None = None,
        payload=None,
        visible_to=None,
        source_type="direct",
    ) -> Event:
        self.event_counter += 1
        event = Event(
            event_id=f"e{self.event_counter:08d}",
            tick=self.tick,
            kind=kind,
            actor=actor,
            payload=payload or {},
            visible_to=visible_to or [],
            source_type=source_type,
        )
        self.events.append(event)
        return event

    def transfer(self, sender: str, recipient: str, amount: int, reason: str):
        if amount < 0:
            raise ActionRejected("Negative transfer")
        balance = self.balance(sender)
        if balance < amount:
            raise ActionRejected("Insufficient funds")
        self.balance(recipient)
        self.set_balance(sender, balance - amount)
        self.set_balance(recipient, self.balance(recipient) + amount)
        self.emit(
            "ledger",
            payload={"debit": sender, "credit": recipient, "amount": amount, "reason": reason},
            visible_to=[
                identifier for identifier in (sender, recipient) if identifier in self.actors
            ],
        )

    def balance(self, account):
        if account in ("treasury", "escrow"):
            return getattr(self, account)
        return self.state(account).cash

    def set_balance(self, account, amount):
        if account in ("treasury", "escrow"):
            setattr(self, account, amount)
        else:
            self.state(account).cash = amount

    def money_total(self):
        return self.treasury + self.escrow + sum(actor.state.cash for actor in self.actors.values())

    def inventory_totals(self):
        totals: dict[str, int] = {}
        for actor in self.actors.values():
            for good, quantity in actor.state.inventory.items():
                totals[good] = totals.get(good, 0) + quantity
        for contract in self.contracts.values():
            if contract.status == "pending":
                totals[contract.good] = totals.get(contract.good, 0) + contract.quantity
        return totals

    def assert_invariants(self):
        if self.money_total() != self.initial_money:
            raise RuntimeError("Money conservation violated")
        if self.escrow != sum(
            contract.total for contract in self.contracts.values() if contract.status == "pending"
        ):
            raise RuntimeError("Escrow does not match pending contracts")
        if any(self.balance(account) < 0 for account in [*self.actors, "treasury", "escrow"]):
            raise RuntimeError("Negative account")
        for actor in self.actors.values():
            if any(quantity < 0 for quantity in actor.state.inventory.values()):
                raise RuntimeError("Negative inventory")
        for good, quantity in self.inventory_totals().items():
            expected = (
                self.initial_goods.get(good, 0)
                + self.goods_created.get(good, 0)
                - self.goods_consumed.get(good, 0)
            )
            if quantity != expected:
                raise RuntimeError(f"Inventory conservation violated for {good}")

    def remember(self):
        for actor_id, actor in self.actors.items():
            visible = [
                event
                for event in self.events
                if "*" in event.visible_to or actor_id in event.visible_to
            ]
            if self.config.memory != "none":
                for event in visible:
                    actor.state.memories.append(event.model_dump())
                actor.state.memories = actor.state.memories[-200:]
            for event in visible:
                if event.kind in ("contract_fulfilled", "contract_expired"):
                    seller = event.payload["seller"]
                    if actor_id == event.payload["buyer"]:
                        previous = actor.state.trust.get(seller, 0.5)
                        change = 0.1 if event.kind == "contract_fulfilled" else -0.15
                        actor.state.trust[seller] = round(max(0.0, min(1.0, previous + change)), 3)

    def local_memories(self, actor_id):
        if self.config.memory == "none":
            return []
        memories = [
            self.event_view(memory)
            for memory in self.state(actor_id).memories[-self.config.memory_limit :]
        ]
        if self.config.memory == "summary":
            for memory in memories:
                memory["payload"].pop("evidence", None)
                memory["payload"].pop("claimed_source_type", None)
            return [
                {"tick": memory["tick"], "kind": memory["kind"], "summary": memory["payload"]}
                for memory in memories
            ]
        return memories

    def event_view(self, event):
        visible = deepcopy(event)
        if visible["kind"] == "message" and not self.config.policies.source_disclosure:
            visible["payload"].pop("evidence", None)
            visible["payload"].pop("claimed_source_type", None)
        return visible

    def local_feedback(self, actor_id):
        return [
            self.event_view(event) for event in self.extra.get("feedback", {}).get(actor_id, [])
        ]

    def snapshot(self):
        return {
            "tick": self.tick,
            "actor_order": list(self.actors),
            "actors": {key: actor.state.model_dump() for key, actor in self.actors.items()},
            "offers": {key: value.model_dump() for key, value in self.offers.items()},
            "contracts": {key: value.model_dump() for key, value in self.contracts.items()},
            "activities": {key: value.model_dump() for key, value in self.activities.items()},
            "jobs": self.jobs,
            "applications": self.applications,
            "treasury": self.treasury,
            "escrow": self.escrow,
            "initial_money": self.initial_money,
            "event_counter": self.event_counter,
            "social_edges": list(self.social.edges),
            "random_state": self.random.getstate(),
            "numpy_state": self.rng.bit_generator.state,
            "initial_goods": self.initial_goods,
            "goods_created": self.goods_created,
            "goods_consumed": self.goods_consumed,
            "policy_spending": self.policy_spending,
            "extra": self.extra,
        }

    @classmethod
    def restore(cls, config: ScenarioConfig, snapshot: dict):
        world = cls(config)
        for actor_id in snapshot["actor_order"]:
            state = snapshot["actors"][actor_id]
            actor = TownActor(world, AgentState.model_validate(state))
            world.actors[actor.state.profile.agent_id] = actor
            world.space.place_agent(actor, actor.state.location)
            world.social.add_node(actor.state.profile.agent_id)
        for key in (
            "tick",
            "jobs",
            "applications",
            "treasury",
            "escrow",
            "initial_money",
            "event_counter",
            "initial_goods",
            "goods_created",
            "goods_consumed",
            "policy_spending",
            "extra",
        ):
            setattr(world, key, deepcopy(snapshot[key]))
        world.offers = {
            key: Offer.model_validate(value) for key, value in snapshot["offers"].items()
        }
        world.contracts = {
            key: Contract.model_validate(value) for key, value in snapshot["contracts"].items()
        }
        world.activities = {
            key: CommunityEvent.model_validate(value)
            for key, value in snapshot["activities"].items()
        }
        world.social.add_edges_from(snapshot["social_edges"])
        world.random.setstate(tuple_tree(snapshot["random_state"]))
        world.rng.bit_generator.state = snapshot["numpy_state"]
        return world
