import tempfile
import unittest
from pathlib import Path

from planelocket_agent.registry import SkillRegistry


class TestSkillRegistry(unittest.TestCase):
    def test_discovers_valid_skill(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill_dir = root / "example-skill"
            skill_dir.mkdir()

            (skill_dir / "SKILL.md").write_text(
                "---\n"
                "name: example-skill\n"
                "description: An example Skill.\n"
                "---\n"
                "\n"
                "# Example Skill\n",
                encoding="utf-8",
            )

            registry = SkillRegistry(root)
            skills = registry.discover()

            self.assertEqual(len(skills), 1)
            self.assertEqual(skills[0].name, "example-skill")
            self.assertEqual(
                skills[0].description,
                "An example Skill.",
            )

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            registry = SkillRegistry(Path(temporary))
            self.assertEqual(registry.discover(), [])

    def test_missing_description(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill_dir = root / "example-skill"
            skill_dir.mkdir()

            (skill_dir / "SKILL.md").write_text(
                "---\nname: example-skill\n---\n",
                encoding="utf-8",
            )

            registry = SkillRegistry(root)

            with self.assertRaisesRegex(ValueError, "Missing description"):
                registry.discover()

    def test_invalid_skill_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill_dir = root / "Invalid_Skill"
            skill_dir.mkdir()

            (skill_dir / "SKILL.md").write_text(
                "---\nname: Invalid_Skill\ndescription: Test invalid naming.\n---\n",
                encoding="utf-8",
            )

            registry = SkillRegistry(root)

            with self.assertRaisesRegex(ValueError, "Invalid Skill name"):
                registry.discover()


if __name__ == "__main__":
    unittest.main()
