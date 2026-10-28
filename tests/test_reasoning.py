"""Tests for iterative agent reasoning."""

import json
import unittest

from planelocket_agent.reasoning import ReasoningAgent


def tool_decision(name):
    return json.dumps(
        {
            "action": "tool",
            "tool": name,
            "answer": None,
        }
    )


def finish_decision(answer):
    return json.dumps(
        {
            "action": "finish",
            "tool": None,
            "answer": answer,
        }
    )


class FakeClient:
    """Return a predetermined sequence of agent decisions."""

    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def chat(self, messages, response_format=None, options=None):
        self.calls.append(
            {
                "messages": list(messages),
                "response_format": response_format,
                "options": options,
            }
        )

        return next(self.responses)


class FakeDispatcher:
    """Record tool execution without accessing the OS."""

    def __init__(self):
        self.calls = []

    def available_tools(self):
        return ("get_memory_usage", "get_disk_usage")

    def execute(self, tool_name):
        self.calls.append(tool_name)

        return {
            "tool": tool_name,
            "result": {
                "measurement": len(self.calls),
            },
        }


class TestReasoningAgent(unittest.TestCase):
    def make_agent(self, responses, max_tool_calls=4):
        client = FakeClient(responses)
        dispatcher = FakeDispatcher()

        agent = ReasoningAgent(
            client=client,
            dispatcher=dispatcher,
            max_tool_calls=max_tool_calls,
        )

        return agent, client, dispatcher

    def test_iterative_tool_execution(self):
        agent, client, dispatcher = self.make_agent(
            [
                tool_decision("get_memory_usage"),
                tool_decision("get_disk_usage"),
                finish_decision("No immediate capacity concerns."),
            ]
        )

        result = agent.run(
            "Investigate resource capacity.",
            "Use read-only diagnostics.",
        )

        self.assertTrue(result.completed)
        self.assertEqual(result.tool_calls, 2)
        self.assertEqual(
            dispatcher.calls,
            ["get_memory_usage", "get_disk_usage"],
        )
        self.assertEqual(
            result.answer,
            "No immediate capacity concerns.",
        )
        self.assertEqual(len(result.observations), 2)
        self.assertEqual(len(client.calls), 3)

    def test_finishes_without_tools(self):
        agent, _, dispatcher = self.make_agent(
            [
                finish_decision("No tools required."),
            ]
        )

        result = agent.run(
            "Explain what RAM is.",
            "Use tools when necessary.",
        )

        self.assertTrue(result.completed)
        self.assertEqual(result.tool_calls, 0)
        self.assertEqual(dispatcher.calls, [])

    def test_unauthorized_tool_rejected(self):
        agent, _, dispatcher = self.make_agent(
            [
                tool_decision("execute_shell_command"),
            ]
        )

        with self.assertRaisesRegex(
            ValueError,
            "Unknown or unauthorized tool",
        ):
            agent.run(
                "Execute a command.",
                "Inspect system.",
            )

        self.assertEqual(dispatcher.calls, [])


    def test_tool_call_limit(self):
        agent, client, dispatcher = self.make_agent(
            [
                tool_decision("get_memory_usage"),
                tool_decision("get_memory_usage"),
                tool_decision("get_memory_usage"),
                finish_decision(
                    "Memory was measured twice, but further "
                    "investigation was limited by the tool budget."
                ),
            ],
            max_tool_calls=2,
        )

        result = agent.run(
            "Investigate memory.",
            "Use diagnostics.",
        )

        self.assertFalse(result.completed)
        self.assertEqual(result.tool_calls, 2)
        self.assertEqual(len(dispatcher.calls), 2)
        self.assertEqual(len(result.observations), 2)
        self.assertEqual(len(client.calls), 4)
        self.assertIn("tool budget", result.answer)

    def test_invalid_json_rejected(self):
        agent, _, dispatcher = self.make_agent(
            [
                "not valid JSON",
            ]
        )

        with self.assertRaisesRegex(
            ValueError,
            "invalid decision JSON",
        ):
            agent.run(
                "Investigate memory.",
                "Use diagnostics.",
            )

        self.assertEqual(dispatcher.calls, [])

    def test_observations_preserve_order(self):
        agent, _, _ = self.make_agent(
            [
                tool_decision("get_disk_usage"),
                tool_decision("get_memory_usage"),
                finish_decision("Investigation complete."),
            ]
        )

        result = agent.run(
            "Check resources.",
            "Use diagnostics.",
        )

        self.assertEqual(
            tuple(observation["tool"] for observation in result.observations),
            ("get_disk_usage", "get_memory_usage"),
        )

    def test_observations_returned_to_model(self):
        agent, client, _ = self.make_agent(
            [
                tool_decision("get_memory_usage"),
                finish_decision("Investigation complete."),
            ]
        )

        agent.run(
            "Check memory.",
            "Use diagnostics.",
        )

        second_call_messages = client.calls[1]["messages"]

        self.assertTrue(
            any(
                "Tool execution result:" in message["content"]
                and '"get_memory_usage"' in message["content"]
                for message in second_call_messages
            )
        )

    def test_invalid_tool_budget(self):
        client = FakeClient([])
        dispatcher = FakeDispatcher()

        with self.assertRaisesRegex(
            ValueError,
            "max_tool_calls must be positive",
        ):
            ReasoningAgent(
                client=client,
                dispatcher=dispatcher,
                max_tool_calls=0,
            )


if __name__ == "__main__":
    unittest.main()
