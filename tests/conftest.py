import json

import httpx2 as httpx
import pytest

from tass.config import ScenarioConfig
from tass.llm import LLMController
from tass.scenarios.town import TownScenario


@pytest.fixture
def config():
    return ScenarioConfig.model_validate(
        {"days": 3, "population": {"residents": 5, "shops": 2, "producers": 1}}
    )


@pytest.fixture
def town(config):
    scenario = TownScenario()
    world = scenario.build_world(config)
    scenario.begin_tick(world)
    return scenario, world


class ControlledProvider:
    def __init__(self):
        self.observations = []
        self.requests = []

    def respond(self, request):
        body = json.loads(request.content)
        self.requests.append(body)
        messages = body["messages"]
        if any(message["role"] == "tool" for message in messages):
            message = {
                "role": "assistant",
                "content": "Proposals queued; waiting for environment feedback.",
            }
            finish_reason = "stop"
        else:
            user_message = next(message for message in messages if message["role"] == "user")
            content = user_message["content"]
            if isinstance(content, list):
                content = "".join(block.get("text", "") for block in content)
            observation = json.loads(content)
            self.observations.append(observation)
            actor_id = observation["actor"]["profile"]["agent_id"]
            actions = [{"kind": "wait"}]
            if actor_id == "resident_00":
                actions = [
                    {"kind": "consume", "good": "food"},
                    {"kind": "message", "target": "resident_01", "text": "明天我们一起讨论购物。"},
                ]
            elif actor_id == "resident_01" and observation["tick"] > 0:
                if any(memory["kind"] == "message" for memory in observation["memories"]):
                    actions = [{"kind": "consume", "good": "food"}]
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"call_{actor_id}_{observation['tick']}",
                        "type": "function",
                        "function": {
                            "name": "submit_actions",
                            "arguments": json.dumps(
                                {"actions": actions, "reflection": "根据局部观察决定本时段行动。"}
                            ),
                        },
                    }
                ],
            }
            finish_reason = "tool_calls"
        return httpx.Response(
            200,
            json={
                "id": "fixture-response",
                "object": "chat.completion",
                "created": 0,
                "model": "controlled-fixture",
                "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
                "usage": {"prompt_tokens": 300, "completion_tokens": 80, "total_tokens": 380},
            },
        )

    def controller(self, config, store):
        return LLMController(config, store, lambda: httpx.MockTransport(self.respond))


@pytest.fixture
def llm_config(config, monkeypatch):
    monkeypatch.setenv("TASS_API_KEY", "fixture-only-not-a-real-key")
    config.mode = "llm"
    config.model.base_url = "https://fixture.invalid/v1"
    config.model.model = "controlled-fixture"
    config.model.retries = 0
    config.budget.concurrency = 1
    return config
