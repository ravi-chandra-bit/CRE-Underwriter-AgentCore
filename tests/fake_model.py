"""A scripted Strands model: replays a fixed list of turns (tool calls or text)."""

from __future__ import annotations

import json
from typing import Any

from strands.models import Model


class ScriptedModel(Model):
    def __init__(self, turns: list[dict[str, Any]]):
        self.turns = list(turns)
        self.calls = 0

    def update_config(self, **kwargs: Any) -> None:
        pass

    def get_config(self) -> dict[str, Any]:
        return {}

    async def structured_output(self, *args: Any, **kwargs: Any):  # pragma: no cover
        raise NotImplementedError
        yield

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        turn = self.turns[min(self.calls, len(self.turns) - 1)]
        self.calls += 1
        yield {"messageStart": {"role": "assistant"}}
        if "tool" in turn:
            yield {
                "contentBlockStart": {
                    "start": {"toolUse": {"toolUseId": f"t{self.calls}", "name": turn["tool"]}}
                }
            }
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(turn.get("input", {}))}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockDelta": {"delta": {"text": turn["text"]}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
