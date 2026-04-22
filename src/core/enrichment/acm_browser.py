"""ACM Digital Library PDF downloader using headless Chromium (stealth mode).

ACM DL (dl.acm.org) hosts PDFs for KDD, SIGIR, WWW, RecSys, CIKM, and WSDM —
primary Tier 0/1 venues for this corpus. Anonymous script access is blocked by
Cloudflare's JS challenge regardless of the URL path; only a real browser
(executing the challenge) passes. This module runs Chromium headlessly with
stealth flags to clear the challenge once per session, then streams PDF
downloads from `/doi/pdf/<DOI>`.

POLICY NOTE
-----------
ACM's robots.txt explicitly disallows AI crawlers (`GPTBot`, `CCBot`,
`Google-Extended`, `ChatGPT-User`). This module is technically capable of
bypassing that signal. It is intended for academic research-corpus construction
on a single organization's infrastructure; operators are responsible for
ensuring their use aligns with ACM's terms and local institutional agreements.
Rate limiting is conservative (~1 request / 2 s) by design.

Runtime characteristics
-----------------------
- Chromium launched with `--disable-gpu`, `--disable-software-rasterizer`,
  `--use-gl=swiftshader` — CPU-only rendering, no GPU memory contention with
  co-located ML workloads.
- Single browser context per downloader instance; Cloudflare cookies persist
  for its lifetime. Reuse the instance across many downloads.
- `accept_downloads=True` + `page.expect_download()` to capture the PDF body
  (ACM's /doi/pdf/* path triggers a download disposition rather than inline
  rendering).
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Playwright

logger = logging.getLogger(__name__)

_ACM_LANDING = "https://dl.acm.org/doi/{doi}"
_ACM_PDF = "https://dl.acm.org/doi/pdf/{doi}"

_DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_CHROMIUM_ARGS = [
    "--disable-gpu",
    "--disable-software-rasterizer",
    "--disable-dev-shm-usage",
    "--no-sandbox",
    "--use-gl=swiftshader",
    # Fingerprint-softening: do not announce automation to page JS.
    "--disable-blink-features=AutomationControlled",
]


def is_acm_doi(doi: str | None) -> bool:
    """True if the DOI belongs to ACM (prefix 10.1145/...)."""
    if not doi:
        return False
    return doi.lower().lstrip("doi:").strip().startswith("10.1145/")


class ACMBrowserDownloader:
    """Download ACM PDFs via headless stealth Chromium.

    Usage::

        async with ACMBrowserDownloader() as dl:
            pdf_bytes = await dl.download_pdf("10.1145/3701716.3717510")

    One browser context is kept alive across calls so the Cloudflare challenge
    is cleared once and reused. Call sites should instantiate one downloader
    and funnel all ACM DOIs through it, not create a new one per paper.
    """

    def __init__(
        self,
        user_agent: str = _DEFAULT_UA,
        rate_limit_seconds: float = 2.0,
        landing_timeout_ms: int = 45_000,
        download_timeout_ms: int = 60_000,
    ):
        self._user_agent = user_agent
        self._rate_limit = rate_limit_seconds
        self._landing_timeout = landing_timeout_ms
        self._download_timeout = download_timeout_ms

        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._ctx: BrowserContext | None = None
        self._challenge_cleared: bool = False
        self._last_request_at: float = 0.0
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "ACMBrowserDownloader":
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=_CHROMIUM_ARGS,
        )
        self._ctx = await self._browser.new_context(
            user_agent=self._user_agent,
            viewport={"width": 1280, "height": 800},
            accept_downloads=True,
            locale="en-US",
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._ctx is not None:
            await self._ctx.close()
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()

    async def _throttle(self) -> None:
        """Enforce rate limit between consecutive requests."""
        now = asyncio.get_event_loop().time()
        wait = self._rate_limit - (now - self._last_request_at)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_request_at = asyncio.get_event_loop().time()

    async def _ensure_challenge_cleared(self, doi: str) -> bool:
        """Visit a landing page to clear the Cloudflare JS challenge.

        Only needs to run once per browser context. Subsequent requests reuse
        the `cf_clearance` cookie automatically.
        """
        if self._challenge_cleared:
            return True
        if self._ctx is None:
            raise RuntimeError("Downloader not started; use `async with`.")

        page = await self._ctx.new_page()
        try:
            url = _ACM_LANDING.format(doi=doi)
            resp = await page.goto(url, wait_until="domcontentloaded",
                                   timeout=self._landing_timeout)
            if resp and resp.status == 200:
                self._challenge_cleared = True
                return True
            logger.warning(f"ACM landing returned {resp.status if resp else '?'} for {doi}")
            return False
        except Exception as e:
            logger.warning(f"ACM landing visit failed for {doi}: {e}")
            return False
        finally:
            await page.close()

    async def download_pdf(self, doi: str) -> bytes | None:
        """Download the PDF for an ACM DOI.

        Returns PDF bytes, or None on any failure (bot challenge not cleared,
        404, timeout, non-PDF body, etc.). Callers should treat None as "try
        the next source" rather than a fatal error.
        """
        if not is_acm_doi(doi):
            logger.warning(f"Not an ACM DOI: {doi}")
            return None
        if self._ctx is None:
            raise RuntimeError("Downloader not started; use `async with`.")

        async with self._lock:
            await self._throttle()

            if not await self._ensure_challenge_cleared(doi):
                return None

            pdf_url = _ACM_PDF.format(doi=doi)
            page = await self._ctx.new_page()
            tmp_path: Path | None = None
            try:
                async with page.expect_download(timeout=self._download_timeout) as dl_info:
                    # JS navigation avoids Playwright's "not a page" error
                    # when the response is a download disposition.
                    await page.evaluate(
                        "url => window.location.href = url", pdf_url
                    )
                download = await dl_info.value

                # Stream to a temp file, then read bytes (Playwright's
                # download API is file-oriented, not bytes-oriented).
                with tempfile.NamedTemporaryFile(
                    suffix=".pdf", delete=False
                ) as tmp:
                    tmp_path = Path(tmp.name)
                await download.save_as(tmp_path)
                data = tmp_path.read_bytes()

                if not data.startswith(b"%PDF"):
                    logger.warning(
                        f"ACM response for {doi} is not a PDF "
                        f"(first bytes: {data[:8]!r})"
                    )
                    return None
                return data

            except Exception as e:
                logger.warning(f"ACM PDF download failed for {doi}: {e}")
                return None
            finally:
                if tmp_path is not None and tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
                await page.close()
