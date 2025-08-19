import requests
import json
import logging

logger = logging.getLogger(__name__)

def __retrieve_document(url, headers, params=None, timeout=15):
    """
    Internal helper function to retrieve document IDs from paperless-ngx API.

    Args:
        url (str): The API endpoint URL to query
        headers (dict): HTTP headers including authorization token
        params (dict|None): Optional query string parameters
        timeout (int|float): Request timeout in seconds

    Returns:
        list: List of document IDs, or empty list if error occurs
    """
    try:
        response = requests.get(url, headers=headers, params=params, timeout=timeout)

        if response.status_code == 200:
            search_data = response.json()
            document_ids = search_data.get('all', [])
            logger.info(f"Search Results: {document_ids}")
            return document_ids
        else:
            logger.error(f"Search was raising HTTP error: {response.status_code}")
            return []

    except requests.RequestException as e:
        logger.error(f"Error connecting to paperless-ngx, is it running? Error: {e}")
        return []


def search_documents(access_token, base_url, search_string):
    """
    Search for documents in paperless-ngx using a search string.

    Args:
        access_token (str): Authentication token for paperless-ngx API
        base_url (str): Base URL of the paperless-ngx instance
        search_string (str): Query string to search for documents

    Returns:
        list: List of document IDs matching the search criteria, or empty list if error occurs
    """
    url = f"{base_url}/api/documents/"

    headers = {
        "Authorization": f"Token {access_token}",
        "Accept": "application/json",
    }
    params = {"query": f"({search_string})"}
    return __retrieve_document(url, headers, params=params)


def filter_documents_by_tags(access_token, base_url, tags: list):
    """
    Filter documents in paperless-ngx by tag IDs.

    Args:
        access_token (str): Authentication token for paperless-ngx API
        base_url (str): Base URL of the paperless-ngx instance
        tags (list): List of tag IDs to filter documents by

    Returns:
        list: List of document IDs matching the tag criteria, or empty list if error occurs
    """
    tags_string = ",".join(str(tag) for tag in tags)

    url = f"{base_url}/api/documents/"

    headers = {
        "Authorization": f"Token {access_token}",
        "Accept": "application/json",
    }
    params = {"tags__id__all": tags_string}

    return __retrieve_document(url, headers, params=params)


def download_document(access_token, base_url, _id):
    """
    Download a document from paperless-ngx by its ID.

    Args:
        access_token (str): Authentication token for paperless-ngx API
        base_url (str): Base URL of the paperless-ngx instance
        _id (int): ID of the document to download

    Returns:
        bytes: Binary content of the document if successful, None otherwise
    """
    url = f'{base_url}/api/documents/{_id}/download/'

    headers = {
        "Authorization": f"Token {access_token}",
        "Accept": "application/json",
    }

    try:
        response = requests.get(url, headers=headers, stream=True, timeout=60)
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


def set_custom_field(access_token, base_url, document_id, field_id, field_value):
    """
    Set a custom field value for a document in paperless-ngx.

    Args:
        access_token (str): Authentication token for paperless-ngx API
        base_url (str): Base URL of the paperless-ngx instance
        document_id (int): ID of the document to update
        field_id (int): ID of the custom field to set
        field_value (str): Value to set for the custom field

    Returns:
        bool: True if successful, False otherwise
    """
    url = f'{base_url}/api/documents/{document_id}/'

    headers = {
        "Authorization": f"Token {access_token}",
        "Content-Type": "application/json",
    }

    payload = json.dumps({
        "custom_fields": [
            {
                "value": field_value,
                "field": field_id
            }
        ]
    })

    try:
        response = requests.request("PATCH", url, headers=headers, data=payload, timeout=15)
        if response.status_code in [200, 201, 204]:
            logger.info(f"Custom field {field_id} set to '{field_value}' for document #{document_id}")
            return True
        else:
            logger.error(f"Failed to set custom field. Status code: {response.status_code}")
            return False

    except requests.RequestException as e:
        logger.error(f"Error connecting to paperless-ngx, is it running? Error: {e}")
        return False


def remove_tag(access_token, base_url, document_id, tag_ids):
    """
    Remove specified tags from a document in paperless-ngx.

    Args:
        access_token (str): Authentication token for paperless-ngx API
        base_url (str): Base URL of the paperless-ngx instance
        document_id (int): ID of the document to update
        tag_ids (list): List of tag IDs to remove from the document

    Returns:
        bool: True if successful, False otherwise
    """
    url = f'{base_url}/api/documents/{document_id}/'

    headers = {
        "Authorization": f"Token {access_token}",
        "Content-Type": "application/json",
    }

    # Get document
    try:
        response = requests.get(url, headers=headers, timeout=15)

        if response.status_code == 200:
            document_data = response.json()
            current_tags = document_data.get('tags', [])

            # Remove tags
            for tag_id in tag_ids:
                current_tags.remove(int(tag_id))

            payload = json.dumps({"tags": current_tags})

            response = requests.request("PATCH", url, headers=headers, data=payload, timeout=15)

            if response.status_code in [200, 201, 204]:
                logger.info(f"Removed tag IDs {tag_ids} from document #{document_id} after successful upload to lexoffice.")
                return True
            else:
                logger.error(f"Failed to update document tags. Status code: {response.status_code}")
                return False
        else:
            logger.error(f"Failed to fetch document data. Status code: {response.status_code}")
            return False

    except requests.RequestException as e:
        logger.error(f"Error connecting to paperless-ngx, is it running? Error: {e}")
        return False
