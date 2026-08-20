# Datamanager Blueprint — Architecture

This document describes the structure of the `datamanager` blueprint and how to work within it. Read this before adding new routes, services, or utilities.

---

## Directory layout

> Docs for this blueprint live in `docs/datamanager/` (this file, plus `add-data.md`,
> `assign-entities.md`, and `github-add.md`).

```
application/blueprints/datamanager/
├── router.py               # Blueprint definition, URL rules, auth guard
├── controllers/
│   ├── __init__.py         # ControllerError exception
│   ├── form.py             # Dashboard GET/POST, import, add-data form
│   ├── check.py            # Check results (geometry, column mapping) and resubmit
│   ├── preview.py          # Entities preview and async GitHub confirm
│   ├── transform.py        # Transformed facts, issue logs, entity growth check
│   ├── flagged_resources.py # Assign-entities: import, summary, per-resource submit
│   └── request_meta.py     # Submission-time writers for the RequestMeta table
├── services/
│   ├── async_api.py        # Async request API client
│   ├── dataset.py          # Dataset lookups and autocomplete
│   ├── dataset_field.py    # Dataset-field mapping from specification CSV
│   ├── doc_crawler.py      # Documentation page link checker
│   ├── endpoint.py         # Endpoint URL lookups from datasette by hash
│   ├── github.py           # GitHub App auth and workflow triggers
│   ├── organisation.py     # Organisation lookups and entity number mapping
│   └── planning_data.py    # Entity counts and lists from the planning data API
└── utils/
    ├── __init__.py         # Shared helpers: error handling, table building
    ├── configure.py        # Column mapping row builder
    └── csv_formats.py      # CSV format builders per dataset type
```

