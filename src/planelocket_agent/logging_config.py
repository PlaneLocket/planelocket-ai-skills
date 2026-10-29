"""Centralized logging configuration for PlaneLocket AI."""

import logging


def configure_logging() -> None:
    """Configure the PlaneLocket AI application logger."""

    logger = logging.getLogger("planelocket_agent")
    logger.setLevel(logging.INFO)

    if not any(
        handler.get_name() == "planelocket-console" for handler in logger.handlers
    ):
        handler = logging.StreamHandler()
        handler.set_name("planelocket-console")
        logger.propagate = False

        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

        handler.setFormatter(formatter)

        logger.addHandler(handler)
