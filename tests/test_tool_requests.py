"""Tests for model-proposed diagnostic tool requests."""

import unittest

from planelocket_agent.tools.requests import (
    ToolRequest,
    validate_tool_request,
)


class FakeDispatcher:
    """Expose approved tool names without executing anything."""

    def available_tools(self):
        return ("get_memory_usage", "get_disk_usage")


class TestToolRequests(unittest.TestCase):
    def setUp(self):
        self.dispatcher = FakeDispatcher()

    def validate(self, payload, max_tools=4):
        return validate_tool_request(
            payload,
            self.dispatcher.available_tools(),
            max_tools=max_tools,
        )

    def test_valid_multiple_tools(self):
        result = self.validate({"tools": ["get_memory_usage", "get_disk_usage"]})

        self.assertIsInstance(result, ToolRequest)
        self.assertEqual(
            result.tools,
            ("get_memory_usage", "get_disk_usage"),
        )

    def test_empty_tool_list(self):
        result = self.validate({"tools": []})

        self.assertEqual(result.tools, ())

    def test_unauthorized_tool(self):
        with self.assertRaisesRegex(ValueError, "Unknown or unauthorized tool"):
            self.validate({"tools": ["execute_shell_command"]})

    def test_duplicate_tool(self):
        with self.assertRaisesRegex(ValueError, "Duplicate tool request"):
            self.validate({"tools": ["get_memory_usage", "get_memory_usage"]})

    def test_unexpected_field(self):
        with self.assertRaisesRegex(ValueError, "only the 'tools' field"):
            self.validate(
                {
                    "tools": ["get_memory_usage"],
                    "command": "whoami",
                }
            )

    def test_non_object_payload(self):
        with self.assertRaisesRegex(ValueError, "must be a JSON object"):
            self.validate(["get_memory_usage"])

    def test_tools_must_be_list(self):
        with self.assertRaisesRegex(ValueError, "must be a list"):
            self.validate({"tools": "get_memory_usage"})

    def test_non_string_tool_name(self):
        with self.assertRaisesRegex(ValueError, "Tool names must be strings"):
            self.validate({"tools": [123]})

    def test_tool_limit(self):
        with self.assertRaisesRegex(ValueError, "exceeds maximum"):
            self.validate(
                {"tools": ["get_memory_usage", "get_disk_usage"]},
                max_tools=1,
            )

    def test_invalid_max_tools(self):
        with self.assertRaisesRegex(ValueError, "max_tools must be positive"):
            self.validate({"tools": []}, max_tools=0)


if __name__ == "__main__":
    unittest.main()
