import paperless
import lexoffice
import os
import asyncio
from db import UploadStore

# Config

polling_interval = int(os.getenv("PL2LO_POLLING_INTERVAL_S"))

# paperless-ngx
paperless_token = os.getenv('PL2LO_PAPERLESS_TOKEN')
paperless_url = os.getenv('PL2LO_PAPERLESS_URL')
inbox_tag_id = os.getenv('PL2LO_INBOX_TAG_ID')
lexoffice_tag_id = os.getenv('PL2LO_LEXOFFICE_TAG_ID')

# lexoffice
lexoffice_token = os.getenv('PL2LO_LEXOFFICE_TOKEN')
lexoffice_url = os.getenv('PL2LO_LEXOFFICE_URL')

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
    5. If upload is successful, removes the inbox tag from the document in paperless-ngx

    Returns:
        None
    """
    if is_locked():
        print("Script is already running. Exiting.")
        return

    # Create the lock file
    create_lock()

    try:
        # Main script logic
        print("Check for new documents in paperless-ngx tagged for upload...")
        document_ids = paperless.filter_documents_by_tags(paperless_token, paperless_url,
                                                          [inbox_tag_id, lexoffice_tag_id])

        # None type if error occurred (e.g., paperless-ngx not reachable)
        if document_ids is not None:

            # Download document content
            for _id in document_ids:
                if not db.is_uploaded(_id):
                    file_content = paperless.download_document(paperless_token, paperless_url, _id)
                    if file_content is not None:
                        # Upload PDF to lexoffice
                        response = lexoffice.upload_voucher(lexoffice_token, lexoffice_url, file_content, _id)

                        # Upload successful
                        if response.status_code == 202:
                            paperless.remove_tag(paperless_token, paperless_url, _id, [inbox_tag_id])
                            db.mark_as_uploaded(_id)
                            print(f"Document {_id} uploaded successfully.")
                        # Upload failed
                        else:
                            print(f"Upload failed. Trying again later. HTTP error {response.status_code}")
                    # Download failed
                    else:
                        print(f"Failed to download document {_id}")

    except Exception as e:
        print(f"An error occurred: {e}")

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
    asyncio.run(periodic_main(polling_interval))
    return None


if __name__ == "__main__":
    main()
