from unittest.mock import MagicMock, patch

import pytest

import application.blueprints.datamanager.services.issue_type as issue_type_module
from application.blueprints.datamanager.services.issue_type import (
    get_quality_criteria_levels,
)


@pytest.fixture(autouse=True)
def clear_cache():
    """Reset the module-level cache between tests."""
    issue_type_module._cache["data"] = None
    issue_type_module._cache["expires_at"] = 0
    yield
    issue_type_module._cache["data"] = None
    issue_type_module._cache["expires_at"] = 0


def _make_response(rows, next_url=None):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"rows": rows, "next_url": next_url}
    return mock_resp


ISSUE_TYPE_ROWS = [
    {"issue_type": "invalid geometry", "quality_criteria_level": 2},
    {"issue_type": "invalid date", "quality_criteria_level": "3"},
    {"issue_type": "combined-value", "quality_criteria_level": None},
    {"issue_type": "unknown format", "quality_criteria_level": ""},
    {"issue_type": "", "quality_criteria_level": 2},
]


class TestGetQualityCriteriaLevels:
    def test_maps_issue_type_to_int_level(self, app):
        with app.app_context():
            with patch(
                "application.blueprints.datamanager.services.issue_type.requests.get",
                return_value=_make_response(ISSUE_TYPE_ROWS),
            ):
                levels = get_quality_criteria_levels()

        assert levels == {"invalid geometry": 2, "invalid date": 3}

    def test_follows_pagination(self, app):
        page_one = _make_response(
            [{"issue_type": "invalid geometry", "quality_criteria_level": 2}],
            next_url="/digital-land/issue_type.json?_next=1",
        )
        page_two = _make_response(
            [{"issue_type": "invalid date", "quality_criteria_level": 3}]
        )
        with app.app_context():
            with patch(
                "application.blueprints.datamanager.services.issue_type.requests.get",
                side_effect=[page_one, page_two],
            ) as mock_get:
                levels = get_quality_criteria_levels()

        assert mock_get.call_count == 2
        assert levels == {"invalid geometry": 2, "invalid date": 3}

    def test_caches_between_calls(self, app):
        with app.app_context():
            with patch(
                "application.blueprints.datamanager.services.issue_type.requests.get",
                return_value=_make_response(ISSUE_TYPE_ROWS),
            ) as mock_get:
                get_quality_criteria_levels()
                get_quality_criteria_levels()

        assert mock_get.call_count == 1

    def test_returns_stale_cache_on_fetch_failure(self, app):
        with app.app_context():
            with patch(
                "application.blueprints.datamanager.services.issue_type.requests.get",
                return_value=_make_response(ISSUE_TYPE_ROWS),
            ):
                get_quality_criteria_levels()

            issue_type_module._cache["expires_at"] = 0

            with patch(
                "application.blueprints.datamanager.services.issue_type.requests.get",
                side_effect=Exception("datasette down"),
            ):
                levels = get_quality_criteria_levels()

        assert levels == {"invalid geometry": 2, "invalid date": 3}

    def test_raises_when_fetch_fails_with_no_cache(self, app):
        with app.app_context():
            with patch(
                "application.blueprints.datamanager.services.issue_type.requests.get",
                side_effect=Exception("datasette down"),
            ):
                with pytest.raises(Exception, match="datasette down"):
                    get_quality_criteria_levels()
