"""Tests for the daemon's configuration handling and synchronization pass.

Run with: python -m unittest discover -s source
"""

import asyncio
import dataclasses
import logging
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

import main
from db import UploadStore


def setUpModule() -> None:
    """Silence the daemon's expected error paths for a quiet suite."""
    logging.getLogger("main").setLevel(logging.CRITICAL)

VALID_ENV = {
    "PL2LO_PAPERLESS_TOKEN": "paperless-token",
    "PL2LO_PAPERLESS_URL": "http://paperless:8000",
    "PL2LO_LEXOFFICE_TAG_ID": "42",
    "PL2LO_LEXOFFICE_TOKEN": "lexoffice-token",
}


def _env(**overrides: str | None) -> dict[str, str]:
    """Build a complete PL2LO_* environment with the given overrides applied."""
    env = dict(VALID_ENV)
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


class ConfigTest(unittest.TestCase):
    def test_reads_a_complete_environment(self):
        with mock.patch.dict(os.environ, _env(), clear=True):
            config = main.Config.from_env()

        self.assertEqual("paperless-token", config.paperless_token)
        self.assertEqual("http://paperless:8000", config.paperless_url)
        self.assertEqual(42, config.lexoffice_tag_id)
        self.assertEqual("lexoffice-token", config.lexoffice_token)

    def test_applies_defaults_for_optional_variables(self):
        with mock.patch.dict(os.environ, _env(), clear=True):
            config = main.Config.from_env()

        self.assertEqual(main.DEFAULT_POLLING_INTERVAL_S, config.polling_interval_s)
        self.assertEqual(main.DEFAULT_LEXOFFICE_URL, config.lexoffice_url)
        self.assertEqual("10", config.paperless_api_version)

    def test_strips_trailing_slashes_from_urls(self):
        with mock.patch.dict(os.environ, _env(PL2LO_PAPERLESS_URL="http://paperless:8000///"), clear=True):
            config = main.Config.from_env()

        self.assertEqual("http://paperless:8000", config.paperless_url)

    def test_empty_api_version_defers_to_the_server(self):
        with mock.patch.dict(os.environ, _env(PL2LO_PAPERLESS_API_VERSION=""), clear=True):
            config = main.Config.from_env()

        self.assertIsNone(config.paperless_api_version)

    def test_rejects_missing_required_variable(self):
        for name in VALID_ENV:
            with self.subTest(variable=name), mock.patch.dict(os.environ, _env(**{name: None}), clear=True):
                with self.assertRaises(main.ConfigError) as ctx:
                    main.Config.from_env()
                self.assertIn(name, str(ctx.exception))

    def test_rejects_blank_required_variable(self):
        with mock.patch.dict(os.environ, _env(PL2LO_PAPERLESS_TOKEN="   "), clear=True):
            with self.assertRaises(main.ConfigError):
                main.Config.from_env()

    def test_rejects_url_without_scheme(self):
        with mock.patch.dict(os.environ, _env(PL2LO_PAPERLESS_URL="paperless:8000"), clear=True):
            with self.assertRaises(main.ConfigError) as ctx:
                main.Config.from_env()

        self.assertIn("http://", str(ctx.exception))

    def test_rejects_non_numeric_tag_id(self):
        with mock.patch.dict(os.environ, _env(PL2LO_LEXOFFICE_TAG_ID="voucher"), clear=True):
            with self.assertRaises(main.ConfigError):
                main.Config.from_env()

    def test_rejects_non_positive_polling_interval(self):
        for value in ["0", "-5"]:
            with self.subTest(value=value), mock.patch.dict(
                os.environ, _env(PL2LO_POLLING_INTERVAL_S=value), clear=True
            ):
                with self.assertRaises(main.ConfigError):
                    main.Config.from_env()

    def test_is_immutable(self):
        """The config is read once at startup and must not drift afterwards."""
        with mock.patch.dict(os.environ, _env(), clear=True):
            config = main.Config.from_env()

        with self.assertRaises(dataclasses.FrozenInstanceError):
            config.paperless_url = "http://elsewhere:8000"


class MainTest(unittest.TestCase):
    def setUp(self):
        # main() configures root logging, which would leak into the whole suite
        self.enterContext(mock.patch.object(main, "_configure_logging"))

    def test_exits_with_an_error_on_invalid_configuration(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit) as ctx:
                main.main()

        self.assertEqual(1, ctx.exception.code)

    def test_does_not_touch_the_database_before_the_config_is_valid(self):
        """An unconfigured container must fail on the config, not on /data."""
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(main, "UploadStore") as store:
            with self.assertRaises(SystemExit):
                main.main()

        store.assert_not_called()


