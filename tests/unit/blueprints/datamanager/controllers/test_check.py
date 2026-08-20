import json
from unittest.mock import patch

from application.blueprints.datamanager.controllers.check import (
    _issue_tasks,
    _missing_column_tasks,
)
from application.blueprints.datamanager.services.async_api import (
    ResponseDetailsIncomplete,
)

PENDING_RESULT = {
    "status": "PENDING",
    "response": None,
    "params": {
        "organisationName": "local-authority-eng:ABC",
        "dataset": "brownfield-land",
    },
}


class TestCheckResultsRoute:
    def test_renders_loading_template_when_pending(self, client):
        with patch(
            "application.blueprints.datamanager.router.fetch_request",
            return_value=PENDING_RESULT,
        ):
            with patch(
                "application.blueprints.datamanager.controllers.check.get_organisation_name",
                return_value="Test Org",
            ):
                with patch(
                    "application.blueprints.datamanager.controllers.check.get_dataset_name",
                    return_value="Brownfield Land",
                ):
                    response = client.get("/datamanager/check-results/test-id")
        assert response.status_code == 200
        assert b"loading" in response.data.lower() or b"check" in response.data.lower()

    def test_returns_error_when_org_code_missing(self, client):
        result_no_org = {**PENDING_RESULT, "params": {}}
        with patch(
            "application.blueprints.datamanager.router.fetch_request",
            return_value=result_no_org,
        ):
            response = client.get("/datamanager/check-results/test-id")
        assert response.status_code == 200
        assert b"govuk-error-summary" in response.data

    def test_resubmit_redirects_to_new_check(self, client):
        result = {
            **PENDING_RESULT,
            "params": {
                **PENDING_RESULT["params"],
                "column_mapping": {"OldColumn": "name"},
            },
        }
        with patch(
            "application.blueprints.datamanager.controllers.check.fetch_request",
            return_value=result,
        ), patch(
            "application.blueprints.datamanager.controllers.check.submit_request",
            return_value="new-check-id",
        ) as submit_request:
            response = client.post(
                "/datamanager/check-results/test-id",
                data={"field_map[name]": "MyColumn"},
            )
        assert response.status_code == 302
        assert "new-check-id" in response.headers["Location"]
        submitted_params = submit_request.call_args.args[0]
        assert submitted_params["column_mapping"] == {"MyColumn": "name"}


def _issue_task(issue_type, field, count=1, summary="", responsibility="external"):
    return {
        "task-source": "issue",
        "responsibility": responsibility,
        "severity": "error",
        "summary": summary,
        "details": json.dumps(
            {"issue_type": issue_type, "field": field, "count": count}
        ),
    }


def _column_field_task(field, summary=""):
    return {
        "task-source": "column-field",
        "responsibility": "external",
        "severity": "error",
        "summary": summary,
        "details": json.dumps({"field": field}),
    }


QUALITY_CRITERIA_LEVELS = {
    "invalid geometry": 2,
    "invalid date": 3,
    "missing value": 3,
    "unknown entity": 2,
}


