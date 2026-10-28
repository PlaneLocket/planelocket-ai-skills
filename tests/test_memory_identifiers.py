"""Tests for investigation identifiers."""

import unittest
from uuid import UUID

from planelocket_agent.memory.identifiers import new_investigation_id


class TestInvestigationIdentifiers(unittest.TestCase):
    def test_generates_valid_uuid(self):
        investigation_id = new_investigation_id()

        self.assertEqual(
            str(UUID(investigation_id)),
            investigation_id,
        )

    def test_generates_distinct_identifiers(self):
        first = new_investigation_id()
        second = new_investigation_id()

        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
