"""Tests for structured tool definitions."""

import unittest

from planelocket_agent.tools.definitions import (
    ToolArgument,
    ToolDefinition,
)


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

    def test_tool_argument_defaults(self):
        argument = ToolArgument(
            description="Reference filename.",
        )

        self.assertEqual(argument.value_type, str)
        self.assertTrue(argument.required)
        self.assertFalse(argument.allow_empty)

    def test_optional_integer_argument(self):
        argument = ToolArgument(
            description="Maximum number of results.",
            value_type=int,
            required=False,
        )

        self.assertEqual(argument.value_type, int)
        self.assertFalse(argument.required)

    def test_typed_argument_model_description(self):
        definition = ToolDefinition(
            name="search_memory",
            description="Search stored knowledge.",
            handler=lambda limit=10: [],
            arguments={
                "limit": ToolArgument(
                    description="Maximum number of results.",
                    value_type=int,
                    required=False,
                ),
            },
        )

        self.assertEqual(
            definition.model_description(),
            {
                "description": "Search stored knowledge.",
                "arguments": {
                    "limit": {
                        "description": "Maximum number of results.",
                        "type": "int",
                        "required": False,
                    },
                },
            },
        )


if __name__ == "__main__":
    unittest.main()
