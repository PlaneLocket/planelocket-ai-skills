"""Select an appropriate Skill using an LLM."""

import json

from planelocket_agent.ollama import OllamaClient
from planelocket_agent.registry import Skill


class SkillSelector:
    """Use an LLM to select from registered Skills."""

    def __init__(self, client: OllamaClient):
        self.client = client

    def select(
        self,
        user_request: str,
        skills: list[Skill],
    ) -> Skill | None:
        """Return the selected Skill, or None."""

        if not skills:
            return None

        available = [
            {
                "name": skill.name,
                "description": skill.description,
            }
            for skill in skills
        ]

        messages = [
            {
                "role": "system",
                "content": (
                    "You select Skills for an AI agent. "
                    "Choose a Skill only when its description "
                    "matches the user's request. "
                    "If none match, choose null. "
                    'Return only JSON: {"skill": "name"} '
                    'or {"skill": null}. '
                    "Do not invent Skill names."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Available Skills:\n"
                    f"{json.dumps(available, indent=2)}\n\n"
                    f"User request:\n{user_request}"
                ),
            },
        ]

        response = self.client.chat(
            messages,
            response_format={
                "type": "object",
                "properties": {
                    "skill": {
                        "type": ["string", "null"],
                    },
                },
                "required": ["skill"],
                "additionalProperties": False,
            },
            options={
                "temperature": 0,
            },
        )

        try:
            result = json.loads(response)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM returned invalid JSON: {response}") from exc

        if not isinstance(result, dict):
            raise ValueError("LLM response must be a JSON object")

        selected_name = result.get("skill")

        if selected_name is None:
            return None

        for skill in skills:
            if skill.name == selected_name:
                return skill

        raise ValueError(f"LLM selected an unknown Skill: {selected_name}")
