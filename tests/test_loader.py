"""Unit tests for loading Skill instructions."""

import tempfile
import unittest
from pathlib import Path

from planelocket_agent.loader import SkillLoader
from planelocket_agent.registry import Skill


class TestSkillLoader(unittest.TestCase):

    def setUp(self):
        self.loader = SkillLoader()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

        self.skill_dir = Path(self.temporary.name) / "test-skill"
        self.skill_dir.mkdir()

        self.skill = Skill(
            name="test-skill",
            description="A test Skill.",
            path=self.skill_dir,
        )

    def write_skill(self, content):
        (self.skill_dir / "SKILL.md").write_text(
            content,
            encoding="utf-8",
        )

    def test_loads_instructions(self):
        self.write_skill(
            "---\n"
            "name: test-skill\n"
            "description: A test Skill.\n"
            "---\n"
            "# Instructions\n"
            "Inspect the system.\n"
        )

        result = self.loader.load(self.skill)

        self.assertEqual(
            result,
            "# Instructions\nInspect the system.",
        )

    def test_missing_skill_file(self):
        with self.assertRaises(FileNotFoundError):
            self.loader.load(self.skill)

    def test_missing_frontmatter(self):
        self.write_skill(
            "# Instructions\n"
            "Inspect the system.\n"
        )

        with self.assertRaisesRegex(
            ValueError, "Missing frontmatter"
        ):
            self.loader.load(self.skill)

    def test_unterminated_frontmatter(self):
        self.write_skill(
            "---\n"
            "name: test-skill\n"
            "description: A test Skill.\n"
        )

        with self.assertRaisesRegex(
            ValueError, "Unterminated frontmatter"
        ):
            self.loader.load(self.skill)

    def test_empty_instructions(self):
        self.write_skill(
            "---\n"
            "name: test-skill\n"
            "description: A test Skill.\n"
            "---\n"
        )

        with self.assertRaisesRegex(
            ValueError, "Skill has no instructions"
        ):
            self.loader.load(self.skill)


if __name__ == "__main__":
    unittest.main()
