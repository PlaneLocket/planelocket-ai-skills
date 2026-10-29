"""Tests for centralized application logging."""

import logging

import pytest

from planelocket_agent.logging_config import configure_logging


@pytest.fixture
def application_logger():
    """Preserve and restore the application logger's configuration."""

    logger = logging.getLogger("planelocket_agent")

    original_handlers = logger.handlers[:]
    original_level = logger.level
    original_propagate = logger.propagate

    yield logger

    for handler in logger.handlers[:]:
        if handler not in original_handlers:
            logger.removeHandler(handler)

    for handler in original_handlers:
        if handler not in logger.handlers:
            logger.addHandler(handler)

    logger.setLevel(original_level)
    logger.propagate = original_propagate


def test_configure_logging_is_idempotent(application_logger):
    """Repeated configuration must not add duplicate handlers."""

    logger = application_logger
    for handler in logger.handlers[:]:
        if handler.get_name() == "planelocket-console":
            logger.removeHandler(handler)
    configure_logging()
    first_count = len(logger.handlers)

    assert first_count >= 1
    assert (
        sum(handler.get_name() == "planelocket-console" for handler in logger.handlers)
        == 1
    )
    configure_logging()

    assert len(logger.handlers) == first_count
    assert (
        sum(handler.get_name() == "planelocket-console" for handler in logger.handlers)
        == 1
    )
    assert logger.level == logging.INFO
    assert logger.propagate is False


def test_configure_logging_with_existing_handler(application_logger):
    """An unrelated handler must not block our application handler."""

    logger = application_logger
    unrelated_handler = logging.NullHandler()

    for handler in logger.handlers[:]:
        if handler.get_name() == "planelocket-console":
            logger.removeHandler(handler)

    logger.addHandler(unrelated_handler)

    configure_logging()

    handler_names = [handler.get_name() for handler in logger.handlers]

    assert "planelocket-console" in handler_names
    assert unrelated_handler in logger.handlers


def test_child_logger_writes_to_stderr(capsys, application_logger):
    """Child logger messages should reach our configured stream."""

    logger = application_logger

    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    configure_logging()

    child_logger = logging.getLogger("planelocket_agent.integrations.inventree")
    child_logger.info("InvenTree logging test")

    captured = capsys.readouterr()

    assert "INFO" in captured.err
    assert "planelocket_agent.integrations.inventree" in captured.err
    assert "InvenTree logging test" in captured.err
