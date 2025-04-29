import requests
from time import sleep


def upload_voucher(access_token, url, file_content, _id):
    """
    Upload a document as a voucher to lexoffice.

    Args:
        access_token (str): Authentication token for lexoffice API
        url (str): URL of the lexoffice API endpoint
        file_content (bytes): Binary content of the file to be uploaded
        _id (int): ID of the document in paperless-ngx

    Returns:
        requests.Response: The response object from the API request
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    files = {
        "file": (f"{_id}.pdf", file_content, "application/pdf"),
        "type": (None, "voucher"),
    }

    sleep(0.5)
    response = requests.post(url, headers=headers, files=files)

    # Print the response from the server
    if response.status_code == 202:
        print(f"Document has lexoffice UUID {response.json().get('id')}")
    else:
        print(f"Error uploading: {response.status_code}")

    return response
