"""Unit tests for the PlaneLocket agent orchestrator."""

import tempfile
import unittest
from pathlib import Path

from planelocket_agent.agent import PlaneLocketAgent


class FakeOllamaClient:
    """Simulate selection and planning responses."""

    def __init__(self, selection):
        self.selection = selection
        self.calls = []

    def chat(self, messages, response_format=None, options=None):
        self.calls.append({
            "messages": messages,
            "response_format": response_format,
            "options": options,
        })

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
        client = FakeOllamaClient(
            '{"skill": "linux-health-check"}'
        )

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


if __name__ == "__main__":
    unittest.main()
