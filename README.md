# Paperless-to-Lexoffice

A tool for synchronizing documents from paperless-ngx to lexoffice in a unidirectional manner.

## Overview

Paperless-to-Lexoffice automatically transfers documents from your paperless-ngx instance to your lexoffice account. The
tool monitors documents with specific tags in paperless-ngx and uploads them to lexoffice as vouchers.

## Prerequisites

Before using this tool, you need to prepare the following:

- **Lexoffice API Access**: Ensure your lexoffice plan includes access to the Public API (not all plans include this
  feature)
- **Authentication Tokens**:
    - Generate a token in paperless-ngx (user must have rights to view documents and edit tags)
    - Generate a token in lexoffice for using the Public API
- **Paperless-ngx Tags**:
    - Create a tag that indicates documents requiring processing (e.g., "Inbox")
    - Create a tag for marking documents to be synced with lexoffice (e.g., "lexoffice")

## Installation

To install paperless-to-lexoffice:

1. Clone or download this repository
2. Navigate to the `docker` directory
3. Modify the `docker-compose.env` file with your:
    - Authentication tokens
    - Paperless-ngx URL
    - Tag IDs for the tags mentioned in prerequisites
4. Run the following command in the directory containing `docker-compose.yml` and `docker-compose.env`:

```bash
docker-compose up -d
```

## Database Persistence

The application uses a SQLite database to track which documents have been uploaded to lexoffice. By default, this
database is stored inside the container and will be lost when the container is removed or recreated.

To make the database persistent:

1. Modify your `docker-compose.yml` file to add a volume:

```yaml
version: '3'
services:
  daemon:
    image: asyncura/paperless-to-lexoffice:latest
    container_name: paperless-to-lexoffice
    env_file:
      - docker-compose.env
    restart: unless-stopped
    volumes:
      - ./data:/app  # This will persist the database file
```

This creates a `data` directory in the same location as your `docker-compose.yml` file and mounts it to the `/app`
directory inside the container, ensuring the database file is preserved across container restarts and updates.

## Environment Variables

Configure the following environment variables in the `docker-compose.env` file:

| Variable                 | Description                              | Default  |
|--------------------------|------------------------------------------|----------|
| PL2LO_POLLING_INTERVAL_S | Polling interval in seconds              | 60       |
| PL2LO_PAPERLESS_TOKEN    | Authentication token for paperless-ngx   | Required |
| PL2LO_PAPERLESS_URL      | URL of the paperless-ngx instance        | Required |
| PL2LO_INBOX_TAG_ID       | ID of the inbox tag in paperless-ngx     | Required |
| PL2LO_LEXOFFICE_TAG_ID   | ID of the lexoffice tag in paperless-ngx | Required |
| PL2LO_LEXOFFICE_TOKEN    | Authentication token for lexoffice       | Required |
| PL2LO_LEXOFFICE_URL      | URL of the lexoffice API endpoint        | Required |

## How It Works

1. The tool periodically checks paperless-ngx for documents that have both the "inbox" and "lexoffice" tags
2. When matching documents are found, they are downloaded and uploaded to lexoffice as vouchers
3. After successful upload, the "inbox" tag is removed from the document in paperless-ngx
4. The document ID is recorded in the database to prevent duplicate uploads

## Limitations

This tool is in early development and has primarily been tested with personal document management workflows and
currently not suited for production use. Features and functionality may change as development continues. This Project is
provided with absolutely no warranty.

Feedback and contributions are very welcome!

## Special Thanks

Special thanks to the developers of paperless-ngx for creating such an excellent document management system with an
accessible API that makes it easy to develop integrations like this one.