Paged API fetches use `application/data_access/http.py`, which sits outside this
blueprint because nothing about it is datamanager-specific. It provides the pooled
`requests.Session` and `fetch_pages_concurrently(urls)`. See
[Paged fetches and partial failure](#paged-fetches-and-partial-failure).

---

## Layers and responsibilities

### `router.py` — HTTP layer

The single entry point for the blueprint.

- Creates the `datamanager_bp` Flask `Blueprint` with `url_prefix="/datamanager"`
- Registers the `require_login` before-request guard
- Registers the `handle_error` blueprint-level error handler
- Registers the `inject_now` context processor
- Defines thin view functions that delegate immediately to a controller
- Registers all URL rules with `blueprint.add_url_rule()`

**Rule:** router view functions should contain minimal logic. If you find yourself writing more than a handful of lines inside a view function, move the logic into a controller.

---

### `controllers/` — Orchestration layer

Controllers receive a request context and orchestrate the workflow: validate inputs, call services, build template context, return a rendered response or redirect.

| File | Handles |
|---|---|
| `form.py` | Dashboard GET, dashboard POST (form submit), CSV import GET/POST, add-data form |
| `check.py` | Check results display with geometry rendering and inline column-mapping UI (GET), resubmit with updated column mappings (POST) |
| `preview.py` | Entities preview loading/result page, add-data confirm (trigger GitHub workflow and show success) |
| `transform.py` | Transformed facts and issue log display, entity comparison vs. platform entities, entity growth check; shared between add-data and assign-entities flows |
| `flagged_resources.py` | Assign-entities flow: upload/paste flagged-resources CSV, grouped summary view, per-resource submit to async API |
| `request_meta.py` | Records per-request metadata on the `RequestMeta` table at submission time (`source_flow`, config branch baseline) that the async request's params can't carry |

#### `RequestMeta` and `source_flow`

The entities preview and confirm routes live under `/datamanager` but are reused by the assign-entities flow (which redirects into them rather than having its own copies). Because those two endpoints are shared, the URL prefix alone can't tell which process lock applies. So at submission time each flow records `source_flow` (`"add_data"` / `"assign_entities"`) on `RequestMeta` via `record_source_flow`; the router's lock guard and the preview render then read it back — the single source of truth for which flow a request belongs to. `RequestMeta` also carries the check-transform retire/unretire selections (`endpoints_to_retire` / `endpoints_to_unretire`) that the async request's params can't — stored on POST and forwarded to the commit workflow.

#### `ControllerError`

Defined in `controllers/__init__.py`. Raise this for any expected, user-facing failure:

```python
from .controllers import ControllerError

raise ControllerError("Could not find the requested dataset.")
```

The router catches `ControllerError` and renders `datamanager/error.html` with `e.message`. Do not use it for unexpected exceptions — let those propagate to the blueprint-level error handler.

---

### `services/` — External integration layer

Each service owns one domain. Services are stateless functions (plus module-level caches where needed). They do not import from controllers or the router.

#### `async_api.py`

Client for the async request API.

| Function | Description |
|---|---|
| `submit_request(params)` | POST to `/requests`, returns `request_id` |
| `fetch_request(request_id)` | GET `/requests/<id>`, returns parsed dict |
| `fetch_response_details(request_id, limit)` | Paginated GET of response details, returns aggregated list. Memoized for **1 hour** |

Raises `AsyncAPIError(message, status_code, detail)` on failure, or
`ResponseDetailsIncomplete` (a subclass, carrying `.partial`) when some pages fail.

`fetch_response_details` reads the row total from the `X-Pagination-Total-Results`
header on the first page, then fetches the remaining offsets in parallel. If that
header is absent it falls back to sequential paging.

#### `dataset.py`

Lookups against the planning data datasets endpoint. Results cached for **5 minutes**.

| Function | Description |
|---|---|
| `get_dataset_options()` | Sorted list of dataset names |
| `get_dataset_id(name)` | Dataset ID for a given name |
| `get_collection_id(name)` | Collection ID for a given name |
| `get_dataset_name(dataset_id)` | Human name for a dataset ID |
| `search_datasets(query, limit)` | Case-insensitive name search for autocomplete |

#### `dataset_field.py`

Dataset-to-field mapping fetched from the specification CSV (`DATASET_FIELD_CSV_URL`). Results cached for **5 minutes**.

| Function | Description |
|---|---|
| `get_fields_for_dataset(dataset_id)` | All field rows (dicts) for a dataset, or `[]` if not found |
| `get_field_names_for_dataset(dataset_id)` | Sorted list of field name strings for a dataset |

#### `doc_crawler.py`

Checks whether an endpoint URL is linked from a documentation page by fetching and parsing the page's `<a href>` tags. Results memoized for **1 hour** via `cache.memoize`.

| Function | Description |
|---|---|
| `is_gov_uk_url(url)` | Returns `True` if the URL's hostname is `gov.uk` or a subdomain |
| `check_endpoint_in_doc(documentation_url, endpoint_url)` | Returns `{found, matched_href, error}` — whether the endpoint URL appears as a link in the documentation page |

#### `endpoint.py`

Endpoint URL lookups from the datasette `endpoint` table.

| Function | Description |
|---|---|
| `get_endpoint_urls_for_hashes(hashes)` | Given a list of endpoint hashes, returns `{hash: {endpoint_url, end_date}}` |

#### `organisation.py`

Organisation lookups from the provision CSV and datasette. Three separate caches:

- Provision orgs per dataset: **5 minutes** (`_provision_cache`)
- Full org code → name mapping: **10 minutes** (`_org_mapping_cache`)
- Org code → entity number mapping: **10 minutes** (`_org_entity_cache`)

| Function | Description |
|---|---|
| `get_provision_orgs_for_dataset(dataset_id)` | List of org codes provisioned for a dataset |
| `get_organisation_name(code)` | Display name for an org code (falls back to code) |
| `is_valid_organisation(code)` | Whether an org code exists |
| `format_org_options(org_codes)` | Format codes as `[{code, label}]` dicts for UI dropdowns |
| `get_org_entity(code)` | Entity number (int) for an org code, or `None` if not found |
| `get_org_entity_lookup()` | Full org code → entity number mapping dict (internal; used by `get_org_entity`) |

#### `github.py`

GitHub App authentication and workflow dispatch.

- `trigger_add_data_async_workflow(...)` — the primary public function; handles JWT generation, installation token fetch, and workflow dispatch internally
- Custom exceptions: `GitHubAppError`, `GitHubAppAuthError`, `GitHubWorkflowError`

#### `planning_data.py`

Entity data from the planning data API (`PLANNING_BASE_URL`). Entity lists are memoized for **5 minutes** via `cache.memoize`.

| Function | Description |
|---|---|
| `get_entity_count_for_organisation_and_dataset(organisation_entity, dataset)` | Total count of authoritative entities for an org entity number + dataset (single API call). Returns `None` if the call fails |
| `get_entities_for_organisation_and_dataset(organisation_entity, dataset, total)` | Full list of authoritative entities for an org entity number + dataset |

Raises `PlatformEntitiesIncomplete` when any page fails.

The count is fetched first and passed in as `total`, so every page can be fetched in
parallel. It returns `None` rather than `0` on failure precisely because it drives
which offsets get requested — a failure that looked like a genuine zero would return
no entities and report every entity in the resource as new. Without a `total`, the
function falls back to walking `links.next` one page at a time.

---

### Paged fetches and partial failure

The transform page reads two paginated sources, both capped server-side at 500 rows
per page, and both fetched in parallel via `fetch_pages_concurrently`. Each feeds one
side of the resource-vs-platform comparison, so a gap in either produces a page that
looks authoritative and is wrong:

| Source | Feeds | A missing page would cause |
|---|---|---|
| async `response-details` | transform table, issue log, resource side of the comparison | real platform entities shown as **"Platform only"** |
| platform `entity.json` | platform side of the comparison | resource entities that already exist shown as **"New"** |

**Services raise rather than return a partial list.** This is deliberate and load-bearing:
both functions are wrapped in `cache.memoize`, which only stores return values. Returning
a short list would cache the gap for the full timeout (1 hour / 5 minutes); raising leaves
the cache empty so the next page load retries.

**The controller then degrades the page rather than failing it:**

| Failure | `all_resp_details` | Comparison | Banner |
|---|---|---|---|
| `ResponseDetailsIncomplete` | the exception's `.partial` rows | suppressed | "Some of the transformed data could not be fetched" + reload link |
| `PlatformEntitiesIncomplete` | unaffected | suppressed | "The platform data could not be fetched" + reload link |
| entity count unavailable (`None`) | unaffected | suppressed | same as `PlatformEntitiesIncomplete` |
| count over `_PLATFORM_ENTITY_LIMIT` | unaffected | suppressed | existing "dataset too large" inset text |

Suppressed means `comparison_unavailable` is passed to the template: the entity table and
its summary stat boxes do not render, and an inset message explains why. The transform and
issue log tables still render throughout.

For `geography` datasets the map is built from the same two inputs, so it degrades with
the comparison: `_build_geometry_features(..., compare=False)` returns only the resource's
own geometry, with no `status` on any feature. The map JS already treats a statusless
feature set as one neutral group (the check-results page relies on this), so the geometry
stays visible without being miscategorised — no template or JS change needed.

A `None` count is treated as a fetch failure rather than a zero. It determines which
offsets get requested, so without it the too-large guard cannot be evaluated and paging
would fall back to an unbounded serial walk inside the web request.

**When adding a new paged fetch,** follow the same contract — raise on an incomplete
result, let the controller decide how to degrade, and never return a partial list from a
memoized function.

---

### `utils/` — Shared helpers

Pure helper functions with no dependency on Flask request context (except where noted). Safe to call from controllers or other utils.

#### `utils/__init__.py`

| Symbol | Description |
|---|---|
| `REQUESTS_TIMEOUT` | Default timeout (20 s) — import this in services instead of hardcoding |
| `handle_error(e)` | Blueprint error handler — renders `datamanager/error.html` with a 500 |
| `inject_now()` | Context processor injecting `now` (datetime) into templates |
| `get_spec_fields_union(dataset_id)` | Union of global + dataset-scoped field definitions from datasette |
| `order_table_fields(fields)` | Orders fields with `reference` first, `name` second |
| `read_raw_csv_preview(source_url, max_rows)` | Fetch and parse the first N rows of a remote CSV |
| `build_check_tables(column_field_log, resp_details)` | Build converted, transformed, and issue-log table dicts for templates |

#### `utils/configure.py`

- `build_column_mapping_rows(...)` — builds UI rows for the column-mapping form

#### `utils/csv_formats.py`

Format-specific CSV builders used in the add-data preview:

- `build_lookup_csv_preview()`
- `build_endpoint_csv_preview()`
- `build_source_csv_preview()`
- `build_column_csv_preview()`
- `build_entity_organisation_csv()`

---

> **Note:** `config.py` currently also re-exports `get_request_api_endpoint` from the top-level `config/config.py`. The intention is to eventually consolidate all URL config here.

---


Errors at any layer:
- **Service errors** (`AsyncAPIError`, `GitHubAppError`, etc.) — catch in the controller, either recover or raise `ControllerError`
- **Incomplete-fetch errors** (`ResponseDetailsIncomplete`, `PlatformEntitiesIncomplete`) — catch in the controller and degrade the page, never propagate; see [Paged fetches and partial failure](#paged-fetches-and-partial-failure)
- **`ControllerError`** — caught by the router view function, renders `datamanager/error.html`
- **Unexpected exceptions** — caught by `datamanager_bp.errorhandler(Exception)` → `handle_error`, renders `datamanager/error.html` with a 500


## Testing

Tests mirror the layered structure:

```
tests/
├── unit/blueprints/datamanager/
│   ├── services/       # Unit tests per service (mock HTTP calls)
│   ├── controllers/    # Controller unit tests (mock services)
│   └── utils/          # Utility function tests
├── integration/blueprints/datamanager/
└── acceptance/blueprints/datamanager/
    └── test_add_data_journey.py
```

- Service tests should mock `requests.get` / `requests.post`
- Controller tests should mock service functions
- Do not test the router directly — that is covered by integration/acceptance tests
