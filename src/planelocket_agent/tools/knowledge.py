"""Read-only knowledge tools for a selected Skill."""

from planelocket_agent.loader import SkillLoader
from planelocket_agent.registry import Skill


class KnowledgeProvider:
    """Provide controlled access to a Skill's reference material."""

    def __init__(self, skill: Skill, loader: SkillLoader):
        self._skill = skill
        self._loader = loader

    def list_references(self) -> tuple[str, ...]:
        """Return available reference filenames."""
        return self._loader.list_references(self._skill)

    def read_reference(self, filename: str) -> str:
        """Read an authorized reference document."""
        return self._loader.read_reference(self._skill, filename)
