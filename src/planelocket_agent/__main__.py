"""Entry point for PlaneLocket AI."""

from planelocket_agent.config import load_config


def main() -> None:
    """Initialize the application environment."""
    load_config()
    print("PlaneLocket AI configuration loaded.")


if __name__ == "__main__":
    main()
