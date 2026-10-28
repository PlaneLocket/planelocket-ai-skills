"""Load PlaneLocket AI's local configuration."""

from pathlib import Path

from dotenv import load_dotenv


def load_config() -> None:
    """Load configuration from the project's .env file."""

    project_root = Path(__file__).resolve().parents[2]
    load_dotenv(project_root / ".env")
