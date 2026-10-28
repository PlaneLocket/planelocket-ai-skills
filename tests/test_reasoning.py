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

    def tool_descriptions(self):
        return {
            name: {
                "description": f"Test tool: {name}",
                "arguments": {},
            }
            for name in self.available_tools()
        }

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

    def test_tool_descriptions_provided_to_model(self):
        agent, client, dispatcher = self.make_agent(
            [
                finish_decision("No diagnostics required."),
            ]
        )

        agent.run(
            "Explain system resources.",
            "Use diagnostics when necessary.",
        )

        first_call_messages = client.calls[0]["messages"]

        user_message = next(
            message["content"]
            for message in first_call_messages
            if message["role"] == "user"
        )

        descriptions = dispatcher.tool_descriptions()

        self.assertIn(
            "Available tools and argument requirements:",
            user_message,
        )

        for name, definition in descriptions.items():
            self.assertIn(name, user_message)
            self.assertIn(definition["description"], user_message)

    def test_recovers_from_invalid_tool_arguments(self):
        class ReferenceDispatcher:
            def __init__(self):
                self.calls = []

            def available_tools(self):
                return ("read_reference",)

            def execute(self, tool_name, **arguments):
                self.calls.append((tool_name, arguments))

                if set(arguments) != {"filename"}:
                    raise ValueError(
                        "read_reference requires exactly one argument: filename"
                    )

                return {
                    "tool": tool_name,
                    "result": "PSI measures resource contention.",
                }

            def tool_descriptions(self):
                return {
                    "read_reference": {
                        "description": "Read a reference document.",
                        "arguments": {
                            "filename": "Required reference filename.",
                        },
                    },
                }

        client = FakeClient(
            [
                json.dumps(
                    {
                        "action": "tool",
                        "tool": "read_reference",
                        "answer": None,
                        "arguments": {},
                    }
                ),
                json.dumps(
                    {
                        "action": "tool",
                        "tool": "read_reference",
                        "answer": None,
                        "arguments": {
                            "filename": "pressure-stall-information.md",
                        },
                    }
                ),
                finish_decision("Reference successfully retrieved."),
            ]
        )

        dispatcher = ReferenceDispatcher()

        agent = ReasoningAgent(
            client=client,
            dispatcher=dispatcher,
            max_tool_calls=3,
        )

        result = agent.run(
            "Investigate Linux PSI.",
            "Use available reference knowledge.",
        )

        self.assertTrue(result.completed)
        self.assertEqual(result.tool_calls, 2)
        self.assertEqual(len(result.observations), 2)

        self.assertIn("error", result.observations[0])
        self.assertEqual(
            result.observations[1]["result"],
            "PSI measures resource contention.",
        )

        self.assertEqual(
            dispatcher.calls,
            [
                ("read_reference", {}),
                (
                    "read_reference",
                    {"filename": "pressure-stall-information.md"},
                ),
            ],
        )

        second_call_messages = client.calls[1]["messages"]

        self.assertTrue(
            any(
                "requires exactly one argument" in message["content"]
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

    def test_observation_callback_runs_before_next_model_decision(self):
        events = []

        class TrackingClient:
            def __init__(self):
                self.responses = iter(
                    [
                        tool_decision("get_memory_usage"),
                        finish_decision("Investigation complete."),
                    ]
                )

            def chat(self, messages, response_format=None, options=None):
                events.append("model")
                return next(self.responses)

        def capture_observation(observation):
            events.append("observation")
            self.assertEqual(observation["tool"], "get_memory_usage")

        agent = ReasoningAgent(
            client=TrackingClient(),
            dispatcher=FakeDispatcher(),
            on_observation=capture_observation,
        )

        result = agent.run(
            "Check memory.",
            "Use read-only diagnostics.",
        )

        self.assertTrue(result.completed)
        self.assertEqual(
            events,
            ["model", "observation", "model"],
        )


if __name__ == "__main__":
    unittest.main()
