"""Tests for agent decision validation."""

import unittest

from planelocket_agent.tools.decisions import validate_agent_decision


class TestAgentDecisions(unittest.TestCase):
    def test_legacy_tool_decision_has_empty_arguments(self):
        decision = validate_agent_decision(
            {
                "action": "tool",
                "tool": "get_resource_pressure",
                "answer": None,
            },
            ("get_resource_pressure",),
        )

        self.assertEqual(decision.arguments, {})

    def test_tool_decision_accepts_arguments(self):
        decision = validate_agent_decision(
            {
                "action": "tool",
                "tool": "read_reference",
                "answer": None,
                "arguments": {
                    "filename": "pressure-stall-information.md",
                },
            },
            ("read_reference",),
        )

        self.assertEqual(
            decision.arguments,
            {"filename": "pressure-stall-information.md"},
        )

    def test_reject_non_object_arguments(self):
        with self.assertRaises(ValueError):
            validate_agent_decision(
                {
                    "action": "tool",
                    "tool": "read_reference",
                    "answer": None,
                    "arguments": ["pressure-stall-information.md"],
                },
                ("read_reference",),
            )

    def test_reject_finish_with_arguments(self):
        with self.assertRaises(ValueError):
            validate_agent_decision(
                {
                    "action": "finish",
                    "tool": None,
                    "answer": "Complete.",
                    "arguments": {"filename": "secret.md"},
                },
                ("read_reference",),
            )

    def test_reject_unauthorized_tool_with_arguments(self):
        with self.assertRaises(ValueError):
            validate_agent_decision(
                {
                    "action": "tool",
                    "tool": "execute_shell",
                    "answer": None,
                    "arguments": {"command": "whoami"},
                },
                ("read_reference",),
            )


if __name__ == "__main__":
    unittest.main()
