from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class Skill:
    """Metadata describing an installed Skill."""

    name: str
    description: str
    path: Path


class SkillRegistry:
    """Discover and validate Skills stored on disk."""

    NAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")

    def __init__(self, skills_directory: Path):
        self.skills_directory = Path(skills_directory)

    def discover(self) -> list[Skill]:
        """Return all valid Skills in the Skills directory."""

        if not self.skills_directory.is_dir():
            return []

        skills = []
        names = set()

        for directory in sorted(self.skills_directory.iterdir()):

            if not directory.is_dir():
                continue

            skill_file = directory / "SKILL.md"

            if not skill_file.is_file():
                continue

            skill = self._load_skill(skill_file)

            if skill.name in names:
                raise ValueError(
                    f"Duplicate Skill name: {skill.name}"
                )

            names.add(skill.name)
            skills.append(skill)

        return skills

    def _load_skill(self, skill_file: Path) -> Skill:
        """Read and validate a Skill's metadata."""

        content = skill_file.read_text(encoding="utf-8")

        metadata = self._parse_frontmatter(content)

        name = metadata.get("name", "").strip()
        description = metadata.get("description", "").strip()

        if not self.NAME_PATTERN.fullmatch(name):
            raise ValueError(
                f"Invalid Skill name in {skill_file}: {name!r}"
            )

        if not description:
            raise ValueError(
                f"Missing description in {skill_file}"
            )

        if skill_file.parent.name != name:
            raise ValueError(
                f"Skill directory must match its name: {name}"
            )

        return Skill(
            name=name,
            description=description,
            path=skill_file.parent,
        )

    @staticmethod
    def _parse_frontmatter(content: str) -> dict[str, str]:
        """Parse the supported subset of YAML frontmatter."""

        lines = content.splitlines()

        if not lines or lines[0].strip() != "---":
            raise ValueError("SKILL.md is missing YAML frontmatter")

        metadata = {}
        current_key = None
        multiline = False

        for line in lines[1:]:

            if line.strip() == "---":
                return metadata

            if line.startswith((" ", "\t")):
                if multiline and current_key:
                    metadata[current_key] += " " + line.strip()
                continue

            if ":" not in line:
                continue

            key, value = line.split(":", 1)

            key = key.strip()
            value = value.strip()

            if key not in {"name", "description"}:
                continue

            current_key = key
            multiline = value in {">", "|"}

            metadata[key] = "" if multiline else value.strip("'\"")

        raise ValueError("YAML frontmatter is not closed")
