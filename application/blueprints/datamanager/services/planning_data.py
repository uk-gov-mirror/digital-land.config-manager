import logging

import requests
from flask import current_app

from application.extensions import cache

from application.data_access.http import fetch_pages_concurrently
from ..utils import REQUESTS_TIMEOUT

logger = logging.getLogger(__name__)


class PlatformEntitiesIncomplete(Exception):
    """
    Raised when any entity page failed. A partial list is worse than none, since the
    entities missing from it get reported as new. Raising also leaves the memoize
    cache empty, so the next request retries instead of serving the gap.
    """


def get_entity_count_for_organisation_and_dataset(
    organisation_entity: int | str, dataset: str
) -> int:
    """
    Return the total count of authoritative entities using a single API request,
    or None if it couldn't be fetched. The count drives which offsets get fetched,
    so a failure must not look like a genuine zero.
    """
    planning_url = current_app.config.get("PLANNING_BASE_URL")
    url = (
        f"{planning_url}/entity.json"
        f"?organisation_entity={organisation_entity}"
        f"&dataset={dataset}"
        f"&quality=authoritative"
        f"&limit=1"
    )
    try:
        response = requests.get(url, timeout=REQUESTS_TIMEOUT)
        response.raise_for_status()
        # No count key means we don't know the size, which is not the same as zero.
        return response.json().get("count")
    except Exception as e:
        logger.error(
            f"Failed to fetch entity count for organisation_entity="
            f"{organisation_entity} dataset={dataset}: {e}",
            exc_info=True,
        )
        return None


ENTITY_PAGE_SIZE = 500


def _org_entities_url(organisation_entity: int | str, dataset: str) -> str:
    planning_url = current_app.config.get("PLANNING_BASE_URL")
    return (
        f"{planning_url}/entity.json"
        f"?organisation_entity={organisation_entity}"
        f"&dataset={dataset}"
        f"&quality=authoritative"
        f"&limit={ENTITY_PAGE_SIZE}"
    )


@cache.memoize(timeout=300)
def get_entities_for_organisation_and_dataset(
    organisation_entity: int | str, dataset: str, total: int = None
) -> list:
    """
    Fetch all authoritative entities for a given organisation entity number and dataset
    from the planning data /entity.json endpoint. Returns a list of entity dicts.

    When the caller already knows the total it is passed in, letting every page be
    fetched in parallel. Without it, falls back to walking links.next one page at a time.

    Raises PlatformEntitiesIncomplete if any page fails.
    """
    if total is None:
        return _get_entities_sequentially(organisation_entity, dataset)

    base_url = _org_entities_url(organisation_entity, dataset)
    offsets = list(range(0, total, ENTITY_PAGE_SIZE))
    urls = [f"{base_url}&offset={offset}" for offset in offsets]

    entities = []
    for offset, page in zip(offsets, fetch_pages_concurrently(urls)):
        if page is None:
            raise PlatformEntitiesIncomplete(
                f"Entity page at offset {offset} failed for organisation_entity="
                f"{organisation_entity} dataset={dataset}"
            )
        entities.extend(page.get("entities", []))

    # Catches a page that returned 200 with fewer rows than the count implied.
    if len(entities) < total:
        raise PlatformEntitiesIncomplete(
            f"Expected {total} entities for organisation_entity={organisation_entity} "
            f"dataset={dataset} but got {len(entities)}"
        )

    logger.info(
        f"Fetched {len(entities)} of {total} entities for organisation_entity="
        f"{organisation_entity} dataset={dataset} in {len(urls)} parallel page(s)"
    )
    return entities


def _get_entities_sequentially(organisation_entity: int | str, dataset: str) -> list:
    """
    Walk links.next one page at a time, for when the total isn't known up front.

    Raises PlatformEntitiesIncomplete if a page fails part way through.
    """
    planning_url = current_app.config.get("PLANNING_BASE_URL")
    url = _org_entities_url(organisation_entity, dataset)

    entities = []
    page = 0
    while url:
        page += 1
        try:
            response = requests.get(url, timeout=REQUESTS_TIMEOUT)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            raise PlatformEntitiesIncomplete(
                f"Failed to fetch entities (page {page}) for organisation_entity="
                f"{organisation_entity} dataset={dataset}: {e}"
            ) from e

        entities.extend(data.get("entities", []))

        next_url = (data.get("links") or {}).get("next")
        if next_url:
            if next_url.startswith("/"):
                url = f"{planning_url.rstrip('/')}{next_url}"
            else:
                url = next_url
        else:
            url = None

    logger.info(
        f"Fetched {len(entities)} entities for organisation_entity={organisation_entity} "
        f"dataset={dataset} in {page} page(s)"
    )
    return entities
