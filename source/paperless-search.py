import paperless
import lexoffice
import os
import asyncio
import logging
from db import UploadStore

logger = logging.getLogger(__name__)

# Config

def _get_env(name, default=None, required=False):
    val = os.getenv(name, default)
    if required and (val is None or (isinstance(val, str) and val.strip() == "")):
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val

# Polling
try:
    polling_interval = int(_get_env("PL2LO_POLLING_INTERVAL_S", "60"))
    if polling_interval <= 0:
        raise ValueError
except Exception:
    raise RuntimeError("PL2LO_POLLING_INTERVAL_S must be a positive integer")

# paperless-ngx
paperless_token = _get_env('PL2LO_PAPERLESS_TOKEN', required=True)
paperless_url = _get_env('PL2LO_PAPERLESS_URL', required=True)
lexoffice_tag_id_raw = _get_env('PL2LO_LEXOFFICE_TAG_ID', required=True)
try:
    lexoffice_tag_id = int(str(lexoffice_tag_id_raw).strip())
except Exception:
    raise RuntimeError("PL2LO_LEXOFFICE_TAG_ID must be an integer")

if not str(paperless_url).startswith(("http://", "https://")):
    raise RuntimeError("PL2LO_PAPERLESS_URL must start with http:// or https://")

# lexoffice
lexoffice_token = _get_env('PL2LO_LEXOFFICE_TOKEN', required=True)
lexoffice_url = _get_env('PL2LO_LEXOFFICE_URL', "https://api.lexoffice.io/v1/files")
if not str(lexoffice_url).startswith(("http://", "https://")):
    raise RuntimeError("PL2LO_LEXOFFICE_URL must start with http:// or https://")

# Lock file for preventing multiple instances
LOCK_FILE = 'script.lock'

# Database
db = UploadStore()


def create_lock():
    """Create a lock file."""
    with open(LOCK_FILE, 'w') as f:
        f.write(str(os.getpid()))


def remove_lock():
    """Remove the lock file."""
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)


def is_locked():
    """Check if the lock file exists."""
    return os.path.exists(LOCK_FILE)


async def sync_paperless_to_lexoffice():
    """
    Synchronize documents from paperless-ngx to lexoffice.

    This function:
    1. Checks if the script is already running (using a lock file)
    2. Retrieves documents from paperless-ngx that are tagged for lexoffice upload
    3. Downloads each document's content into memory
    4. Uploads each document to lexoffice

    Returns:
        None
    """
    if is_locked():
        logger.warning("Script is already running. Exiting.")
        return

    # Create the lock file
    create_lock()

    try:
        # Main script logic
        logger.info("Check for new documents in paperless-ngx tagged for upload...")
        document_ids = paperless.filter_documents_by_tags(paperless_token, paperless_url, [lexoffice_tag_id])

        # None type if error occurred (e.g., paperless-ngx not reachable)
        if document_ids is not None:

            # Download document content
            for _id in document_ids:
                if not db.is_uploaded(_id):
                    file_content = paperless.download_document(paperless_token, paperless_url, _id)
                    if file_content is not None:
                        # Upload PDF to lexoffice
                        try:
                            response = lexoffice.upload_voucher(lexoffice_token, lexoffice_url, file_content, _id)
                            db.mark_as_uploaded(_id)
                            logger.info(f"Document {_id} uploaded successfully.")
                        except Exception as e:
                            # Any failure raised by upload_voucher
                            logger.error(f"Upload failed for document {_id}. Trying again later. Error: {e}")
                    # Download failed
                    else:
                        logger.error(f"Failed to download document {_id}")

    except Exception as e:
        logger.exception(f"An error occurred: {e}")

    finally:
        # Ensure the lock file is removed even if an error occurs
        remove_lock()


async def periodic_main(interval_seconds):
    """
    Run the sync_paperless_to_lexoffice function periodically at specified intervals.

    Args:
        interval_seconds (int): The number of seconds to wait between each execution

    Returns:
        None: This function runs indefinitely in an infinite loop
    """
    while True:
        await sync_paperless_to_lexoffice()
        await asyncio.sleep(interval_seconds)


def main():
    """
    Main entry point of the application.

    This function starts the periodic execution of the sync_paperless_to_lexoffice function
    using the polling interval specified in the environment variables.

    Returns:
        None
    """
    # Configure logging level and format from env var PL2LO_LOG_LEVEL (default INFO)
    level_name = os.getenv("PL2LO_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    logger.info(f"Starting paperless-to-lexoffice with polling interval {polling_interval}s")
    asyncio.run(periodic_main(polling_interval))
    return None


if __name__ == "__main__":
    main()
