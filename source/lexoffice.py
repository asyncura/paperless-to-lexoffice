"""Client for the lexoffice file upload API."""

import logging
import time

import requests

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_BACKOFF_S = 0.5
TIMEOUT_S = 30


def upload_voucher(access_token: str, url: str, file_content: bytes, _id: int) -> requests.Response:
    """
    Upload a document as a voucher to lexoffice.

    Retries on HTTP 429 and 5xx responses and on network errors, honouring a
    numeric Retry-After header when lexoffice sends one and falling back to
    exponential backoff otherwise.

    Args:
        access_token: Authentication token for the lexoffice API.
        url: URL of the lexoffice API endpoint (e.g. https://api.lexoffice.io/v1/files).
        file_content: Binary content of the PDF file to upload.
        _id: ID of the document in paperless-ngx, used as a filename hint.

    Returns:
        The final HTTP response from lexoffice on success (HTTP 202).

    Raises:
        requests.HTTPError: If lexoffice responds with a non-202 status after any retries.
        requests.RequestException: For network errors after retries are exhausted.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    files = {
        "file": (f"{_id}.pdf", file_content, "application/pdf"),
        "type": (None, "voucher"),
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(url, headers=headers, files=files, timeout=TIMEOUT_S)

            # Success (202 Accepted)
            if response.status_code == 202:
                try:
                    resp_json = response.json()
                    uuid = resp_json.get("id") if isinstance(resp_json, dict) else None
                    if uuid:
                        logger.info(f"Document has lexoffice UUID {uuid}")
                    else:
                        logger.info("Upload accepted by lexoffice (202)")
                except Exception:
                    logger.warning("Upload accepted by lexoffice (202), but response was not valid JSON.")
                return response

            # Retriable statuses: 429, 5xx
            if response.status_code == 429 or 500 <= response.status_code < 600:
                # Determine wait time: prefer Retry-After header if present and numeric
                wait_s: float | None = None
                retry_after = response.headers.get("Retry-After")
                if retry_after is not None:
                    try:
                        wait_s = float(retry_after)
                    except Exception:
                        wait_s = None
                if wait_s is None:
                    wait_s = BASE_BACKOFF_S * (2 ** (attempt - 1))
                if attempt < MAX_RETRIES:
                    logger.warning(
                        f"Error from lexoffice (HTTP {response.status_code}). Retrying in "
                        f"{wait_s:.1f}s (attempt {attempt}/{MAX_RETRIES})..."
                    )
                    time.sleep(wait_s)
                    continue
                else:
                    # Exhausted retries for retriable status -> raise HTTPError
                    message = (
                        f"Lexoffice returned HTTP {response.status_code} after "
                        f"{attempt} attempts. No more retries."
                    )
                    http_error = requests.HTTPError(message, response=response)
                    logger.error(message)
                    raise http_error

            # Hard error -> No Retry
            try:
                body_preview = response.text[:500]
            except Exception:
                body_preview = "<unavailable>"
            message = f"Error uploading to lexoffice: HTTP {response.status_code}. Response preview: {body_preview}"
            logger.error(message)
            raise requests.HTTPError(message, response=response)

        except requests.RequestException as e:
            if attempt < MAX_RETRIES:
                wait_s = BASE_BACKOFF_S * (2 ** (attempt - 1))
                logger.warning(
                    f"Network error while uploading to lexoffice: {e}. Retrying in "
                    f"{wait_s:.1f}s (attempt {attempt}/{MAX_RETRIES})..."
                )
                time.sleep(wait_s)
                continue
            else:
                logger.error(f"Network error while uploading to lexoffice and retries exhausted: {e}")
                raise

    raise requests.RequestException("Upload to lexoffice failed due to an unknown error.")
