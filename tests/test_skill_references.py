import tempfile
import unittest
from pathlib import Path

from planelocket_agent.loader import SkillLoader
from planelocket_agent.registry import Skill


class TestSkillReferences(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        self.root = Path(self.temp_dir.name)
        self.skill_dir = self.root / "test-skill"
        self.references_dir = self.skill_dir / "references"
        self.references_dir.mkdir(parents=True)

        self.skill = Skill(
            name="test-skill",
            description="Test reference retrieval",
            path=self.skill_dir,
        )

        self.loader = SkillLoader()

    def test_list_references(self):
        (self.references_dir / "psi.md").write_text("PSI reference", encoding="utf-8")

        (self.references_dir / "memory.md").write_text(
            "Memory reference", encoding="utf-8"
        )

        self.assertEqual(
            self.loader.list_references(self.skill),
            ("memory.md", "psi.md"),
        )

    def test_read_reference(self):
        (self.references_dir / "psi.md").write_text("PSI reference", encoding="utf-8")

        result = self.loader.read_reference(
            self.skill,
            "psi.md",
        )

        self.assertEqual(result, "PSI reference")

    def test_reject_path_traversal(self):
        with self.assertRaises(ValueError):
            self.loader.read_reference(
                self.skill,
                "../../secret.md",
            )

    def test_reject_unknown_reference(self):
        with self.assertRaises(ValueError):
            self.loader.read_reference(
                self.skill,
                "nonexistent.md",
            )

    def test_reject_symlink_escape(self):
        secret = self.root / "secret.md"
        secret.write_text(
            "Sensitive information",
            encoding="utf-8",
        )

        link = self.references_dir / "secret-link.md"
        link.symlink_to(secret)

        with self.assertRaises(ValueError):
            self.loader.read_reference(
                self.skill,
                "secret-link.md",
            )

    def test_missing_references_directory(self):
        empty_skill_dir = self.root / "empty-skill"
        empty_skill_dir.mkdir()

        empty_skill = Skill(
            name="empty-skill",
            description="No references",
            path=empty_skill_dir,
        )

        self.assertEqual(
            self.loader.list_references(empty_skill),
            (),
        )


if __name__ == "__main__":
    unittest.main()
