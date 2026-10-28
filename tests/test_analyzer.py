"""Tests for diagnostic evidence analysis."""

import unittest

from planelocket_agent.tools.analyzer import DiagnosticAnalyzer
from planelocket_agent.tools.coordinator import DiagnosticExecution


class FakeOllamaClient:
    """Capture model requests and return controlled responses."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def chat(self, messages, response_format=None, options=None):
        self.calls.append(
            {
                "messages": messages,
                "response_format": response_format,
                "options": options,
            }
        )
        return self.response


class TestDiagnosticAnalyzer(unittest.TestCase):
    def setUp(self):
        self.execution = DiagnosticExecution(
            requested_tools=(
                "get_memory_usage",
                "get_disk_usage",
            ),
            results=(
                {
                    "tool": "get_memory_usage",
                    "result": {
                        "total_bytes": 1000,
                        "used_bytes": 250,
                        "used_percent": 25.0,
                    },
                },
                {
                    "tool": "get_disk_usage",
                    "result": {
                        "mount_point": "/",
                        "total_bytes": 1000,
                        "used_bytes": 500,
                        "used_percent": 50.0,
                    },
                },
            ),
        )

    def test_returns_assessment(self):
        client = FakeOllamaClient("Memory utilization is 25%.")
        analyzer = DiagnosticAnalyzer(client)

        result = analyzer.analyze(
            "Check system health.",
            "Inspect memory and disk.",
            self.execution,
        )

        self.assertEqual(
            result,
            "Memory utilization is 25%.",
        )
        self.assertEqual(len(client.calls), 1)

    def test_includes_diagnostic_evidence(self):
        client = FakeOllamaClient("Assessment")
        analyzer = DiagnosticAnalyzer(client)

        analyzer.analyze(
            "Check system health.",
            "Inspect memory and disk.",
            self.execution,
        )

        messages = client.calls[0]["messages"]
        user_message = messages[1]["content"]

        self.assertIn(
            "Check system health.",
            user_message,
        )
        self.assertIn(
            "Inspect memory and disk.",
            user_message,
        )

        self.assertIn(
            '"used_percent": 25.0',
            user_message,
        )
        self.assertIn(
            '"used_percent": 50.0',
            user_message,
        )

    def test_evidence_preserves_tool_names(self):
        client = FakeOllamaClient("Assessment")
        analyzer = DiagnosticAnalyzer(client)

        analyzer.analyze(
            "Check system health.",
            "Inspect system.",
            self.execution,
        )

        user_message = client.calls[0]["messages"][1]["content"]

        self.assertIn(
            '"get_memory_usage"',
            user_message,
        )
        self.assertIn(
            '"get_disk_usage"',
            user_message,
        )

    def test_temperature_is_zero(self):
        client = FakeOllamaClient("Assessment")
        analyzer = DiagnosticAnalyzer(client)

        analyzer.analyze(
            "Check system health.",
            "Inspect system.",
            self.execution,
        )

        self.assertEqual(
            client.calls[0]["options"]["temperature"],
            0,
        )

    def test_empty_response_rejected(self):
        client = FakeOllamaClient("   ")
        analyzer = DiagnosticAnalyzer(client)

        with self.assertRaisesRegex(
            ValueError,
            "empty response",
        ):
            analyzer.analyze(
                "Check system health.",
                "Inspect system.",
                self.execution,
            )

    def test_non_string_response_rejected(self):
        client = FakeOllamaClient(None)
        analyzer = DiagnosticAnalyzer(client)

        with self.assertRaises(ValueError):
            analyzer.analyze(
                "Check system health.",
                "Inspect system.",
                self.execution,
            )

    def test_response_whitespace_removed(self):
        client = FakeOllamaClient("\n  Memory utilization is low.  \n")
        analyzer = DiagnosticAnalyzer(client)

        result = analyzer.analyze(
            "Check memory.",
            "Inspect memory.",
            self.execution,
        )

        self.assertEqual(
            result,
            "Memory utilization is low.",
        )


if __name__ == "__main__":
    unittest.main()
