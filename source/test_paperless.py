"""Tests for the paperless-ngx API client.

Run with: python -m unittest discover -s source
"""

import logging
import unittest
from unittest import mock

import requests

import paperless


def setUpModule() -> None:
    """Silence the client's expected warning and error paths for a quiet suite."""
    logging.getLogger("paperless").setLevel(logging.CRITICAL)


def _response(status_code=200, json_body=None, headers=None):
    """Build a stub requests.Response-alike."""
    response = mock.Mock(spec=requests.Response)
    response.status_code = status_code
    response.headers = headers or {}
    if json_body is None:
        response.json.side_effect = ValueError("no json")
    else:
        response.json.return_value = json_body
    return response


def _page(results, next_page=None, count=None):
    """Build an API version 10 shaped page (note: no `all` field)."""
    return {
        "count": count if count is not None else len(results),
        "next": next_page,
        "previous": None,
        "results": [{"id": _id, "title": f"doc {_id}"} for _id in results],
    }


class FilterDocumentsByTagsTest(unittest.TestCase):
    def test_collects_ids_across_pages_without_all_field(self):
        """API v10 drops the `all` field, so IDs come from paginated `results`."""
        first = _page(list(range(1, 26)), next_page="http://internal:8000/api/documents/?page=2", count=30)
        second = _page(list(range(26, 31)), next_page=None, count=30)

        with mock.patch.object(paperless.requests, "request") as request:
            request.side_effect = [_response(json_body=first), _response(json_body=second)]
            ids = paperless.filter_documents_by_tags("token", "http://paperless:8000", [42])

        self.assertEqual(list(range(1, 31)), ids)
        self.assertEqual(2, request.call_count)

    def test_ignores_legacy_all_field(self):
        """A v9 server still sends `all`; results must remain the source of truth."""
        body = _page([7, 8], next_page=None, count=2)
        body["all"] = [7, 8, 9, 10]

        with mock.patch.object(paperless.requests, "request") as request:
            request.return_value = _response(json_body=body)
            ids = paperless.filter_documents_by_tags("token", "http://paperless:8000", [42])

        self.assertEqual([7, 8], ids)

    def test_requests_pages_against_configured_base_url(self):
        """The server's `next` link may name an unreachable host, so it is not followed."""
        first = _page([1], next_page="http://internal:8000/api/documents/?page=2", count=2)
        second = _page([2], next_page=None, count=2)

        with mock.patch.object(paperless.requests, "request") as request:
            request.side_effect = [_response(json_body=first), _response(json_body=second)]
            paperless.filter_documents_by_tags("token", "http://paperless:8000", [42])

        for call in request.call_args_list:
            self.assertEqual("http://paperless:8000/api/documents/", call.args[1])
        self.assertEqual(2, request.call_args_list[1].kwargs["params"]["page"])

    def test_pins_api_version_in_accept_header(self):
        with mock.patch.object(paperless.requests, "request") as request:
            request.return_value = _response(json_body=_page([1]))
            paperless.filter_documents_by_tags("token", "http://paperless:8000", [42])

        headers = request.call_args.kwargs["headers"]
        self.assertEqual("application/json; version=10", headers["Accept"])
        self.assertEqual("Token token", headers["Authorization"])

    def test_pages_by_unique_id_for_stable_pagination(self):
        """`created` is only day-precise, so paging by it can skip documents."""
        with mock.patch.object(paperless.requests, "request") as request:
            request.return_value = _response(json_body=_page([1]))
            paperless.filter_documents_by_tags("token", "http://paperless:8000", [42])

        self.assertEqual("id", request.call_args.kwargs["params"]["ordering"])

    def test_sends_tags_filter(self):
        with mock.patch.object(paperless.requests, "request") as request:
            request.return_value = _response(json_body=_page([1]))
            paperless.filter_documents_by_tags("token", "http://paperless:8000", [42, 43])

        self.assertEqual("42,43", request.call_args.kwargs["params"]["tags__id__all"])

    def test_retries_unpinned_when_server_rejects_version(self):
        """An older paperless-ngx answers an unknown Accept version with HTTP 406."""
        with mock.patch.object(paperless.requests, "request") as request:
            request.side_effect = [
                _response(status_code=406),
                _response(json_body=_page([5])),
            ]
            ids = paperless.filter_documents_by_tags("token", "http://paperless:8000", [42])

        self.assertEqual([5], ids)
        self.assertEqual("application/json", request.call_args_list[1].kwargs["headers"]["Accept"])

    def test_returns_none_on_http_error(self):
        with mock.patch.object(paperless.requests, "request") as request:
            request.return_value = _response(status_code=500)
            self.assertIsNone(paperless.filter_documents_by_tags("token", "http://paperless:8000", [42]))

    def test_returns_none_on_connection_error(self):
        with mock.patch.object(paperless.requests, "request") as request:
            request.side_effect = requests.ConnectionError("refused")
            self.assertIsNone(paperless.filter_documents_by_tags("token", "http://paperless:8000", [42]))

    def test_stops_when_next_is_advertised_but_count_is_reached(self):
        """Guard against looping forever on a server that always sets `next`."""
        body = _page([1], next_page="http://internal:8000/api/documents/?page=2", count=1)

        with mock.patch.object(paperless.requests, "request") as request:
            request.return_value = _response(json_body=body)
            ids = paperless.filter_documents_by_tags("token", "http://paperless:8000", [42])

        self.assertEqual([1], ids)
        self.assertEqual(1, request.call_count)


