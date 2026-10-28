"""Unit tests for the PlaneLocket agent orchestrator."""

import json
import tempfile
import unittest
from pathlib import Path

from planelocket_agent.agent import PlaneLocketAgent
from planelocket_agent.memory.models import MemoryKind
from planelocket_agent.memory.recorder import MemoryRecorder
from planelocket_agent.memory.storage import MemoryStorage
from planelocket_agent.tools.definitions import ToolDefinition
from planelocket_agent.tools.dispatcher import ToolDispatcher


class FakeOllamaClient:
    """Simulate selection and planning responses."""

    def __init__(self, selection):
        self.selection = selection
        self.calls = []

    def chat(self, messages, response_format=None, options=None):
        self.calls.append(
            {
                "messages": messages,
                "response_format": response_format,
                "options": options,
            }
        )

        if response_format is not None:
            return self.selection

        return "Diagnostic plan generated."


class TestPlaneLocketAgent(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

        self.skills_dir = Path(self.temporary.name)
        skill_dir = self.skills_dir / "linux-health-check"
        skill_dir.mkdir()

        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: linux-health-check\n"
            "description: Inspect Linux server health.\n"
            "---\n"
            "# Health Check\n"
            "Inspect CPU, memory, and disk usage.\n"
            "Do not modify the system.\n",
            encoding="utf-8",
        )

    def test_generates_plan_with_skill_instructions(self):
        client = FakeOllamaClient('{"skill": "linux-health-check"}')

        agent = PlaneLocketAgent(self.skills_dir, client)

        result = agent.plan("Check Kvasir")

        self.assertEqual(
            result,
            "Diagnostic plan generated.",
        )

        self.assertEqual(len(client.calls), 2)

        planning_messages = client.calls[1]["messages"]
        planning_prompt = planning_messages[1]["content"]

        self.assertIn(
            "Inspect CPU, memory, and disk usage.",
            planning_prompt,
        )

        self.assertIn(
            "Do not modify the system.",
            planning_prompt,
        )

    def test_no_matching_skill(self):
        client = FakeOllamaClient('{"skill": null}')

        agent = PlaneLocketAgent(self.skills_dir, client)

        result = agent.plan("Bake sourdough bread")

        self.assertEqual(
            result,
            "No matching Skill is available for this request.",
        )

        self.assertEqual(len(client.calls), 1)

    def test_investigate_preserves_custom_tools(self):
        class FakeDiagnostics:
            def get_memory_usage(self):
                return {}

            def get_disk_usage(self):
                return {}

            def get_resource_pressure(self):
                return {}

        class InvestigationClient:
            def __init__(self):
                self.calls = []
                self.responses = iter(
                    [
                        json.dumps({"skill": "linux-health-check"}),
                        json.dumps(
                            {
                                "action": "tool",
                                "tool": "custom_tool",
                                "answer": None,
                                "arguments": {},
                            }
                        ),
                        json.dumps(
                            {
                                "action": "finish",
                                "tool": None,
                                "answer": "Custom tool executed successfully.",
                                "arguments": {},
                            }
                        ),
                    ]
                )

            def chat(self, messages, response_format=None, options=None):
                self.calls.append(
                    {
                        "messages": list(messages),
                        "response_format": response_format,
                        "options": options,
                    }
                )
                return next(self.responses)

        client = InvestigationClient()
        dispatcher = ToolDispatcher(FakeDiagnostics())

        calls = []

        def custom_handler():
            calls.append("executed")
            return {"status": "available"}

        dispatcher._definitions["custom_tool"] = ToolDefinition(
            name="custom_tool",
            description="Return custom diagnostic information.",
            handler=custom_handler,
        )

        agent = PlaneLocketAgent(self.skills_dir, client)

        result = agent.investigate(
            "Check Kvasir using the custom diagnostic tool.",
            dispatcher,
        )

        self.assertTrue(result.completed)
        self.assertIsNone(result.investigation_id)
        self.assertEqual(result.tool_calls, 1)
        self.assertEqual(calls, ["executed"])

        self.assertEqual(
            result.observations[0],
            {
                "tool": "custom_tool",
                "result": {"status": "available"},
            },
        )

        self.assertIn("custom_tool", dispatcher.available_tools())
        self.assertIn("read_reference", dispatcher.available_tools())

        reasoning_prompt = client.calls[1]["messages"][1]["content"]

        self.assertIn("custom_tool", reasoning_prompt)
        self.assertIn(
            "Return custom diagnostic information.",
            reasoning_prompt,
        )

    def test_investigate_persists_observations(self):
        class FakeDiagnostics:
            def get_memory_usage(self):
                return {"available_bytes": 8589934592}

            def get_disk_usage(self):
                return {}

            def get_resource_pressure(self):
                return {}

        class InvestigationClient:
            def __init__(self):
                self.responses = iter(
                    [
                        json.dumps({"skill": "linux-health-check"}),
                        json.dumps(
                            {
                                "action": "tool",
                                "tool": "get_memory_usage",
                                "answer": None,
                                "arguments": {},
                            }
                        ),
                        json.dumps(
                            {
                                "action": "finish",
                                "tool": None,
                                "answer": "Memory inspection complete.",
                                "arguments": {},
                            }
                        ),
                    ]
                )

            def chat(self, messages, response_format=None, options=None):
                return next(self.responses)

        storage = MemoryStorage(self.skills_dir / "memory.sqlite3")
        storage.initialize()

        recorder = MemoryRecorder(storage)

        agent = PlaneLocketAgent(
            self.skills_dir,
            InvestigationClient(),
            memory_recorder=recorder,
        )

        result = agent.investigate(
            "Check Kvasir memory.",
            ToolDispatcher(FakeDiagnostics()),
        )

        self.assertTrue(result.completed)
        self.assertEqual(result.tool_calls, 1)

        # Retrieve the persisted record without knowing its generated ID.
        import sqlite3
        from contextlib import closing

        with closing(sqlite3.connect(storage.database_path)) as connection:
            row = connection.execute("SELECT id FROM memory_records").fetchone()

        self.assertIsNotNone(row)

        record = storage.get(row[0])

        self.assertIsNotNone(result.investigation_id)

        self.assertEqual(
            record.investigation_id,
            result.investigation_id,
        )

        self.assertEqual(
            storage.get_by_investigation(result.investigation_id),
            [record],
        )
        self.assertEqual(record.kind, MemoryKind.OBSERVATION)
        self.assertEqual(record.source, "get_memory_usage")
        self.assertIsNotNone(record.investigation_id)

        self.assertEqual(
            json.loads(record.content),
            result.observations[0],
        )


if __name__ == "__main__":
    unittest.main()
