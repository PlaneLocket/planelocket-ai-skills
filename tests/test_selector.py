"""Unit tests for Skill selection."""

import unittest
from pathlib import Path

from planelocket_agent.registry import Skill
from planelocket_agent.selector import SkillSelector


class FakeOllamaClient:
    """Return predetermined model responses."""

    def __init__(self, response):
        self.response = response

    def chat(self, messages, response_format=None):
        return self.response

class TestSkillSelector(unittest.TestCase):

    def setUp(self):
        self.skill = Skill(
            name="linux-health-check",
            description="Inspect Linux server health.",
            path=Path("skills/linux-health-check"),
        )

    def test_valid_selection(self):
        client = FakeOllamaClient(
            '{"skill": "linux-health-check"}'
        )

        selector = SkillSelector(client)

        result = selector.select(
            "Check my server",
            [self.skill],
        )

        self.assertEqual(result, self.skill)

    def test_no_matching_skill(self):
        client = FakeOllamaClient(
            '{"skill": null}'
        )

        selector = SkillSelector(client)

        result = selector.select(
            "Bake sourdough bread",
            [self.skill],
        )

        self.assertIsNone(result)

    def test_unknown_skill_rejected(self):
        client = FakeOllamaClient(
            '{"skill": "delete-everything"}'
        )

        selector = SkillSelector(client)

        with self.assertRaises(ValueError):
            selector.select(
                "Check my server",
                [self.skill],
            )

    def test_invalid_json_rejected(self):
        client = FakeOllamaClient(
            "I recommend linux-health-check"
        )

        selector = SkillSelector(client)

        with self.assertRaises(ValueError):
            selector.select(
                "Check my server",
                [self.skill],
            )

    def test_empty_registry(self):
        client = FakeOllamaClient(
            '{"skill": "linux-health-check"}'
        )

        selector = SkillSelector(client)

        result = selector.select(
            "Check my server",
            [],
        )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
