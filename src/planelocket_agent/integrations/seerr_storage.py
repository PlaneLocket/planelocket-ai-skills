"""Persistent storage for Seerr acquisition requests."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4


class SeerrRequestStorage:
    """Manage persistent Seerr request state using SQLite."""

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)

    def initialize(self) -> None:
        """Create the database and request table if necessary."""

        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with (
            closing(sqlite3.connect(self.database_path)) as connection,
            connection,
        ):
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS media_requests (
                    id TEXT PRIMARY KEY,
                    media_type TEXT NOT NULL
                        CHECK (media_type IN ('movie', 'tv')),
                    media_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK (status IN (
                            'pending',
                            'submitting',
                            'submitted',
                            'cancelled',
                            'expired',
                            'failed',
                            'uncertain'
                        )),
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    seerr_request_id INTEGER
                )
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_media_requests_status
                ON media_requests (status, expires_at)
                """
            )

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS acquisition_continuations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL)
                """
            )

            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(acquisition_continuations)"
                )
            }
            if "candidates" not in columns:
                connection.execute(
                    "ALTER TABLE acquisition_continuations ADD COLUMN candidates TEXT NOT NULL DEFAULT '[]'"
                )
            if "context" not in columns:
                connection.execute(
                    "ALTER TABLE acquisition_continuations ADD COLUMN context TEXT NOT NULL DEFAULT '{}'"
                )

    def create_continuation(
        self,
        title: str,
        candidates: list[dict] | None = None,
        *,
        context: dict | None = None,
    ) -> str:
        """Remember an acquisition awaiting title or season selection."""

        title = title.strip()

        if not title:
            raise ValueError("title cannot be empty")

        continuation_id = str(uuid4())
        now = datetime.now(UTC)
        expires_at = now + timedelta(minutes=15)

        with (
            closing(sqlite3.connect(self.database_path)) as connection,
            connection,
        ):
            connection.execute(
                """
                INSERT INTO acquisition_continuations (
                    id,
                    title,
                    created_at,
                    expires_at, candidates, context
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    continuation_id,
                    title,
                    now.isoformat(),
                    expires_at.isoformat(),
                    json.dumps(candidates or []),
                    json.dumps(context or {}),
                ),
            )

        return continuation_id

    def get_continuation(self, continuation_id: str) -> dict | None:
        """Retrieve an unexpired acquisition continuation."""

        now = datetime.now(UTC).isoformat()

        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.row_factory = sqlite3.Row

            row = connection.execute(
                """
                SELECT id, title, created_at, expires_at, candidates, context
                FROM acquisition_continuations
                WHERE id = ?
                AND expires_at > ?
                """,
                (continuation_id, now),
            ).fetchone()

        if row is None:
            return None
        record = dict(row)
        if "candidates" in record:
            record["candidates"] = json.loads(record["candidates"])
        record["context"] = json.loads(record["context"])
        return record

    def consume_continuation(self, continuation_id: str) -> dict | None:
        """Atomically retrieve and consume an unexpired continuation."""

        now = datetime.now(UTC).isoformat()

        with (
            closing(sqlite3.connect(self.database_path)) as connection,
            connection,
        ):
            connection.row_factory = sqlite3.Row

            row = connection.execute(
                """
                DELETE FROM acquisition_continuations
                WHERE id = ?
                AND expires_at > ?
                RETURNING id, title, created_at, expires_at, candidates, context
                """,
                (continuation_id, now),
            ).fetchone()

        if row is None:
            return None
        record = dict(row)
        if "candidates" in record:
            record["candidates"] = json.loads(record["candidates"])
        record["context"] = json.loads(record["context"])
        return record

    def create_pending(self, media_id: int, title: str) -> str:
        """Create a pending movie request and return its identifier."""

        if type(media_id) is not int or media_id <= 0:
            raise ValueError("media_id must be a positive integer")

        title = title.strip()

        if not title:
            raise ValueError("title cannot be empty")

        request_id = str(uuid4())
        now = datetime.now(UTC)
        expires_at = now + timedelta(minutes=15)

        with (
            closing(sqlite3.connect(self.database_path)) as connection,
            connection,
        ):
            connection.execute(
                """
                INSERT INTO media_requests (
                    id,
                    media_type,
                    media_id,
                    title,
                    status,
                    created_at,
                    expires_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    "movie",
                    media_id,
                    title,
                    "pending",
                    now.isoformat(),
                    expires_at.isoformat(),
                    now.isoformat(),
                ),
            )

        return request_id

    def claim_pending(self, request_id: str) -> bool:
        """Atomically claim an unexpired pending request.

        Returns True only when this caller successfully claims it.
        """

        now = datetime.now(UTC).isoformat()

        with (
            closing(sqlite3.connect(self.database_path)) as connection,
            connection,
        ):
            cursor = connection.execute(
                """
                UPDATE media_requests
                SET status = 'submitting',
                    updated_at = ?
                WHERE id = ?
                  AND status = 'pending'
                  AND expires_at > ?
                """,
                (now, request_id, now),
            )

            return cursor.rowcount == 1

    def mark_submitted(
        self,
        request_id: str,
        seerr_request_id: int,
    ) -> bool:
        """Record successful submission acknowledged by Seerr."""

        if type(seerr_request_id) is not int or seerr_request_id <= 0:
            raise ValueError("seerr_request_id must be a positive integer")

        now = datetime.now(UTC).isoformat()

        with (
            closing(sqlite3.connect(self.database_path)) as connection,
            connection,
        ):
            cursor = connection.execute(
                """
                UPDATE media_requests
                SET status = 'submitted',
                    seerr_request_id = ?,
                    updated_at = ?
                WHERE id = ?
                  AND status = 'submitting'
                """,
                (seerr_request_id, now, request_id),
            )

            return cursor.rowcount == 1

    def mark_uncertain(self, request_id: str) -> bool:
        """Mark a claimed request as requiring reconciliation.

        Used when Seerr may have accepted the request but
        its outcome could not be verified.
        """

        now = datetime.now(UTC).isoformat()

        with (
            closing(sqlite3.connect(self.database_path)) as connection,
            connection,
        ):
            cursor = connection.execute(
                """
                UPDATE media_requests
                SET status = 'uncertain',
                    updated_at = ?
                WHERE id = ?
                  AND status = 'submitting'
                """,
                (now, request_id),
            )

            return cursor.rowcount == 1

    def mark_failed(self, request_id: str) -> bool:
        """Record a request that was definitively not submitted."""

        now = datetime.now(UTC).isoformat()

        with (
            closing(sqlite3.connect(self.database_path)) as connection,
            connection,
        ):
            cursor = connection.execute(
                """
                UPDATE media_requests
                SET status = 'failed',
                    updated_at = ?
                WHERE id = ?
                  AND status = 'submitting'
                """,
                (now, request_id),
            )

            return cursor.rowcount == 1

    def get_request(self, request_id: str) -> dict | None:
        """Retrieve a media request by its internal identifier."""

        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.row_factory = sqlite3.Row

            row = connection.execute(
                """
                SELECT
                    id,
                    media_type,
                    media_id,
                    title,
                    status,
                    created_at,
                    expires_at,
                    updated_at,
                    seerr_request_id
                FROM media_requests
                WHERE id = ?
                """,
                (request_id,),
            ).fetchone()

        return dict(row) if row is not None else None

    def cancel_pending(self, request_id: str) -> bool:
        """Cancel a pending request that has not been submitted."""

        now = datetime.now(UTC).isoformat()

        with (
            closing(sqlite3.connect(self.database_path)) as connection,
            connection,
        ):
            cursor = connection.execute(
                """
                UPDATE media_requests
                SET status = 'cancelled',
                    updated_at = ?
                WHERE id = ?
                  AND status = 'pending'
                """,
                (now, request_id),
            )

            return cursor.rowcount == 1

    def expire_pending(self) -> int:
        """Expire pending requests whose confirmation window has elapsed.

        Returns the number of requests transitioned to expired.
        """

        now = datetime.now(UTC).isoformat()

        with (
            closing(sqlite3.connect(self.database_path)) as connection,
            connection,
        ):
            cursor = connection.execute(
                """
                UPDATE media_requests
                SET status = 'expired',
                    updated_at = ?
                WHERE status = 'pending'
                  AND expires_at <= ?
                """,
                (now, now),
            )

            return cursor.rowcount
