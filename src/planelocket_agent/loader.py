"""Load the instructions for a registered Skill."""

from pathlib import Path

from planelocket_agent.registry import Skill


class SkillLoader:
    """Read instructions from a Skill's SKILL.md file."""

    def load(self, skill: Skill) -> str:
        """Return the instructional body of a Skill."""

        skill_file = Path(skill.path) / "SKILL.md"

        if not skill_file.is_file():
            raise FileNotFoundError(f"Skill instructions not found: {skill_file}")

        content = skill_file.read_text(encoding="utf-8")

        lines = content.splitlines()

        if not lines or lines[0].strip() != "---":
            raise ValueError(f"Missing frontmatter in {skill_file}")

        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                instructions = "\n".join(lines[index + 1 :]).strip()

                if not instructions:
                    raise ValueError(f"Skill has no instructions: {skill_file}")

                return instructions

        raise ValueError(f"Unterminated frontmatter in {skill_file}")

    def list_references(self, skill: Skill) -> tuple[str, ...]:
        """List available Markdown references for a Skill."""

        references_dir = Path(skill.path) / "references"

        if not references_dir.is_dir():
            return ()

        return tuple(
            path.name for path in sorted(references_dir.glob("*.md")) if path.is_file()
        )

    def read_reference(self, skill: Skill, filename: str) -> str:
        """Read an authorized Markdown reference for a Skill."""

        references_dir = (Path(skill.path) / "references").resolve()

        if filename not in self.list_references(skill):
            raise ValueError(f"Unknown Skill reference: {filename}")

        reference_file = (references_dir / filename).resolve()

        if not reference_file.is_relative_to(references_dir):
            raise ValueError(
                f"Skill reference escapes authorized directory: {filename}"
            )

        return reference_file.read_text(encoding="utf-8")
