"""Identifiers for persistent investigation memory."""

from uuid import uuid4


def new_investigation_id() -> str:
    """Generate a unique identifier for an investigation."""
    return str(uuid4())
