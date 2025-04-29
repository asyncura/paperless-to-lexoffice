import sqlite3
from contextlib import contextmanager


class UploadStore:
    """
    A class to track documents that have been uploaded to lexoffice.

    This class provides methods to check if a document has been uploaded
    and to mark documents as uploaded, using a SQLite database for storage.
    """
    def __init__(self, db_path="upload_store.db"):
        """
        Initialize the UploadStore with a database file path.

        Args:
            db_path (str): Path to the SQLite database file. Defaults to "upload_store.db".
        """
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """
        Initialize the database by creating the necessary table if it doesn't exist.
        """
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS uploaded_docs (
                    doc_id TEXT PRIMARY KEY,
                    upload_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

    @contextmanager
    def _get_conn(self):
        """
        Context manager for database connections.

        Yields:
            sqlite3.Connection: A database connection that will be automatically closed.
        """
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def is_uploaded(self, doc_id):
        """
        Check if a document has already been uploaded.

        Args:
            doc_id (int or str): The ID of the document to check.

        Returns:
            bool: True if the document has been uploaded, False otherwise.
        """
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM uploaded_docs WHERE doc_id = ?",
                (str(doc_id),)
            )
            return cursor.fetchone() is not None

    def mark_as_uploaded(self, doc_id):
        """
        Mark a document as uploaded in the database.

        Args:
            doc_id (int or str): The ID of the document to mark as uploaded.
        """
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO uploaded_docs (doc_id) VALUES (?)",
                (str(doc_id),)
            )
            conn.commit()


if __name__ == "__main__":
    store = UploadStore()
