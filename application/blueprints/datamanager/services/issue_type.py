import logging
import time

import requests
from flask import current_app

from ..utils import REQUESTS_TIMEOUT

logger = logging.getLogger(__name__)

_cache = {
    "data": None,
    "expires_at": 0,
}
CACHE_TTL_SECONDS = 300  # 5 minutes


def get_quality_criteria_levels() -> dict[str, int]:
    """Return a mapping of issue-type -> quality criteria level.

    The level decides whether an issue blocks data being added:
    level 2 issues are blocking ("must fix"), level 3 issues are
    non-blocking ("should fix"). Issue types with no level (internal
    responsibility or warning severity) are omitted.

    Fetched from the datasette issue_type table and cached for 5 minutes.
    """
    now = time.monotonic()
    if _cache["data"] is not None and now < _cache["expires_at"]:
        return _cache["data"]

    datasette_url = current_app.config.get("DATASETTE_BASE_URL")
    url = f"{datasette_url}/issue_type.json?_shape=objects&_size=max"

    levels: dict[str, int] = {}
    try:
        while url:
            response = requests.get(
                url,
                timeout=REQUESTS_TIMEOUT,
                headers={"User-Agent": "Planning Data - Manage"},
            )
            response.raise_for_status()
            data = response.json()

            rows = data.get("rows", []) if isinstance(data, dict) else data
            for row in rows:
                if not isinstance(row, dict):
                    continue
                issue_type = row.get("issue_type")
                level = row.get("quality_criteria_level")
                if not issue_type or level in (None, ""):
                    continue
                try:
                    levels[issue_type] = int(level)
                except (TypeError, ValueError):
                    logger.warning(
                        f"Ignoring non-numeric quality_criteria_level "
                        f"'{level}' for issue type '{issue_type}'"
                    )

            url = data.get("next_url") if isinstance(data, dict) else None
            if url and url.startswith("/"):
                url = f"{datasette_url.rstrip('/')}{url}"

    except Exception:
        logger.exception("Error fetching issue_type quality criteria levels")
        if _cache["data"] is not None:
            logger.warning("Returning stale issue_type cache after fetch failure")
            return _cache["data"]
        raise

    _cache["data"] = levels
    _cache["expires_at"] = now + CACHE_TTL_SECONDS

    return levels
