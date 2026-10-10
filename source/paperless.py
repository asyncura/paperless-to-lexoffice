"""Client for the paperless-ngx REST API.

Written against API version 10, the default of paperless-ngx 3.x. See the
"Compatibility" section of the README for what changed and why it matters.
"""

import json
import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

# paperless-ngx API version this client is written against. Servers running
# paperless-ngx 3.x support versions "9" and "10" and default to "10"; API
# version 1 was removed in 3.0.0.
DEFAULT_API_VERSION = "10"

# Number of documents requested per page when walking list endpoints.
PAGE_SIZE = 100


def _headers(
    access_token: str,
    api_version: str | None = DEFAULT_API_VERSION,
    content_type: str | None = None,
) -> dict[str, str]:
    """
    Build the HTTP headers for a paperless-ngx API request.

    Args:
        access_token: Authentication token for paperless-ngx API
        api_version: API version to pin via the Accept header, or
            None to let the server pick its default version
        content_type: Optional Content-Type header value

    Returns:
        The request headers.
    """
    accept = "application/json"
    if api_version:
        accept = f"{accept}; version={api_version}"

    headers = {
        "Authorization": f"Token {access_token}",
        "Accept": accept,
    }
    if content_type:
        headers["Content-Type"] = content_type

    return headers


def _request(
    method: str,
    url: str,
    access_token: str,
    api_version: str | None = DEFAULT_API_VERSION,
    content_type: str | None = None,
    **kwargs: Any,
) -> requests.Response:
    """
    Send a request to paperless-ngx, retrying unpinned if the version is rejected.

    paperless-ngx answers an unsupported `Accept: application/json; version=N`
    with HTTP 406, which is what an older server does when asked for a version
    it does not know. The response shapes this client relies on are identical
    across API versions, so retry once without the pin instead of failing.

    Args:
        method: HTTP method
        url: The API endpoint URL
        access_token: Authentication token for paperless-ngx API
        api_version: API version to pin via the Accept header
        content_type: Optional Content-Type header value
        **kwargs: Passed through to requests.request

    Returns:
        The response from paperless-ngx.

    Raises:
        requests.RequestException: For network-related errors
    """
    response = requests.request(
        method, url, headers=_headers(access_token, api_version, content_type), **kwargs
    )

    if response.status_code == 406 and api_version:
        logger.warning(
            f"paperless-ngx does not support API version {api_version} (HTTP 406). "
            "Retrying without a version pin - consider upgrading paperless-ngx."
        )
        # Return a streamed, unread body to the connection pool before retrying
        response.close()
        response = requests.request(
            method, url, headers=_headers(access_token, None, content_type), **kwargs
        )

    return response


def _retrieve_document(
    url: str,
    access_token: str,
    params: dict[str, Any] | None = None,
    api_version: str | None = DEFAULT_API_VERSION,
    ordering: str | None = "id",
    timeout: float = 15,
) -> list[int] | None:
    """
    Internal helper function to retrieve document IDs from paperless-ngx API.

    Walks every page of the list endpoint. API version 10 no longer returns the
    `all` field that used to carry every matching ID on the first page, so the
    IDs are collected from `results` instead. Pages are requested by number
    against `url` rather than by following the server's `next` link, because
    that link is built from the host paperless-ngx was reached on and need not
    be reachable under PL2LO_PAPERLESS_URL.

    Args:
        url: The API endpoint URL to query
        access_token: Authentication token for paperless-ngx API
        params: Optional query string parameters
        api_version: API version to pin via the Accept header
        ordering: Sort key to page by, or None to leave the ordering
            to paperless-ngx
        timeout: Request timeout in seconds

    Returns:
        Every matching document ID, or None if the lookup failed.
    """
    document_ids = []
    seen = set()
    page = 1

    base_params = dict(params or {})
    # Paging over the default `-created` ordering is not stable: `created` is a
    # date (not a datetime) since API version 9, so documents filed on the same
    # day tie and a document can shift between pages while they are fetched -
    # silently missing one. Ordering by the unique id makes paging total.
    if ordering:
        base_params.setdefault("ordering", ordering)

    while True:
        page_params = dict(base_params)
        page_params.update({"page": page, "page_size": PAGE_SIZE})

        try:
            response = _request("GET", url, access_token, api_version, params=page_params, timeout=timeout)
        except requests.RequestException as e:
            logger.error(f"Error connecting to paperless-ngx, is it running? Error: {e}")
            return None

        if response.status_code != 200:
            logger.error(f"Search was raising HTTP error: {response.status_code}")
            return None

        try:
            search_data = response.json()
        except ValueError as e:
            logger.error(f"paperless-ngx returned a response that is not valid JSON: {e}")
            return None

        results = search_data.get('results') or []
        for document in results:
            _id = document.get('id')
            if _id is not None and _id not in seen:
                seen.add(_id)
                document_ids.append(_id)

        count = search_data.get('count')
        if not results or not search_data.get('next'):
            break
        # Guard against a server that keeps advertising a next page
        if isinstance(count, int) and len(seen) >= count:
            break

        page += 1

    logger.info(f"Found {len(document_ids)} matching document(s) in paperless-ngx")
    logger.debug(f"Matching document IDs: {document_ids}")
    return document_ids


