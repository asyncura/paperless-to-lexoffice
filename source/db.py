"""SQLite-backed record of which paperless-ngx documents reached lexoffice."""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

DEFAULT_DB_PATH = "/data/upload_store.db"


class UploadStore:
    """
    Tracks the documents that have been uploaded to lexoffice.

    Uploading is not idempotent on the lexoffice side - the same file posted
    twice becomes two vouchers - so the daemon consults this store before every
    upload. The store is a SQLite database and should live on a persistent
    volume; see the "Database Persistence" section of the README.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        """
        Open the store, creating the database file and schema if needed.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path
        # Ensure the parent directory exists to avoid sqlite3.connect errors
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create the uploaded_docs table if it does not exist yet."""
        with self._get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS uploaded_docs
                (
                    doc_id           TEXT PRIMARY KEY,
                    upload_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    @contextmanager
    def _get_conn(self) -> Iterator[sqlite3.Connection]:
        """
        Open a database connection for the duration of the block.

        Yields:
            A connection that is closed again when the block exits.
        """
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def is_uploaded(self, doc_id: int | str) -> bool:
        """
        Check whether a document has already been uploaded.

        Args:
            doc_id: ID of the document to check.

        Returns:
            True if the document has been uploaded before.
        """
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM uploaded_docs WHERE doc_id = ?",
                (str(doc_id),),
            )
            return cursor.fetchone() is not None

    def mark_as_uploaded(self, doc_id: int | str) -> None:
        """
        Record a document as uploaded.

        Recording the same document twice is a no-op rather than an error, so a
        retry that races an earlier success cannot break the sync loop.

        Args:
            doc_id: ID of the document to record.
        """
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO uploaded_docs (doc_id) VALUES (?)",
                (str(doc_id),),
            )
            conn.commit()