class SyncTest(unittest.TestCase):
    def setUp(self):
        with mock.patch.dict(os.environ, _env(), clear=True):
            self.config = main.Config.from_env()
        self.store = mock.Mock(spec=UploadStore)
        self.store.is_uploaded.return_value = False

    def _run(self):
        asyncio.run(main.sync_paperless_to_lexoffice(self.config, self.store))

    def test_uploads_each_new_document_and_records_it(self):
        with mock.patch.object(main.paperless, "filter_documents_by_tags", return_value=[1, 2]), \
             mock.patch.object(main.paperless, "download_document", return_value=b"%PDF"), \
             mock.patch.object(main.lexoffice, "upload_voucher") as upload:
            self._run()

        self.assertEqual([1, 2], [call.args[3] for call in upload.call_args_list])
        self.assertEqual([mock.call(1), mock.call(2)], self.store.mark_as_uploaded.call_args_list)

    def test_skips_documents_already_uploaded(self):
        self.store.is_uploaded.side_effect = lambda doc_id: doc_id == 1

        with mock.patch.object(main.paperless, "filter_documents_by_tags", return_value=[1, 2]), \
             mock.patch.object(main.paperless, "download_document", return_value=b"%PDF"), \
             mock.patch.object(main.lexoffice, "upload_voucher") as upload:
            self._run()

        self.assertEqual([2], [call.args[3] for call in upload.call_args_list])

    def test_does_nothing_when_the_lookup_failed(self):
        with mock.patch.object(main.paperless, "filter_documents_by_tags", return_value=None), \
             mock.patch.object(main.paperless, "download_document") as download:
            self._run()

        download.assert_not_called()

    def test_does_not_record_a_document_whose_upload_failed(self):
        """A failed upload must stay unrecorded so the next pass retries it."""
        with mock.patch.object(main.paperless, "filter_documents_by_tags", return_value=[1]), \
             mock.patch.object(main.paperless, "download_document", return_value=b"%PDF"), \
             mock.patch.object(main.lexoffice, "upload_voucher", side_effect=RuntimeError("boom")):
            self._run()

        self.store.mark_as_uploaded.assert_not_called()

    def test_one_failed_upload_does_not_stop_the_pass(self):
        with mock.patch.object(main.paperless, "filter_documents_by_tags", return_value=[1, 2]), \
             mock.patch.object(main.paperless, "download_document", return_value=b"%PDF"), \
             mock.patch.object(main.lexoffice, "upload_voucher", side_effect=[RuntimeError("boom"), None]):
            self._run()

        self.store.mark_as_uploaded.assert_called_once_with(2)

    def test_does_not_upload_a_document_that_failed_to_download(self):
        with mock.patch.object(main.paperless, "filter_documents_by_tags", return_value=[1]), \
             mock.patch.object(main.paperless, "download_document", return_value=None), \
             mock.patch.object(main.lexoffice, "upload_voucher") as upload:
            self._run()

        upload.assert_not_called()
        self.store.mark_as_uploaded.assert_not_called()


class RunPeriodicallyTest(unittest.TestCase):
    def test_keeps_polling_after_an_unexpected_error(self):
        with mock.patch.dict(os.environ, _env(PL2LO_POLLING_INTERVAL_S="1"), clear=True):
            config = main.Config.from_env()

        passes = []

        async def pass_then_stop(_config, _store):
            passes.append(1)
            if len(passes) == 1:
                raise RuntimeError("boom")
            raise asyncio.CancelledError

        with mock.patch.object(main, "sync_paperless_to_lexoffice", pass_then_stop), \
             mock.patch.object(main.asyncio, "sleep", new=mock.AsyncMock()):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(main.run_periodically(config, mock.Mock()))

        self.assertEqual(2, len(passes))


class UploadStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = UploadStore(os.path.join(self.tmp.name, "nested", "upload_store.db"))

    def test_records_and_recognizes_a_document(self):
        self.assertFalse(self.store.is_uploaded(7))
        self.store.mark_as_uploaded(7)
        self.assertTrue(self.store.is_uploaded(7))

    def test_recording_twice_is_not_an_error(self):
        """A retry that races an earlier success must not break the sync loop."""
        self.store.mark_as_uploaded(7)
        self.store.mark_as_uploaded(7)
        self.assertTrue(self.store.is_uploaded(7))

    def test_treats_int_and_str_ids_as_the_same_document(self):
        self.store.mark_as_uploaded(7)
        self.assertTrue(self.store.is_uploaded("7"))

    def test_survives_reopening_the_same_file(self):
        self.store.mark_as_uploaded(7)
        self.assertTrue(UploadStore(self.store.db_path).is_uploaded(7))

    def test_creates_missing_parent_directories(self):
        self.assertTrue(os.path.isfile(self.store.db_path))

    def test_stores_an_upload_timestamp(self):
        self.store.mark_as_uploaded(7)
        conn = sqlite3.connect(self.store.db_path)
        try:
            timestamp = conn.execute(
                "SELECT upload_timestamp FROM uploaded_docs WHERE doc_id = '7'"
            ).fetchone()[0]
        finally:
            conn.close()

        self.assertIsNotNone(timestamp)


if __name__ == "__main__":
    unittest.main()