def check_compatibility(
    access_token: str,
    base_url: str,
    api_version: str | None = DEFAULT_API_VERSION,
    timeout: float = 15,
) -> tuple[str | None, str | None]:
    """
    Probe the paperless-ngx API and log the versions it reports.

    Follows the procedure documented by paperless-ngx: perform one
    authenticated request and read the `X-Api-Version` and `X-Version`
    response headers.

    Args:
        access_token: Authentication token for paperless-ngx API
        base_url: Base URL of the paperless-ngx instance
        api_version: API version to pin via the Accept header
        timeout: Request timeout in seconds

    Returns:
        The API version and server version paperless-ngx reports, either
        of which is None if the probe failed.
    """
    url = f"{base_url}/api/documents/"
    params = {"page": 1, "page_size": 1}

    try:
        response = _request("GET", url, access_token, api_version, params=params, timeout=timeout)
    except requests.RequestException as e:
        logger.error(f"Error connecting to paperless-ngx, is it running? Error: {e}")
        return None, None

    if response.status_code in [401, 403]:
        logger.error(
            f"paperless-ngx rejected the API token (HTTP {response.status_code}). "
            "Check PL2LO_PAPERLESS_TOKEN."
        )
        return None, None

    if response.status_code != 200:
        logger.error(f"Unexpected response from paperless-ngx: HTTP {response.status_code}")
        return None, None

    server_api_version = response.headers.get("X-Api-Version")
    server_version = response.headers.get("X-Version")

    logger.info(
        f"Connected to paperless-ngx {server_version or 'unknown version'} "
        f"(API version {server_api_version or 'unknown'})"
    )

    return server_api_version, server_version


def search_documents(
    access_token: str,
    base_url: str,
    search_string: str,
    api_version: str | None = DEFAULT_API_VERSION,
) -> list[int] | None:
    """
    Search for documents in paperless-ngx using a search string.

    Args:
        access_token: Authentication token for paperless-ngx API
        base_url: Base URL of the paperless-ngx instance
        search_string: Query string to search for documents
        api_version: API version to pin via the Accept header

    Returns:
        The matching document IDs, or None if the lookup failed.
    """
    url = f"{base_url}/api/documents/"
    params = {"query": f"({search_string})"}

    # Leave the ordering to paperless-ngx: for a full text query it ranks by
    # relevance, which is the reason to use this endpoint in the first place.
    return _retrieve_document(url, access_token, params=params, api_version=api_version, ordering=None)


def filter_documents_by_tags(
    access_token: str,
    base_url: str,
    tags: list[int],
    api_version: str | None = DEFAULT_API_VERSION,
) -> list[int] | None:
    """
    Filter documents in paperless-ngx by tag IDs.

    Args:
        access_token: Authentication token for paperless-ngx API
        base_url: Base URL of the paperless-ngx instance
        tags: List of tag IDs to filter documents by
        api_version: API version to pin via the Accept header

    Returns:
        The matching document IDs, or None if the lookup failed.
    """
    tags_string = ",".join(str(tag) for tag in tags)

    url = f"{base_url}/api/documents/"
    params = {"tags__id__all": tags_string}

    return _retrieve_document(url, access_token, params=params, api_version=api_version)


