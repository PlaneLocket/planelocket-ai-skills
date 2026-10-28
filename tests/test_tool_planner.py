"""Tests for model-assisted diagnostic tool planning."""

import json
import unittest

from planelocket_agent.tools.planner import ToolPlanner


class FakeOllamaClient:
    """Return controlled model responses without running Ollama."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def chat(
        self,
        messages,
        response_format=None,
        options=None,
    ):
        self.calls.append(
            {
                "messages": messages,
                "response_format": response_format,
                "options": options,
            }
        )

        return self.response


class TestToolPlanner(unittest.TestCase):
    def make_planner(self, response, max_tools=4):
        client = FakeOllamaClient(response)

        planner = ToolPlanner(
            client=client,
            allowed_tools=(
                "get_memory_usage",
                "get_disk_usage",
            ),
            max_tools=max_tools,
        )

        return planner, client

    def test_valid_single_tool(self):
        planner, client = self.make_planner(json.dumps({"tools": ["get_memory_usage"]}))

        result = planner.plan(
            "How much RAM is Kvasir using?",
            "Inspect system memory.",
        )

        self.assertEqual(
            result.tools,
            ("get_memory_usage",),
        )

        self.assertEqual(len(client.calls), 1)

    def test_valid_multiple_tools(self):
        planner, _ = self.make_planner(
            json.dumps(
                {
                    "tools": [
                        "get_memory_usage",
                        "get_disk_usage",
                    ]
                }
            )
        )

        result = planner.plan(
            "Check memory and disk.",
            "Inspect system health.",
        )

        self.assertEqual(
            result.tools,
            ("get_memory_usage", "get_disk_usage"),
        )

    def test_empty_tool_selection(self):
        planner, _ = self.make_planner(json.dumps({"tools": []}))

        result = planner.plan(
            "Explain what RAM is.",
            "Use tools only when needed.",
        )

        self.assertEqual(result.tools, ())

    def test_invalid_json_rejected(self):
        planner, _ = self.make_planner("not valid JSON")

        with self.assertRaisesRegex(
            ValueError,
            "invalid tool-request JSON",
        ):
            planner.plan("Check memory.", "Inspect memory.")

    def test_unauthorized_tool_rejected(self):
        planner, _ = self.make_planner(json.dumps({"tools": ["execute_shell_command"]}))

        with self.assertRaisesRegex(
            ValueError,
            "Unknown or unauthorized tool",
        ):
            planner.plan("Run a command.", "Inspect system.")

    def test_duplicate_tools_rejected(self):
        planner, _ = self.make_planner(
            json.dumps(
                {
                    "tools": [
                        "get_memory_usage",
                        "get_memory_usage",
                    ]
                }
            )
        )

        with self.assertRaisesRegex(
            ValueError,
            "Duplicate tool request",
        ):
            planner.plan("Check memory.", "Inspect memory.")

    def test_tool_limit_enforced(self):
        planner, _ = self.make_planner(
            json.dumps(
                {
                    "tools": [
                        "get_memory_usage",
                        "get_disk_usage",
                    ]
                }
            ),
            max_tools=1,
        )

        with self.assertRaisesRegex(
            ValueError,
            "exceeds maximum",
        ):
            planner.plan("Check system.", "Inspect system.")

    def test_schema_restricts_tools(self):
        planner, client = self.make_planner(json.dumps({"tools": []}))

        planner.plan("Check system.", "Inspect system.")

        schema = client.calls[0]["response_format"]

        self.assertEqual(
            schema["properties"]["tools"]["items"]["enum"],
            ["get_memory_usage", "get_disk_usage"],
        )

        self.assertFalse(schema["additionalProperties"])

        self.assertEqual(
            client.calls[0]["options"]["temperature"],
            0,
        )


if __name__ == "__main__":
    unittest.main()
