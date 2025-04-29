# Paperless-to-Lexoffice

A Docker Container for synchronizing documents from paperless-ngx to lexoffice.

## Overview

Paperless-to-Lexoffice automatically transfers documents from your paperless-ngx instance to your lexoffice account. The
tool monitors documents with specific tags in paperless-ngx and uploads them to lexoffice as vouchers.

## Prerequisites

Before using this tool, you need to prepare the following:

- **Lexoffice API Access**: Ensure your lexoffice plan includes access to the Public API (not all plans include this
  feature)
- **Authentication Tokens**:
    - Generate a token in paperless-ngx
    - [Generate a token in lexoffice for using the Public API](https://app.lexoffice.de/addons/public-api)
- **Paperless-ngx Tags**:
    - Create a tag for marking documents to be synced with lexoffice (e.g., "lexoffice" or "voucher")

## Installation

To install paperless-to-lexoffice:

### Option 1: Using a Single Docker Command (Recommended)

If you prefer a simpler setup without separate configuration files, you can use a single docker command:

```bash
docker run -d \
  --name paperless-to-lexoffice \
  --restart unless-stopped \
  -v ./data:/data \
  -e PL2LO_PAPERLESS_TOKEN="your-paperless-token-here" \
  -e PL2LO_PAPERLESS_URL="http://your-paperless-instance:port" \
  -e PL2LO_LEXOFFICE_TAG_ID=42 \
  -e PL2LO_LEXOFFICE_TOKEN="your-lexoffice-api-token-here" \
  asyncura/paperless-to-lexoffice:latest
```

### Option 2: Using Docker Compose (Recommended)

1. Create a new directory for your configuration files
2. Download the `docker-compose.yml` and `docker-compose.env` files:
   ```bash
   curl -O https://raw.githubusercontent.com/asyncura/paperless-to-lexoffice/main/docker/docker-compose.yml
   curl -O https://raw.githubusercontent.com/asyncura/paperless-to-lexoffice/main/docker/docker-compose.env
   ```
3. Modify the `docker-compose.env` file with your:
    - Authentication tokens
    - Paperless-ngx URL
    - Tag IDs for the tags mentioned in prerequisites
4. Run the following command in the directory containing `docker-compose.yml` and `docker-compose.env`:
   ```bash
   docker-compose up -d
   ```

Replace the environment variable values with your actual configuration:

- `your-paperless-token-here`: Your paperless-ngx authentication token
- `http://your-paperless-instance:8000`: URL of your paperless-ngx instance
- `42`: ID of your lexoffice tag in paperless-ngx
- `your-lexoffice-api-token-here`: Your lexoffice API token

### Option 3: Building from Source

1. Clone or download this repository
2. Navigate to the `docker` directory
3. Modify the `docker-compose.env` file with your configuration
4. Run the following command:
   ```bash
   docker-compose up -d
   ```

## Database Persistence

The application uses a SQLite database to track which documents have been uploaded to lexoffice. By default, this
database is stored inside the container at `/data/upload_store.db` and will be lost when the container is removed or
recreated.

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
      - ./data:/data  # This will persist the database file
```

This creates a `data` directory in the same location as your `docker-compose.yml` file and mounts it to the `/data`
directory inside the container, ensuring the database file is preserved across container restarts and updates.

## Environment Variables

Configure the following environment variables in the `docker-compose.env` file:

| Variable                 | Description                              | Default                             | Example                               |
|--------------------------|------------------------------------------|-------------------------------------|---------------------------------------|
| PL2LO_POLLING_INTERVAL_S | Polling interval in seconds              | 60                                  | `60`                                  |
| PL2LO_PAPERLESS_TOKEN    | Authentication token for paperless-ngx   | None - Required                     | `"your-paperless-token-here"`         |
| PL2LO_PAPERLESS_URL      | URL of the paperless-ngx instance        | None - Required                     | `"http://192.168.0.5:8000"`           |
| PL2LO_LEXOFFICE_TAG_ID   | ID of the lexoffice tag in paperless-ngx | None - Required                     | `42`                                  |
| PL2LO_LEXOFFICE_TOKEN    | Authentication token for lexoffice       | None - Required                     | `"your-lexoffice-api-token-here"`     |
| PL2LO_LEXOFFICE_URL      | URL of the lexoffice API endpoint        | "https://api.lexoffice.io/v1/files" | `"https://api.lexoffice.io/v1/files"` |

Example `docker-compose.env` file:

```
# Polling interval
PL2LO_POLLING_INTERVAL_S=60

# Settings for paperless-ngx
PL2LO_PAPERLESS_TOKEN="TOKEN"  # Enter your paperless-ngx token here
PL2LO_PAPERLESS_URL="http://192.168.0.5:8000"  # Change this to your paperless-ngx URL
PL2LO_LEXOFFICE_TAG_ID=42  # Change this to your lexoffice Tag ID

# Settings for lexoffice
# Caution: Only works with lexoffice plans that include the public API unfortunately
PL2LO_LEXOFFICE_TOKEN="TOKEN"  # Enter your lexoffice API token here
PL2LO_LEXOFFICE_URL="https://api.lexoffice.io/v1/files"
```

## How It Works

1. The tool periodically checks paperless-ngx for documents that have the specified lexoffice tag (configured via
   `PL2LO_LEXOFFICE_TAG_ID`)
2. When matching documents are found, they are downloaded and uploaded to lexoffice as vouchers
3. After successful upload, the document ID is recorded in a SQLite database to prevent duplicate uploads
4. The process repeats at the interval specified by `PL2LO_POLLING_INTERVAL_S` (default: 60 seconds)

## Limitations

This tool is in early development and has primarily been tested with personal document management workflows and
currently not suited for production use. Features and functionality may change as development continues. This Project is
provided with absolutely no warranty.

Feedback and contributions are very welcome!

## Special Thanks

Special thanks to the developers of paperless-ngx for creating such an excellent document management system with an
accessible API that makes it easy to develop integrations like this one.