def download_document(
    access_token: str,
    base_url: str,
    _id: int,
    api_version: str | None = DEFAULT_API_VERSION,
) -> bytes | None:
    """
    Download a document from paperless-ngx by its ID.

    Returns the archived PDF version when paperless-ngx has one, otherwise the
    original file.

    Args:
        access_token: Authentication token for paperless-ngx API
        base_url: Base URL of the paperless-ngx instance
        _id: ID of the document to download
        api_version: API version to pin via the Accept header

    Returns:
        The document's binary content, or None if the download failed.
    """
    url = f'{base_url}/api/documents/{_id}/download/'

    try:
        response = _request("GET", url, access_token, api_version, stream=True, timeout=60)
        document_binary = b''
        if response.status_code == 200:
            for chunk in response.iter_content(chunk_size=8192):
                document_binary += chunk

            logger.info(f"Document #{_id} downloaded successfully.")
            return document_binary
        else:
            logger.error(f"Failed to download document. Status code: {response.status_code}")
            return None

    except requests.RequestException as e:
        logger.error(f"Error connecting to paperless-ngx, is it running? Error: {e}")
        return None


def set_custom_field(
    access_token: str,
    base_url: str,
    document_id: int,
    field_id: int,
    field_value: str,
    api_version: str | None = DEFAULT_API_VERSION,
) -> bool:
    """
    Set a custom field value for a document in paperless-ngx.

    Uses the bulk edit endpoint, which adds the single field instead of
    replacing the document's whole `custom_fields` list. Note that for a
    `select` type custom field the value has to be the option's id.

    Args:
        access_token: Authentication token for paperless-ngx API
        base_url: Base URL of the paperless-ngx instance
        document_id: ID of the document to update
        field_id: ID of the custom field to set
        field_value: Value to set for the custom field
        api_version: API version to pin via the Accept header

    Returns:
        True if paperless-ngx accepted the change.
    """
    url = f'{base_url}/api/documents/bulk_edit/'

    payload = json.dumps({
        "documents": [int(document_id)],
        "method": "modify_custom_fields",
        "parameters": {
            "add_custom_fields": {str(field_id): field_value},
            "remove_custom_fields": [],
        },
    })

    try:
        response = _request(
            "POST",
            url,
            access_token,
            api_version,
            content_type="application/json",
            data=payload,
            timeout=15,
        )
        if response.status_code in [200, 201, 204]:
            logger.info(f"Custom field {field_id} set to '{field_value}' for document #{document_id}")
            return True
        else:
            logger.error(f"Failed to set custom field. Status code: {response.status_code}")
            return False

    except requests.RequestException as e:
        logger.error(f"Error connecting to paperless-ngx, is it running? Error: {e}")
        return False


def remove_tag(
    access_token: str,
    base_url: str,
    document_id: int,
    tag_ids: list[int],
    api_version: str | None = DEFAULT_API_VERSION,
) -> bool:
    """
    Remove specified tags from a document in paperless-ngx.

    Uses the bulk edit endpoint rather than reading the document and PATCHing
    its full `tags` list back: paperless-ngx 3.x applies tag hierarchy rules to
    a full `tags` update, so a read-modify-write can take descendant tags with
    it. Removing a tag the document does not carry is a no-op here.

    Args:
        access_token: Authentication token for paperless-ngx API
        base_url: Base URL of the paperless-ngx instance
        document_id: ID of the document to update
        tag_ids: List of tag IDs to remove from the document
        api_version: API version to pin via the Accept header

    Returns:
        True if paperless-ngx accepted the change.
    """
    url = f'{base_url}/api/documents/bulk_edit/'

    payload = json.dumps({
        "documents": [int(document_id)],
        "method": "modify_tags",
        "parameters": {
            "add_tags": [],
            "remove_tags": [int(tag_id) for tag_id in tag_ids],
        },
    })

    try:
        response = _request(
            "POST",
            url,
            access_token,
            api_version,
            content_type="application/json",
            data=payload,
            timeout=15,
        )
        if response.status_code in [200, 201, 204]:
            logger.info(f"Removed tag IDs {tag_ids} from document #{document_id} after successful upload to lexoffice.")
            return True
        else:
            logger.error(f"Failed to update document tags. Status code: {response.status_code}")
            return False

    except requests.RequestException as e:
        logger.error(f"Error connecting to paperless-ngx, is it running? Error: {e}")
        return False