class TestIssueTasks:
    def test_splits_issues_by_quality_criteria_level(self):
        task_log = [
            _issue_task("invalid geometry", "geometry", summary="Invalid geometry"),
            _issue_task("invalid date", "start-date", summary="Invalid date"),
        ]
        tasks = _issue_tasks(task_log, QUALITY_CRITERIA_LEVELS)
        assert sorted(tasks) == [(2, "Invalid geometry"), (3, "Invalid date")]

    def test_missing_value_on_reference_is_blocking(self):
        # 'missing value' is level 3 in general, but blocking on the reference field
        task_log = [
            _issue_task("missing value", "reference", summary="References missing"),
            _issue_task("missing value", "name", summary="Names missing"),
        ]
        tasks = _issue_tasks(task_log, QUALITY_CRITERIA_LEVELS)
        assert sorted(tasks) == [(2, "References missing"), (3, "Names missing")]

    def test_excludes_internal_and_unlevelled_issues(self):
        task_log = [
            _issue_task(
                "unknown entity",
                "entity",
                summary="Unknown entity",
                responsibility="internal",
            ),
            _issue_task("not in the issue type table", "name", summary="Something"),
        ]
        assert _issue_tasks(task_log, QUALITY_CRITERIA_LEVELS) == []

    def test_aggregates_counts_by_issue_type_and_field(self):
        task_log = [
            _issue_task("invalid date", "start-date", count=2),
            _issue_task("invalid date", "start-date", count=3),
        ]
        tasks = _issue_tasks(task_log, QUALITY_CRITERIA_LEVELS)
        assert tasks == [(3, "5 issues of type invalid date in start-date")]

    def test_falls_back_to_generated_summary(self):
        task_log = [_issue_task("invalid geometry", "geometry")]
        tasks = _issue_tasks(task_log, QUALITY_CRITERIA_LEVELS)
        assert tasks == [(2, "1 issue of type invalid geometry in geometry")]

    def test_ignores_non_dict_entries(self):
        task_log = [
            None,
            "not a task",
            _issue_task("invalid geometry", "geometry", summary="Invalid geometry"),
        ]
        assert _issue_tasks(task_log, QUALITY_CRITERIA_LEVELS) == [
            (2, "Invalid geometry")
        ]

    def test_ignores_entries_with_unusable_details(self):
        task_log = [
            {"task-source": "issue", "details": "not json", "summary": "x"},
            {"task-source": "issue", "details": "", "summary": "x"},
            _issue_task("invalid geometry", "", summary="No field"),
        ]
        assert _issue_tasks(task_log, QUALITY_CRITERIA_LEVELS) == []


class TestMissingColumnTasks:
    def test_uses_summary_when_present(self):
        task_log = [_column_field_task("reference", summary="Reference column missing")]
        assert _missing_column_tasks(task_log) == ["Reference column missing"]

    def test_generates_summary_when_missing(self):
        task_log = [_column_field_task("reference")]
        assert _missing_column_tasks(task_log) == ["reference column is missing"]

    def test_ignores_non_column_field_entries(self):
        task_log = [_issue_task("invalid date", "start-date", summary="Invalid date")]
        assert _missing_column_tasks(task_log) == []

    def test_ignores_non_dict_entries(self):
        task_log = [
            None,
            "not a task",
            _column_field_task("reference", summary="Reference column missing"),
        ]
        assert _missing_column_tasks(task_log) == ["Reference column missing"]


COMPLETED_CHECK_RESULT = {
    "status": "COMPLETED",
    "params": {
        "organisationName": "local-authority-eng:ABC",
        "dataset": "brownfield-land",
    },
    "response": {
        "data": {
            "task-log": [],
            "column-mapping": [{"field": "reference", "column": "ref"}],
        }
    },
}


class TestCheckResultsIncompleteDetails:
    def test_incomplete_details_warns_instead_of_erroring(self, client):
        # check.py shares fetch_response_details with transform.py, so it has to
        # honour the same contract - otherwise a transient page failure 500s.
        partial = [
            {
                "entry_number": 1,
                "converted_row": {"ref": "R1"},
                "transformed_row": [
                    {"entity": 100, "field": "reference", "value": "R1"}
                ],
                "issue_logs": [],
            }
        ]
        with patch(
            "application.blueprints.datamanager.router.fetch_request",
            return_value=COMPLETED_CHECK_RESULT,
        ), patch(
            "application.blueprints.datamanager.controllers.check.get_organisation_name",
            return_value="Test Org",
        ), patch(
            "application.blueprints.datamanager.controllers.check.get_dataset_name",
            return_value="Brownfield Land",
        ), patch(
            "application.blueprints.datamanager.controllers.check.fetch_response_details",
            side_effect=ResponseDetailsIncomplete("page 2 failed", partial=partial),
        ):
            response = client.get("/datamanager/check-results/incomplete-id")

        assert response.status_code == 200
        assert b"checked data could not be fetched" in response.data
        assert b"Reload to try again" in response.data
