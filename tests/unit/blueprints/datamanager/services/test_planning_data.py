from unittest.mock import MagicMock, patch

import pytest

from application.blueprints.datamanager.services.planning_data import (
    ENTITY_PAGE_SIZE,
    PlatformEntitiesIncomplete,
    get_entities_for_organisation_and_dataset,
    get_entity_count_for_organisation_and_dataset,
)

PLANNING_DATA_MODULE = "application.blueprints.datamanager.services.planning_data"


def _entities(start, count):
    return [{"entity": n, "reference": f"ref-{n}"} for n in range(start, start + count)]


def _entities_response(entities, next_url=None):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "entities": entities,
        "links": {"next": next_url} if next_url else {},
    }
    return resp


class TestGetEntityCount:
    def test_returns_count_on_success(self, app):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"count": 4200}
        with app.app_context():
            with patch(f"{PLANNING_DATA_MODULE}.requests.get", return_value=resp):
                assert get_entity_count_for_organisation_and_dataset(1, "tree") == 4200

    def test_returns_none_when_the_call_fails(self, app):
        # Must not be 0 — the count drives which offsets get fetched, so a failure
        # that looks like a genuine zero would report every entity as new.
        with app.app_context():
            with patch(
                f"{PLANNING_DATA_MODULE}.requests.get", side_effect=Exception("boom")
            ):
                assert get_entity_count_for_organisation_and_dataset(1, "tree") is None


class TestGetEntitiesForOrganisationAndDataset:
    def test_fetches_every_page_in_parallel_when_total_is_known(self, app):
        pages = [
            {"entities": _entities(0, ENTITY_PAGE_SIZE)},
            {"entities": _entities(ENTITY_PAGE_SIZE, 120)},
        ]
        with app.app_context():
            with patch(
                f"{PLANNING_DATA_MODULE}.fetch_pages_concurrently", return_value=pages
            ) as fetch_pages:
                result = get_entities_for_organisation_and_dataset(
                    11, "parallel-dataset", total=ENTITY_PAGE_SIZE + 120
                )

        assert len(result) == ENTITY_PAGE_SIZE + 120
        assert [e["entity"] for e in result] == list(range(ENTITY_PAGE_SIZE + 120))
        urls = fetch_pages.call_args[0][0]
        assert [u.split("offset=")[1] for u in urls] == ["0", str(ENTITY_PAGE_SIZE)]

    def test_failed_page_raises_rather_than_returning_a_partial_list(self, app):
        # A partial list would report the missing platform entities as new.
        pages = [{"entities": _entities(0, ENTITY_PAGE_SIZE)}, None]
        with app.app_context():
            with patch(
                f"{PLANNING_DATA_MODULE}.fetch_pages_concurrently", return_value=pages
            ):
                with pytest.raises(PlatformEntitiesIncomplete):
                    get_entities_for_organisation_and_dataset(
                        12, "holed-dataset", total=ENTITY_PAGE_SIZE + 10
                    )

    def test_partial_result_is_not_cached_so_the_next_call_retries(self, app):
        failing = [{"entities": _entities(0, ENTITY_PAGE_SIZE)}, None]
        whole = [
            {"entities": _entities(0, ENTITY_PAGE_SIZE)},
            {"entities": _entities(ENTITY_PAGE_SIZE, 10)},
        ]
        total = ENTITY_PAGE_SIZE + 10
        with app.app_context():
            with patch(
                f"{PLANNING_DATA_MODULE}.fetch_pages_concurrently", return_value=failing
            ):
                with pytest.raises(PlatformEntitiesIncomplete):
                    get_entities_for_organisation_and_dataset(15, "flaky", total=total)

            # Same memoize key: the failure must not have poisoned the cache.
            with patch(
                f"{PLANNING_DATA_MODULE}.fetch_pages_concurrently", return_value=whole
            ):
                result = get_entities_for_organisation_and_dataset(
                    15, "flaky", total=total
                )

        assert len(result) == total

    def test_sequential_paging_raises_when_a_page_fails(self, app):
        responses = [
            _entities_response(
                _entities(0, ENTITY_PAGE_SIZE), next_url="/entity.json?p=2"
            ),
            Exception("connection reset"),
        ]
        with app.app_context():
            with patch(f"{PLANNING_DATA_MODULE}.requests.get", side_effect=responses):
                with pytest.raises(PlatformEntitiesIncomplete):
                    get_entities_for_organisation_and_dataset(
                        16, "sequential-holed", total=None
                    )

    def test_zero_total_fetches_nothing(self, app):
        with app.app_context():
            with patch(
                f"{PLANNING_DATA_MODULE}.fetch_pages_concurrently", return_value=[]
            ) as fetch_pages:
                result = get_entities_for_organisation_and_dataset(
                    13, "empty-dataset", total=0
                )

        assert result == []
        assert fetch_pages.call_args[0][0] == []

    def test_falls_back_to_sequential_paging_when_total_is_unknown(self, app):
        responses = [
            _entities_response(
                _entities(0, ENTITY_PAGE_SIZE), next_url="/entity.json?p=2"
            ),
            _entities_response(_entities(ENTITY_PAGE_SIZE, 30)),
        ]
        with app.app_context():
            with patch(
                f"{PLANNING_DATA_MODULE}.requests.get", side_effect=responses
            ) as mock_get:
                result = get_entities_for_organisation_and_dataset(
                    14, "sequential-dataset", total=None
                )

        assert len(result) == ENTITY_PAGE_SIZE + 30
        assert mock_get.call_count == 2
