"""vLLM-based abstract labeling via OpenAI-compatible API.

vLLM (https://docs.vllm.ai/) is a batched LLM inference server. Where
Ollama serializes requests through a single GPU pipeline (~750 papers/hr
for granite4.1:8b on GB10, measured 2026-07-03), vLLM uses PagedAttention
+ continuous batching to process many concurrent requests together —
100× speedup is realistic for constrained-JSON labeling at 8B scale.

This backend uses vLLM's OpenAI-compatible ``/v1/chat/completions``
endpoint with the ``guided_json`` extra body param to enforce the same
Pydantic schema (:class:`SentenceLabels`) that Ollama's ``format`` field
enforces. Interface is identical to :class:`OllamaAbstractLabeler` so
``AbstractLabeler`` can swap backends by name.

Serving reference: ``scripts/labeling/serve_vllm.sh``.
Design context: ``docs/design/vllm-labeling-migration.md``.
"""

import asyncio
import logging

import httpx

from src.core.labeling.llm_base import (
    BaseAbstractLabeler,
    LABELING_SYSTEM_PROMPT,
    LABELING_USER_PROMPT,
    SentenceLabels,
)

logger = logging.getLogger(__name__)

DEFAULT_VLLM_BASE_URL = "http://localhost:8000"
DEFAULT_VLLM_MODEL = "ibm-granite/granite-4.1-8b"


class VLLMAbstractLabeler(BaseAbstractLabeler):
    """Abstract labeler backed by a vLLM OpenAI-compatible server."""

    def __init__(
        self,
        model: str = DEFAULT_VLLM_MODEL,
        base_url: str = DEFAULT_VLLM_BASE_URL,
        max_concurrent: int = 64,
        timeout: float = 180.0,
        max_retries: int = 5,
    ):
        # max_concurrent maps directly to how many in-flight requests we
        # send to vLLM. Unlike Ollama (which serializes internally),
        # vLLM benefits from high concurrency — 32-128 is typical.
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._client = httpx.AsyncClient(timeout=timeout)
        self._max_retries = max_retries

    async def label_sentences(
        self, title: str, abstract: str, numbered_sentences: str, num_sentences: int
    ) -> SentenceLabels | None:
        user_prompt = LABELING_USER_PROMPT.format(
            title=title, abstract=abstract, sentences=numbered_sentences
        )
        # vLLM's OpenAI-compatible endpoint accepts constrained JSON via a
        # top-level `response_format` field (OpenAI standard). Older docs
        # referenced `extra_body: {guided_json: ...}` — that's the OpenAI
        # Python SDK's client-side unpack convention, but when we POST raw
        # JSON via httpx it goes across the wire nested under extra_body
        # and vLLM ignores it (verified 2026-07-04: "fields ignored:
        # {'extra_body'}" warning in the server log). Response_format is
        # the wire-safe form.
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": LABELING_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "SentenceLabels",
                    "schema": SentenceLabels.model_json_schema(),
                },
            },
            "temperature": 0.1,
            "stream": False,
        }
        for attempt in range(self._max_retries):
            async with self._semaphore:
                try:
                    response = await self._client.post(
                        f"{self._base_url}/v1/chat/completions",
                        json=payload,
                    )

                    # 400 Bad Request — deterministic client-side error
                    # (prompt exceeds max_model_len, malformed schema, etc.).
                    # Retrying the same input yields the same 400. 2026-07-05:
                    # burnt ~31s (1+2+4+8+16) per outlier paper before this
                    # short-circuit. Log the reason so ops can spot outliers.
                    if response.status_code == 400:
                        try:
                            err_body = response.json().get("error", {})
                            msg = err_body.get("message") or str(err_body)[:200]
                        except Exception:
                            msg = response.text[:200]
                        logger.warning(
                            "vLLM returned 400 (deterministic — skip, no retry): %s",
                            msg,
                        )
                        return None

                    response.raise_for_status()
                    body = response.json()

                    # Skip retry when vLLM truncated the output (length limit)
                    # — same input will produce the same truncation. 2026-07-05:
                    # ~77% of long-abstract papers failed 5x retries with EOF
                    # JSON errors before we caught this. finish_reason=length
                    # means the output was cut mid-generation; short-circuit.
                    finish_reason = body["choices"][0].get("finish_reason")
                    if finish_reason == "length":
                        logger.warning(
                            "vLLM output hit length limit (finish_reason=length); "
                            "abstract likely too long for max_model_len. Giving up."
                        )
                        return None

                    content = body["choices"][0]["message"]["content"]
                    return SentenceLabels.model_validate_json(content)
                except Exception as e:
                    # JSON validation errors on well-formed non-truncated
                    # output are deterministic — retry won't help. But since
                    # finish_reason=length short-circuits above, any
                    # ValidationError reaching here is a rare model-quality
                    # issue where retry may help.
                    if attempt < self._max_retries - 1:
                        wait_time = 2 ** attempt
                        logger.warning(
                            "vLLM labeling failed (attempt %d/%d), retrying in %ds: %s",
                            attempt + 1, self._max_retries, wait_time, e,
                        )
                        await asyncio.sleep(wait_time)
                    else:
                        logger.warning(
                            "vLLM labeling failed after %d attempts: %s",
                            self._max_retries, e,
                        )
                        return None

    async def close(self) -> None:
        await self._client.aclose()
