"""Coordinate Skill discovery, selection, and planning."""

from pathlib import Path

from planelocket_agent.loader import SkillLoader
from planelocket_agent.memory.identifiers import new_investigation_id
from planelocket_agent.memory.models import MemoryRecord
from planelocket_agent.memory.recorder import MemoryRecorder
from planelocket_agent.ollama import OllamaClient
from planelocket_agent.reasoning import ReasoningAgent, ReasoningResult
from planelocket_agent.registry import SkillRegistry
from planelocket_agent.selector import SkillSelector
from planelocket_agent.tools.dispatcher import ToolDispatcher
from planelocket_agent.tools.knowledge import KnowledgeProvider


class PlaneLocketAgent:
    """A Skill-aware agent that produces plans without executing tools."""

    def __init__(
        self,
        skills_directory: Path,
        client: OllamaClient,
        memory_recorder: MemoryRecorder | None = None,
    ):
        self.registry = SkillRegistry(skills_directory)
        self.selector = SkillSelector(client)
        self.loader = SkillLoader()
        self.client = client
        self.memory_recorder = memory_recorder

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

    def investigate(
        self,
        user_request: str,
        dispatcher: ToolDispatcher,
        max_tool_calls: int = 6,
    ) -> ReasoningResult:
        """Select a Skill and investigate using authorized tools."""

        skills = self.registry.discover()
        selected = self.selector.select(user_request, skills)

        if selected is None:
            return ReasoningResult(
                answer="No matching Skill is available for this request.",
                observations=(),
                tool_calls=0,
                completed=False,
            )

        instructions = self.loader.load(selected)

        references = self.loader.list_references(selected)

        if references:
            instructions += (
                "\n\n## Available Knowledge References\n\n"
                "The following reference documents are available "
                "for optional retrieval using read_reference:\n"
                + "\n".join(f"- {name}" for name in references)
            )

        # Bind reference access to the Skill selected for this investigation.
        knowledge = KnowledgeProvider(selected, self.loader)

        dispatcher.bind_knowledge(knowledge)

        on_observation = None

        investigation_id = (
            new_investigation_id() if self.memory_recorder is not None else None
        )

        on_observation = None

        if self.memory_recorder is not None:

            def on_observation(observation):
                self.memory_recorder.record_observation(
                    observation,
                    investigation_id,
                )

        reasoning_agent = ReasoningAgent(
            client=self.client,
            dispatcher=dispatcher,
            max_tool_calls=max_tool_calls,
            on_observation=on_observation,
        )

        result = reasoning_agent.run(
            user_request=user_request,
            skill_instructions=instructions,
        )

        return ReasoningResult(
            answer=result.answer,
            observations=result.observations,
            tool_calls=result.tool_calls,
            completed=result.completed,
            investigation_id=investigation_id,
        )

    def get_investigation_history(
        self,
        investigation_id: str,
    ) -> list[MemoryRecord]:
        """Retrieve persisted evidence for an investigation."""
        if self.memory_recorder is None:
            raise RuntimeError(
                "Investigation history requires persistent memory to be configured."
            )

        return self.memory_recorder.get_investigation_history(investigation_id)
