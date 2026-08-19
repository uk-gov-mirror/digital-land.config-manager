import logging
from concurrent.futures import ThreadPoolExecutor

import requests
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

# Kept well under the CDN's 30s origin timeout so one slow page can't eat the budget.
PAGE_REQUEST_TIMEOUT = 10
DEFAULT_MAX_WORKERS = 8

# Reused across pages to avoid a TLS handshake each time. pool_maxsize must stay
# >= the worker count or urllib3 discards connections.
_session = requests.Session()
_adapter = HTTPAdapter(pool_connections=4, pool_maxsize=16)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)


def get_http_session() -> requests.Session:
    """Return the process-wide pooled session used for paged fetches."""
    return _session


def fetch_pages_concurrently(
    urls: list,
    max_workers: int = DEFAULT_MAX_WORKERS,
    timeout: int = PAGE_REQUEST_TIMEOUT,
    headers: dict = None,
) -> list:
    """
    GET every url and return the parsed JSON bodies in the order the urls were given.
    A page that fails contributes None rather than raising, so one bad page doesn't
    lose the others.

    Callers build their own paginated urls, fully resolved — the workers run off the
    request thread and so have no Flask application context to read config from.
    """
    if not urls:
        return []

    session = get_http_session()

    def _get(url):
        try:
            response = session.get(url, timeout=timeout, headers=headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to fetch page {url}: {e}", exc_info=True)
            return None

    with ThreadPoolExecutor(max_workers=min(max_workers, len(urls))) as executor:
        # map preserves input order, which callers rely on to reassemble by offset.
        return list(executor.map(_get, urls))
