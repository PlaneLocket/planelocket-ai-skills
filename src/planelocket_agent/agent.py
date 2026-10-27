"""Coordinate Skill discovery, selection, and planning."""

from pathlib import Path

from planelocket_agent.loader import SkillLoader
from planelocket_agent.ollama import OllamaClient
from planelocket_agent.registry import SkillRegistry
from planelocket_agent.selector import SkillSelector


class PlaneLocketAgent:
    """A Skill-aware agent that produces plans without executing tools."""

    def __init__(
        self,
        skills_directory: Path,
        client: OllamaClient,
    ):
        self.registry = SkillRegistry(skills_directory)
        self.selector = SkillSelector(client)
        self.loader = SkillLoader()
        self.client = client

    def plan(self, user_request: str) -> str:
        """Select a Skill and generate a read-only diagnostic plan."""

        skills = self.registry.discover()
        selected = self.selector.select(user_request, skills)

        if selected is None:
            return "No matching Skill is available for this request."

        instructions = self.loader.load(selected)

        messages = [
            {
                "role": "system",
                "content": (
                    "You are the PlaneLocket AI Agent. "
                    "Your task is to produce a diagnostic plan, "
                    "not execute commands. "
                    "The selected Skill provides task guidance, "
                    "but does not grant execution permissions. "
                    "Do not claim that you inspected any system. "
                    "Do not invent measurements, service states, "
                    "or diagnostic results. "
                    "Clearly identify any authorization or "
                    "information needed before execution."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Selected Skill: {selected.name}\n\n"
                    f"Skill instructions:\n{instructions}\n\n"
                    f"User request:\n{user_request}\n\n"
                    "Produce a concise diagnostic plan. "
                    "Explain what information should be collected, "
                    "which checks should be performed, "
                    "and how results would be evaluated. "
                    "Do not execute anything."
                ),
            },
        ]

        return self.client.chat(messages)