class SearchDocumentsTest(unittest.TestCase):
    def test_wraps_query_and_paginates(self):
        first = _page([1, 2], next_page="http://internal:8000/api/documents/?page=2", count=3)
        second = _page([3], next_page=None, count=3)

        with mock.patch.object(paperless.requests, "request") as request:
            request.side_effect = [_response(json_body=first), _response(json_body=second)]
            ids = paperless.search_documents("token", "http://paperless:8000", "invoice")

        self.assertEqual([1, 2, 3], ids)
        self.assertEqual("(invoice)", request.call_args_list[0].kwargs["params"]["query"])

    def test_does_not_override_relevance_ranking(self):
        """A full text query is ranked by relevance; forcing an ordering flattens it."""
        with mock.patch.object(paperless.requests, "request") as request:
            request.return_value = _response(json_body=_page([1]))
            paperless.search_documents("token", "http://paperless:8000", "invoice")

        self.assertNotIn("ordering", request.call_args.kwargs["params"])


class DownloadDocumentTest(unittest.TestCase):
    def test_returns_binary_content(self):
        response = _response()
        response.iter_content.return_value = [b"%PDF-1.7", b"payload"]

        with mock.patch.object(paperless.requests, "request") as request:
            request.return_value = response
            content = paperless.download_document("token", "http://paperless:8000", 9)

        self.assertEqual(b"%PDF-1.7payload", content)
        self.assertEqual("http://paperless:8000/api/documents/9/download/", request.call_args.args[1])

    def test_returns_none_on_http_error(self):
        with mock.patch.object(paperless.requests, "request") as request:
            request.return_value = _response(status_code=404)
            self.assertIsNone(paperless.download_document("token", "http://paperless:8000", 9))


class CheckCompatibilityTest(unittest.TestCase):
    def test_reports_versions_from_response_headers(self):
        headers = {"X-Api-Version": "10", "X-Version": "3.2.1"}

        with mock.patch.object(paperless.requests, "request") as request:
            request.return_value = _response(json_body=_page([]), headers=headers)
            api_version, server_version = paperless.check_compatibility("token", "http://paperless:8000")

        self.assertEqual(("10", "3.2.1"), (api_version, server_version))

    def test_returns_none_on_rejected_token(self):
        with mock.patch.object(paperless.requests, "request") as request:
            request.return_value = _response(status_code=401)
            self.assertEqual((None, None), paperless.check_compatibility("token", "http://paperless:8000"))


class BulkEditTest(unittest.TestCase):
    def test_remove_tag_uses_bulk_edit_endpoint(self):
        with mock.patch.object(paperless.requests, "request") as request:
            request.return_value = _response(json_body={})
            self.assertTrue(paperless.remove_tag("token", "http://paperless:8000", 5, [42]))

        self.assertEqual("POST", request.call_args.args[0])
        self.assertEqual("http://paperless:8000/api/documents/bulk_edit/", request.call_args.args[1])

        import json
        payload = json.loads(request.call_args.kwargs["data"])
        self.assertEqual([5], payload["documents"])
        self.assertEqual("modify_tags", payload["method"])
        self.assertEqual({"add_tags": [], "remove_tags": [42]}, payload["parameters"])

    def test_set_custom_field_adds_without_replacing_others(self):
        with mock.patch.object(paperless.requests, "request") as request:
            request.return_value = _response(json_body={})
            self.assertTrue(paperless.set_custom_field("token", "http://paperless:8000", 5, 3, "LX-1"))

        import json
        payload = json.loads(request.call_args.kwargs["data"])
        self.assertEqual("modify_custom_fields", payload["method"])
        self.assertEqual({"3": "LX-1"}, payload["parameters"]["add_custom_fields"])
        self.assertEqual([], payload["parameters"]["remove_custom_fields"])


if __name__ == "__main__":
    unittest.main()
