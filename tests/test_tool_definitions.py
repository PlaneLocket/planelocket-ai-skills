"""Tests for structured tool definitions."""

import unittest

from planelocket_agent.tools.definitions import ToolDefinition


class TestToolDefinition(unittest.TestCase):
    def test_model_description(self):
        def example_handler(filename):
            return filename

        definition = ToolDefinition(
            name="read_reference",
            description="Read a knowledge reference.",
            handler=example_handler,
            arguments={
                "filename": "Required reference filename.",
            },
        )

        self.assertEqual(
            definition.model_description(),
            {
                "description": "Read a knowledge reference.",
                "arguments": {
                    "filename": "Required reference filename.",
                },
            },
        )

    def test_model_description_does_not_expose_handler(self):
        definition = ToolDefinition(
            name="example",
            description="Example tool.",
            handler=lambda: None,
        )

        self.assertNotIn(
            "handler",
            definition.model_description(),
        )


if __name__ == "__main__":
    unittest.main()
