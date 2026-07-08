"""Shared retry helper for transient Qdrant failures (Wave 1e-bis).

Born from the 2026-07-04 b2ab incident: one transient ``set_payload``
timeout torched a 500-paper labeling batch that had zero retry. Every
Qdrant call in a bulk loop wraps in this helper so one bad second
doesn't lose the whole batch.
"""

import logging
import time

from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

logger = logging.getLogger(__name__)


def retry_qdrant(fn, *, max_attempts: int = 5, label: str = "qdrant call"):
    """Call ``fn`` with exponential backoff (1, 2, 4, 8, 16s, capped at 30s)
    on transient Qdrant errors (timeouts, connection drops, 5xx, 429).

    Permanent errors — 4xx other than 429 (payload validation, not-found) —
    propagate immediately: retrying them just repeats the failure.
    """
    delay = 1.0
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except (ResponseHandlingException, UnexpectedResponse, OSError) as e:
            if isinstance(e, UnexpectedResponse) and 400 <= e.status_code < 500 \
                    and e.status_code != 429:
                raise
            if attempt >= max_attempts:
                logger.error(
                    "%s failed after %d attempts: %s", label, max_attempts, e,
                )
                raise
            logger.warning(
                "%s failed (attempt %d/%d), retrying in %.0fs: %s",
                label, attempt, max_attempts, delay, e,
            )
            time.sleep(delay)
            delay = min(delay * 2, 30.0)
