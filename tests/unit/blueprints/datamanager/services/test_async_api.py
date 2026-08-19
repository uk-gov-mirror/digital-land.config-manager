from unittest.mock import patch, Mock

import pytest

from application.blueprints.datamanager.services.async_api import (
    fetch_response_details,
    AsyncAPIError,
    fetch_request,
    submit_request,
)


class TestSubmitRequest:
    def test_returns_request_id_on_202(self):
        mock_response = Mock()
        mock_response.status_code = 202
        mock_response.json.return_value = {"id": "abc123"}
        with patch(
            "application.blueprints.datamanager.services.async_api.requests.post",
            return_value=mock_response,
        ):
            result = submit_request(
                {"type": "check_url", "url": "https://example.com/data.csv"}
            )
        assert result == "abc123"

    def test_raises_on_non_202(self):
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.json.return_value = {"error": "server error"}
        with patch(
            "application.blueprints.datamanager.services.async_api.requests.post",
            return_value=mock_response,
        ):
            with pytest.raises(AsyncAPIError):
                submit_request({"type": "check_url"})

    def test_raises_on_request_exception(self):
        with patch(
            "application.blueprints.datamanager.services.async_api.requests.post",
            side_effect=Exception("timeout"),
        ):
            with pytest.raises(Exception):
                submit_request({"type": "check_url"})


class TestFetchRequest:
    def test_returns_json_on_200(self):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "abc123", "status": "COMPLETE"}
        with patch(
            "application.blueprints.datamanager.services.async_api.requests.get",
            return_value=mock_response,
        ):
            result = fetch_request("abc123")
        assert result["id"] == "abc123"
        assert result["status"] == "COMPLETE"

    def test_raises_on_404(self):
        mock_response = Mock()
        mock_response.status_code = 404
        with patch(
            "application.blueprints.datamanager.services.async_api.requests.get",
            return_value=mock_response,
        ):
            with pytest.raises(AsyncAPIError):
                fetch_request("nonexistent-id")

    def test_raises_on_400(self):
        mock_response = Mock()
        mock_response.status_code = 400
        with patch(
            "application.blueprints.datamanager.services.async_api.requests.get",
            return_value=mock_response,
        ):
            with pytest.raises(AsyncAPIError):
                fetch_request("bad-id")


def _rows(start, count):
    """Identifiable rows so ordering can be asserted."""
    return [
        {"entry_number": n, "converted_row": {}} for n in range(start, start + count)
    ]


def _page_response(payload, total=None):
    response = Mock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    response.headers = (
        {} if total is None else {"X-Pagination-Total-Results": str(total)}
    )
    return response


class TestFetchResponseDetails:
    """
    The first page carries the row total in a header, so the remaining pages are
    fetched in parallel. Row order matters: the controller slices the returned list
    by index to paginate the transform tables.
    """

    def _patch_first_page(self, response):
        session = Mock()
        session.get.return_value = response
        return patch(
            "application.blueprints.datamanager.services.async_api.get_http_session",
            return_value=session,
        )

    def test_fetches_remaining_pages_in_parallel_and_keeps_offset_order(self, app):
        with self._patch_first_page(_page_response(_rows(0, 500), total=1200)), patch(
            "application.blueprints.datamanager.services.async_api.fetch_pages_concurrently",
            return_value=[_rows(500, 500), _rows(1000, 200)],
        ) as fetch_pages:
            result = fetch_response_details("parallel-order")

        assert len(result) == 1200
        assert [row["entry_number"] for row in result] == list(range(1200))
        urls = fetch_pages.call_args[0][0]
        assert [u.split("offset=")[1].split("&")[0] for u in urls] == ["500", "1000"]

    def test_single_page_needs_no_parallel_fetch(self, app):
        with self._patch_first_page(_page_response(_rows(0, 12), total=12)), patch(
            "application.blueprints.datamanager.services.async_api.fetch_pages_concurrently"
        ) as fetch_pages:
            result = fetch_response_details("single-page")

        assert len(result) == 12
        fetch_pages.assert_not_called()

    def test_max_rows_clamps_the_result(self, app):
        with self._patch_first_page(_page_response(_rows(0, 500), total=5000)), patch(
            "application.blueprints.datamanager.services.async_api.fetch_pages_concurrently",
            return_value=[_rows(500, 500)],
        ):
            result = fetch_response_details("clamped", max_rows=750)

        assert len(result) == 750
        assert [row["entry_number"] for row in result] == list(range(750))

    def test_falls_back_to_sequential_when_header_missing(self, app):
        with self._patch_first_page(_page_response(_rows(0, 500))), patch(
            "application.blueprints.datamanager.services.async_api._fetch_response_details_sequentially",
            return_value=_rows(0, 900),
        ) as sequential:
            result = fetch_response_details("no-header")

        assert len(result) == 900
        sequential.assert_called_once()

    def test_failed_page_is_skipped_without_reordering_the_rest(self, app, caplog):
        with self._patch_first_page(_page_response(_rows(0, 500), total=1500)), patch(
            "application.blueprints.datamanager.services.async_api.fetch_pages_concurrently",
            return_value=[None, _rows(1000, 500)],
        ):
            result = fetch_response_details("holed")

        assert [row["entry_number"] for row in result] == (
            list(range(500)) + list(range(1000, 1500))
        )
        assert "offset 500 failed" in caplog.text

    def test_returns_empty_when_the_first_page_fails(self, app):
        session = Mock()
        session.get.side_effect = Exception("connection reset")
        with patch(
            "application.blueprints.datamanager.services.async_api.get_http_session",
            return_value=session,
        ):
            assert fetch_response_details("first-page-fails") == []
