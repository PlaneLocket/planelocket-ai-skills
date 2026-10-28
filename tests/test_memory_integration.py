"""Integration tests for investigation memory persistence."""

import json
import tempfile
import unittest
from pathlib import Path

from planelocket_agent.memory.identifiers import new_investigation_id
from planelocket_agent.memory.models import MemoryKind
from planelocket_agent.memory.recorder import MemoryRecorder
from planelocket_agent.memory.storage import MemoryStorage
from planelocket_agent.reasoning import ReasoningAgent


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)

    def chat(self, messages, response_format=None, options=None):
        return next(self.responses)


class FakeDispatcher:
    def available_tools(self):
        return ("get_memory_usage",)

    def tool_descriptions(self):
        return {
            "get_memory_usage": {
                "description": "Retrieve memory usage.",
                "arguments": {},
            }
        }

    def execute(self, tool_name, **arguments):
        return {
            "tool": tool_name,
            "result": {"available_bytes": 8589934592},
        }


class TestMemoryIntegration(unittest.TestCase):
    def test_observation_survives_reasoning_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = MemoryStorage(Path(directory) / "memory.sqlite3")
            storage.initialize()

            recorder = MemoryRecorder(storage)
            investigation_id = new_investigation_id()

            client = FakeClient(
                [
                    json.dumps(
                        {
                            "action": "tool",
                            "tool": "get_memory_usage",
                            "answer": None,
                            "arguments": {},
                        }
                    ),
                    "invalid JSON",
                ]
            )

            agent = ReasoningAgent(
                client=client,
                dispatcher=FakeDispatcher(),
                on_observation=lambda observation: recorder.record_observation(
                    observation,
                    investigation_id,
                ),
            )

            with self.assertRaisesRegex(
                ValueError,
                "invalid decision JSON",
            ):
                agent.run(
                    "Investigate memory usage.",
                    "Use read-only diagnostics.",
                )

            records = storage.get_by_investigation(investigation_id)

            self.assertEqual(len(records), 1)
            self.assertEqual(
                records[0].kind,
                MemoryKind.OBSERVATION,
            )
            self.assertEqual(
                json.loads(records[0].content),
                {
                    "tool": "get_memory_usage",
                    "result": {
                        "available_bytes": 8589934592,
                    },
                },
            )


if __name__ == "__main__":
    unittest.main()
