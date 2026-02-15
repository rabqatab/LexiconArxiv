"""OpenAlex API key manager with round-robin rotation and per-key cooldown."""

from __future__ import annotations

import logging
import time

from src.core.constants import get_openalex_api_keys, get_openalex_email

logger = logging.getLogger(__name__)


class OpenAlexKeyManager:
    """Manages a pool of OpenAlex API keys with round-robin rotation and per-key cooldown.

    Keys are rotated evenly across requests. When a key is exhausted (HTTP 429
    with "Insufficient credits"), it enters a cooldown period. After cooldown,
    it re-enters the rotation automatically. When ALL keys are exhausted,
    falls back to email-based polite pool.
    """

    def __init__(
        self,
        keys: list[str],
        email: str | None = None,
        cooldown: float = 300,
    ) -> None:
        # Deduplicate while preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for k in keys:
            if k not in seen:
                seen.add(k)
                deduped.append(k)
            else:
                logger.warning(f"Duplicate OpenAlex API key removed: {k[:8]}...")
        self._keys = deduped
        self._email = email
        self._cooldown = cooldown
        self._exhausted: dict[str, float] = {}  # key -> exhaustion timestamp
        self._index = 0

        logger.info(
            f"OpenAlex key manager: {len(self._keys)} API key(s) loaded, "
            f"email={'yes' if self._email else 'no'}"
        )

    @classmethod
    def from_env(cls) -> OpenAlexKeyManager:
        """Create key manager from environment variables.

        Reads OPENALEX_API_KEYS (comma-separated) or OPENALEX_API_KEY (single),
        plus OPENALEX_EMAIL as fallback.
        """
        keys = get_openalex_api_keys()
        email = get_openalex_email()
        return cls(keys=keys, email=email)

    def get_next_params(self) -> dict[str, str]:
        """Get query parameters for the next OpenAlex API call.

        Round-robins through available (non-exhausted) keys.
        Falls back to email if all keys exhausted, or empty dict if no email.
        """
        self._recover_keys()

        available = [k for k in self._keys if k not in self._exhausted]
        if available:
            key = available[self._index % len(available)]
            self._index += 1
            logger.debug(
                f"Using OpenAlex key {self._keys.index(key) + 1}/{len(self._keys)}"
            )
            return {"api_key": key}

        if self._email:
            return {"mailto": self._email}
        return {}

    def mark_exhausted(self, key: str) -> None:
        """Mark an API key as exhausted.

        Args:
            key: The API key string that received 429.
        """
        if key not in self._exhausted:
            self._exhausted[key] = time.monotonic()
            key_idx = self._keys.index(key) + 1 if key in self._keys else "?"
            remaining = self.active_key_count
            logger.warning(
                f"OpenAlex key {key_idx}/{len(self._keys)} exhausted. "
                f"{remaining} key(s) remaining."
            )
            if remaining == 0:
                if self._email:
                    logger.warning(
                        f"All {len(self._keys)} OpenAlex API key(s) exhausted. "
                        "Falling back to email polite pool."
                    )
                else:
                    logger.warning(
                        f"All {len(self._keys)} OpenAlex API key(s) exhausted. "
                        "No email configured — using anonymous access."
                    )

    def _recover_keys(self) -> None:
        """Check cooldowns and restore any keys whose cooldown has elapsed."""
        now = time.monotonic()
        recovered = [
            k for k, t in self._exhausted.items() if now - t > self._cooldown
        ]
        for k in recovered:
            del self._exhausted[k]
            key_idx = self._keys.index(k) + 1 if k in self._keys else "?"
            logger.info(
                f"OpenAlex key {key_idx}/{len(self._keys)} recovered after cooldown. "
                f"{self.active_key_count}/{len(self._keys)} key(s) available."
            )

    @property
    def has_available_keys(self) -> bool:
        """True if at least one non-exhausted key exists."""
        self._recover_keys()
        return any(k not in self._exhausted for k in self._keys)

    @property
    def active_key_count(self) -> int:
        """Number of non-exhausted keys."""
        return sum(1 for k in self._keys if k not in self._exhausted)

    @property
    def total_key_count(self) -> int:
        """Total number of keys in pool."""
        return len(self._keys)
