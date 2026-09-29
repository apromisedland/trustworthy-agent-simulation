"""Public data contracts shared by plugins, controllers and replay."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentProfile(Record):
    agent_id: str
    name: str
    role: str
    goal: str
    preferences: dict[str, float] = Field(default_factory=dict)


class AgentState(Record):
    profile: AgentProfile
    cash: int = Field(ge=0)
    inventory: dict[str, int] = Field(default_factory=dict)
    location: str = "square"
    home: str = "homes"
    employer: str | None = None
    labor: int = 0
    needs: int = 0
    consumed: int = 0
    social_activity: int = 0
    trust: dict[str, float] = Field(default_factory=dict)
    memories: list[dict[str, Any]] = Field(default_factory=list)


class Action(Record):
    kind: str
    target: str | None = None
    good: str = "food"
    quantity: int = Field(default=1, ge=1, le=10000, strict=True)
    amount: int = Field(default=0, ge=0, strict=True)
    text: str = Field(default="", max_length=1200)
    evidence: list[str] = Field(default_factory=list, max_length=10)
    source_type: Literal["direct", "hearsay", "inference"] = "inference"


class Decision(Record):
    actions: list[Action] = Field(default_factory=list)
    reflection: str = Field(default="", max_length=1600)
    error: str | None = None


class Observation(Record):
    tick: int
    day: int
    slot: int
    actor: dict[str, Any]
    visible: dict[str, Any]
    memories: list[dict[str, Any]]
    actions: dict[str, str]
    rules: list[str]


class Event(Record):
    event_id: str
    tick: int
    kind: str
    actor: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    visible_to: list[str] = Field(default_factory=list)
    source_type: Literal["direct", "hearsay", "inference"] = "direct"


class Offer(Record):
    offer_id: str
    seller: str
    good: str
    quantity: int = Field(ge=0)
    unit_price: int = Field(gt=0)
    expires: int


class Contract(Record):
    contract_id: str
    seller: str
    buyer: str
    good: str
    quantity: int = Field(gt=0)
    total: int = Field(gt=0)
    deadline: int
    status: Literal["pending", "fulfilled", "expired"] = "pending"


class CommunityEvent(Record):
    activity_id: str
    organizer: str
    title: str
    location: str
    tick: int
    participants: list[str] = Field(default_factory=list)
