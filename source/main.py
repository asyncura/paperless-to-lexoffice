"""Daemon that syncs tagged paperless-ngx documents to lexoffice as vouchers.

Polls paperless-ngx for documents carrying the configured tag, downloads each
one that has not been uploaded before and posts it to the lexoffice voucher
endpoint. Uploaded document IDs are recorded in a local SQLite store so a
document is never uploaded twice.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass

import lexoffice
import paperless
from db import UploadStore

logger = logging.getLogger(__name__)

DEFAULT_POLLING_INTERVAL_S = 60
DEFAULT_LEXOFFICE_URL = "https://api.lexoffice.io/v1/files"


class ConfigError(ValueError):
    """Raised when the environment does not describe a usable configuration."""


@dataclass(frozen=True)
class Config:
    """Runtime configuration, read from environment variables."""

    paperless_token: str
    paperless_url: str
    paperless_api_version: str | None
    lexoffice_tag_id: int
    lexoffice_token: str
    lexoffice_url: str
    polling_interval_s: int

    @classmethod
    def from_env(cls) -> Config:
        """
        Build a configuration from the PL2LO_* environment variables.

        Returns:
            The validated configuration.

        Raises:
            ConfigError: If a required variable is missing or a value is invalid.
        """
        return cls(
            paperless_token=_env("PL2LO_PAPERLESS_TOKEN"),
            paperless_url=_http_url("PL2LO_PAPERLESS_URL"),
            paperless_api_version=_api_version("PL2LO_PAPERLESS_API_VERSION"),
            lexoffice_tag_id=_positive_int("PL2LO_LEXOFFICE_TAG_ID"),
            lexoffice_token=_env("PL2LO_LEXOFFICE_TOKEN"),
            lexoffice_url=_http_url("PL2LO_LEXOFFICE_URL", default=DEFAULT_LEXOFFICE_URL),
            polling_interval_s=_positive_int(
                "PL2LO_POLLING_INTERVAL_S", default=DEFAULT_POLLING_INTERVAL_S
            ),
        )


def _env(name: str, default: str | None = None) -> str:
    """
    Read an environment variable, falling back to a default.

    Args:
        name: Name of the environment variable.
        default: Value to use when the variable is unset or empty, or None to
            make the variable required.

    Returns:
        The variable's value, stripped of surrounding whitespace.

    Raises:
        ConfigError: If the variable is unset or empty and has no default.
    """
    value = (os.getenv(name) or "").strip()
    if value:
        return value
    if default is None:
        raise ConfigError(f"Missing required environment variable: {name}")
    return default


def _positive_int(name: str, default: int | None = None) -> int:
    """
    Read an environment variable that must hold a positive integer.

    Args:
        name: Name of the environment variable.
        default: Value to use when the variable is unset, or None to make the
            variable required.

    Returns:
        The parsed integer.

    Raises:
        ConfigError: If the value is not a positive integer.
    """
    raw = _env(name, None if default is None else str(default))
    try:
        value = int(raw)
    except ValueError as e:
        raise ConfigError(f"{name} must be a positive integer, got {raw!r}") from e
    if value <= 0:
        raise ConfigError(f"{name} must be a positive integer, got {raw!r}")
    return value


def _http_url(name: str, default: str | None = None) -> str:
    """
    Read an environment variable that must hold an HTTP(S) URL.

    Args:
        name: Name of the environment variable.
        default: Value to use when the variable is unset, or None to make the
            variable required.

    Returns:
        The URL without trailing slashes, which would otherwise produce
        request paths like "//api/documents/".

    Raises:
        ConfigError: If the value is not an http:// or https:// URL.
    """
    url = _env(name, default)
    if not url.startswith(("http://", "https://")):
        raise ConfigError(f"{name} must start with http:// or https://, got {url!r}")
    return url.rstrip("/")


def _api_version(name: str) -> str | None:
    """
    Read the paperless-ngx API version to request.

    Args:
        name: Name of the environment variable.

    Returns:
        The version to pin, or None if it was set to an empty value, which
        lets paperless-ngx fall back to its own default version.
    """
    if name in os.environ and not os.environ[name].strip():
        return None
    return _env(name, paperless.DEFAULT_API_VERSION)


async def sync_paperless_to_lexoffice(config: Config, store: UploadStore) -> None:
    """
    Run one synchronization pass from paperless-ngx to lexoffice.

    Retrieves the documents tagged for upload, then downloads and uploads each
    one that the store does not already know about. Individual failures are
    logged and left for the next pass; they never abort the pass.

    Args:
        config: Runtime configuration.
        store: Store of document IDs already uploaded to lexoffice.
    """
    logger.info("Check for new documents in paperless-ngx tagged for upload...")
    document_ids = paperless.filter_documents_by_tags(
        config.paperless_token,
        config.paperless_url,
        [config.lexoffice_tag_id],
        api_version=config.paperless_api_version,
    )

    # None rather than an empty list means the lookup itself failed
    if document_ids is None:
        return

    for document_id in document_ids:
        if store.is_uploaded(document_id):
            continue

        file_content = paperless.download_document(
            config.paperless_token,
            config.paperless_url,
            document_id,
            api_version=config.paperless_api_version,
        )
        if file_content is None:
            logger.error(f"Failed to download document {document_id}")
            continue

        try:
            lexoffice.upload_voucher(
                config.lexoffice_token, config.lexoffice_url, file_content, document_id
            )
        except Exception as e:
            logger.error(f"Upload failed for document {document_id}. Trying again later. Error: {e}")
            continue

        store.mark_as_uploaded(document_id)
        logger.info(f"Document {document_id} uploaded successfully.")


async def run_periodically(config: Config, store: UploadStore) -> None:
    """
    Synchronize repeatedly, waiting between passes, until cancelled.

    An unexpected error in a pass is logged and the loop continues, so a
    transient failure cannot take the daemon down.

    Args:
        config: Runtime configuration.
        store: Store of document IDs already uploaded to lexoffice.
    """
    while True:
        try:
            await sync_paperless_to_lexoffice(config, store)
        except Exception as e:
            logger.exception(f"Synchronization pass failed: {e}")
        await asyncio.sleep(config.polling_interval_s)


def _configure_logging() -> None:
    """Set up logging, with the level taken from PL2LO_LOG_LEVEL (default INFO)."""
    level_name = os.getenv("PL2LO_LOG_LEVEL", "INFO").strip().upper()
    level = logging.getLevelNamesMapping().get(level_name, logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")


def main() -> None:
    """
    Entry point: load the configuration and poll until interrupted.

    Raises:
        SystemExit: If the configuration is invalid.
    """
    _configure_logging()

    try:
        config = Config.from_env()
    except ConfigError as e:
        logger.error(f"Invalid configuration: {e}")
        raise SystemExit(1) from e

    logger.info(
        f"Starting paperless-to-lexoffice with polling interval {config.polling_interval_s}s"
    )

    # Log which paperless-ngx the daemon reached, so an incompatible server
    # shows up at startup instead of as an endless run that syncs nothing. A
    # failed probe is not fatal: paperless-ngx may still be booting.
    paperless.check_compatibility(
        config.paperless_token, config.paperless_url, api_version=config.paperless_api_version
    )

    store = UploadStore()

    try:
        asyncio.run(run_periodically(config, store))
    except KeyboardInterrupt:
        logger.info("Interrupted, shutting down.")


if __name__ == "__main__":
    main()
