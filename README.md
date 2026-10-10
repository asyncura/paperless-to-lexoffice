# Paperless-to-Lexoffice

A Docker Container for synchronizing documents from paperless-ngx to lexoffice.

## Overview

Paperless-to-Lexoffice automatically transfers documents from your paperless-ngx instance to your lexoffice account. The
tool monitors documents with specific tags in paperless-ngx and uploads them to lexoffice as vouchers.

## Prerequisites

Before using this tool, you need to prepare the following:

- **paperless-ngx 3.0 or newer**: this tool talks to REST API version 10, the default of paperless-ngx 3.x.
  Older servers that do not offer API version 10 still work - the tool notices the rejection and falls
  back to the server's default API version - but they are not what it is tested against. See
  [Compatibility](#compatibility) below.
- **Lexoffice API Access**: Ensure your lexoffice plan includes access to the Public API (not all plans include this
  feature)
- **Authentication Tokens**:
    - Generate a token in paperless-ngx
    - [Generate a token in lexoffice for using the Public API](https://app.lexoffice.de/addons/public-api)
- **Paperless-ngx Tags**:
    - Create a tag for marking documents to be synced with lexoffice (e.g., "lexoffice" or "voucher")

## Installation

Pick whichever option suits you; all three run the same daemon.

### Option 1: Docker Compose (recommended)

1. Create a new directory for your configuration
2. Download the `docker-compose.yml` and `docker-compose.env` files:
   ```bash
   curl -O https://raw.githubusercontent.com/asyncura/paperless-to-lexoffice/main/docker/docker-compose.yml
   curl -O https://raw.githubusercontent.com/asyncura/paperless-to-lexoffice/main/docker/docker-compose.env
   ```
3. Edit `docker-compose.env` and set your authentication tokens, your paperless-ngx URL and your
   lexoffice tag ID. See [Environment Variables](#environment-variables) for every setting.
4. Start the daemon from that directory:
   ```bash
   docker compose up -d
   ```
5. Check the log to confirm it reached your paperless-ngx instance:
   ```bash
   docker compose logs -f
   ```

The shipped `docker-compose.yml` mounts `./data` into the container, which is where the record of
already-uploaded documents is kept. See [Database Persistence](#database-persistence) for why that
matters.

### Option 2: A single docker run command

For a setup without separate configuration files:

```bash
docker run -d \
  --name paperless-to-lexoffice \
  --restart unless-stopped \
  -v ./data:/data \
  -e PL2LO_PAPERLESS_TOKEN="your-paperless-token-here" \
  -e PL2LO_PAPERLESS_URL="http://your-paperless-instance:8000" \
  -e PL2LO_LEXOFFICE_TAG_ID=42 \
  -e PL2LO_LEXOFFICE_TOKEN="your-lexoffice-api-token-here" \
  asyncura/paperless-to-lexoffice:latest
```

Replace the placeholder values with your own:

- `your-paperless-token-here`: your paperless-ngx authentication token
- `http://your-paperless-instance:8000`: URL of your paperless-ngx instance
- `42`: ID of your lexoffice tag in paperless-ngx
- `your-lexoffice-api-token-here`: your lexoffice API token

Keep the `-v ./data:/data` mount: without it the daemon re-uploads every tagged document after the
container is recreated.

### Option 3: Building from source

1. Clone this repository
2. Edit `docker/docker-compose.env` with your configuration
3. Build and start the image from the `docker` directory:
   ```bash
   cd docker
   docker compose -f docker-compose.build.yml up -d --build
   ```

## Database Persistence

The daemon records every document it has uploaded in a SQLite database at `/data/upload_store.db`
inside the container. It checks that record before each upload, because lexoffice does not
deduplicate: the same file posted twice becomes two vouchers.

That directory therefore has to survive the container. Both the shipped `docker-compose.yml` and the
`docker run` command above mount a host directory for it:

```yaml
services:
  daemon:
    image: asyncura/paperless-to-lexoffice:latest
    container_name: paperless-to-lexoffice
    env_file:
      - docker-compose.env
    restart: unless-stopped
    volumes:
      - ./data:/data  # persists the record of uploaded documents
```

This creates a `data` directory next to your `docker-compose.yml`. **If you remove the mount, the
record is lost whenever the container is recreated - for instance by `docker compose pull` - and
every tagged document is uploaded to lexoffice again as a duplicate voucher.**

## Environment Variables

All configuration is read from environment variables at startup. An invalid value is reported and the
daemon exits immediately rather than running in a half-configured state.

| Variable                    | Description                                                           | Default                             | Example                             |
|-----------------------------|-----------------------------------------------------------------------|-------------------------------------|-------------------------------------|
| PL2LO_PAPERLESS_TOKEN       | Authentication token for paperless-ngx                                | **required**                        | `"your-paperless-token"`            |
| PL2LO_PAPERLESS_URL         | URL of the paperless-ngx instance                                     | **required**                        | `"http://192.168.0.5:8000"`         |
| PL2LO_LEXOFFICE_TAG_ID      | ID of the lexoffice tag in paperless-ngx                              | **required**                        | `42`                                |
| PL2LO_LEXOFFICE_TOKEN       | Authentication token for lexoffice                                    | **required**                        | `"your-lexoffice-token"`            |
| PL2LO_POLLING_INTERVAL_S    | Seconds between polls; must be a positive integer                     | `60`                                | `300`                               |
| PL2LO_PAPERLESS_API_VERSION | paperless-ngx REST API version to request; empty defers to the server | `10`                                | `9`                                 |
| PL2LO_LEXOFFICE_URL         | lexoffice file upload endpoint                                        | `https://api.lexoffice.io/v1/files` | `https://api.lexoffice.io/v1/files` |
| PL2LO_LOG_LEVEL             | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`)               | `INFO`                              | `DEBUG`                             |

Example `docker-compose.env` file:

```ini
# Settings for paperless-ngx
PL2LO_PAPERLESS_TOKEN="TOKEN"                  # Enter your paperless-ngx token here
PL2LO_PAPERLESS_URL="http://192.168.0.5:8000"  # Change this to your paperless-ngx URL
PL2LO_LEXOFFICE_TAG_ID=42                      # Change this to your lexoffice tag ID

# Settings for lexoffice
# Caution: this only works with lexoffice plans that include the public API
PL2LO_LEXOFFICE_TOKEN="TOKEN"                  # Enter your lexoffice API token here

# Optional
PL2LO_POLLING_INTERVAL_S=60
PL2LO_LOG_LEVEL=INFO
```

## How It Works

1. Every `PL2LO_POLLING_INTERVAL_S` seconds the daemon asks paperless-ngx for all documents carrying
   the tag given by `PL2LO_LEXOFFICE_TAG_ID`
2. Documents already recorded as uploaded are skipped
3. Each remaining document is downloaded - the archived PDF when paperless-ngx has one, otherwise the
   original file - and posted to the lexoffice file endpoint as a voucher
4. Only after lexoffice accepts the upload is the document ID recorded, so a failed upload is retried
   on the next poll rather than lost
5. A failure on one document is logged and the poll continues with the next one

The tag is left on the document, so paperless-ngx keeps showing what has been sent to lexoffice.

## Compatibility

This tool is developed against the current paperless-ngx REST API (version 10) and reads the document
list from the paginated `results` field, which every API version provides.

A few notes if you are upgrading:

- paperless-ngx 3.0 removed REST API version 1 and now supports versions `9` and `10` only, defaulting
  to `10`. Earlier releases of this tool **silently synced nothing** against a 3.x server: they read
  document IDs from the `all` field of the list response, which API version 10 no longer returns.
- The requested API version can be changed with `PL2LO_PAPERLESS_API_VERSION`. Leave it empty to let
  paperless-ngx choose its own default version. An unsupported value makes paperless-ngx answer
  `406 Not Acceptable`; the daemon logs a warning and retries without pinning a version.
- At startup the daemon performs one authenticated request and logs the `X-Version` and
  `X-Api-Version` headers paperless-ngx reports, so you can confirm from the container log which
  server it reached:

  ```
  INFO [paperless] Connected to paperless-ngx 3.2.1 (API version 10)
  ```

## Troubleshooting

Start with `docker compose logs -f`, and set `PL2LO_LOG_LEVEL=DEBUG` for the individual document IDs.

| Symptom                                                   | Likely cause                                                                                |
|-----------------------------------------------------------|---------------------------------------------------------------------------------------------|
| `Invalid configuration: ...` and the container stops      | A required variable is missing or malformed; the message names it                           |
| `paperless-ngx rejected the API token (HTTP 401)`          | `PL2LO_PAPERLESS_TOKEN` is wrong or was regenerated                                         |
| `Error connecting to paperless-ngx, is it running?`        | `PL2LO_PAPERLESS_URL` is unreachable from inside the container - a `localhost` URL points at the container itself |
| `Found 0 matching document(s)` though documents are tagged | `PL2LO_LEXOFFICE_TAG_ID` is not the ID of the tag you are using                             |
| `Error uploading to lexoffice: HTTP 403`                   | The lexoffice plan does not include public API access, or the token lacks permission        |
| Documents are uploaded again after an update               | `/data` is not mounted to a persistent host directory, see [Database Persistence](#database-persistence) |

## Development

The source lives in `source/`:

| File                 | Purpose                                                       |
|----------------------|---------------------------------------------------------------|
| `main.py`            | Entry point: configuration, the polling loop and the sync pass |
| `paperless.py`       | paperless-ngx REST API client                                  |
| `lexoffice.py`       | lexoffice file upload client, including retries                |
| `db.py`              | SQLite record of documents already uploaded                    |
| `test_*.py`          | Unit tests                                                     |

The tests need no running paperless-ngx or lexoffice account - every HTTP call is stubbed:

```bash
pip install -r source/requirements.txt
python -m unittest discover -s source -p 'test_*.py' -v
```

Linting uses [ruff](https://docs.astral.sh/ruff/), configured in `pyproject.toml`:

```bash
pip install ruff
ruff check .
```

Both run in CI on every push and pull request, and the image is only published if they pass.

## Limitations

This tool has primarily been tested against personal document management workflows, and features and
functionality may change as development continues. Review the uploaded vouchers in lexoffice rather
than relying on the sync unattended. This project is provided with absolutely no warranty.

Feedback and contributions are very welcome!

## Special Thanks

Special thanks to the developers of paperless-ngx for creating such an excellent document management system with an
accessible API that makes it easy to develop integrations like this one.
