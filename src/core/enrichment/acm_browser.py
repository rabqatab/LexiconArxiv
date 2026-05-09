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
- `accept_downloads=True` + `page.expect_download()` to capture the PDF
  body. ACM responds with `Content-Disposition: inline` for /doi/pdf/*, but
  in headless Chromium application/pdf responses are routed to the download
  stack regardless (no PDF viewer plugin), so the download event fires.
- Critical: triggering the request must use `page.goto(url)` — JS navigation
  via `window.location.href = url` does NOT register the response with
  Playwright's download accounting in headless mode, so `expect_download()`
  silently times out.
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


def is_acm_paper_doi(doi: str | None) -> bool:
    """True if the DOI is an ACM paper-level DOI (has a single PDF).

    ACM convention: `10.1145/<proc-id>.<paper-id>` is a paper, while
    `10.1145/<proc-id>` (no `.` in suffix) is a proceedings/journal-level
    DOI without a single-paper PDF. Hitting `/doi/pdf/` on a journal DOI
    redirects to /doi/abs/ instead of triggering a download — and that
    pattern flags the browser session to Cloudflare for the rest of its
    lifetime, poisoning subsequent paper requests too. Filter these out
    upstream so we never poke them.
    """
    if not is_acm_doi(doi):
        return False
    suffix = doi.lower().lstrip("doi:").strip()[len("10.1145/"):]
    return "." in suffix


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
        download_timeout_ms: int = 30_000,
        consecutive_failure_circuit_breaker: int = 25,
    ):
        self._user_agent = user_agent
        self._rate_limit = rate_limit_seconds
        self._landing_timeout = landing_timeout_ms
        self._download_timeout = download_timeout_ms
        self._circuit_breaker_threshold = consecutive_failure_circuit_breaker

        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._ctx: BrowserContext | None = None
        self._challenge_cleared: bool = False
        self._last_request_at: float = 0.0
        self._lock = asyncio.Lock()
        self._consecutive_failures: int = 0
        self._circuit_open: bool = False

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
        the `cf_clearance` cookie automatically. If the landing page returns
        403 (Cloudflare flagged the current session — typically after a
        download failure pattern), recreate the BrowserContext once to get a
        fresh cookie session. If even a fresh context 403s, surrender —
        we're rate-limited at the IP level and waiting won't help.
        """
        if self._challenge_cleared:
            return True
        if self._ctx is None:
            raise RuntimeError("Downloader not started; use `async with`.")

        for attempt in (1, 2):
            page = await self._ctx.new_page()
            try:
                url = _ACM_LANDING.format(doi=doi)
                resp = await page.goto(url, wait_until="domcontentloaded",
                                       timeout=self._landing_timeout)
                if resp and resp.status == 200:
                    self._challenge_cleared = True
                    return True
                logger.warning(
                    f"ACM landing returned {resp.status if resp else '?'} "
                    f"for {doi} (attempt {attempt}/2)"
                )
            except Exception as e:
                logger.warning(
                    f"ACM landing visit failed for {doi} "
                    f"(attempt {attempt}/2): {e}"
                )
            finally:
                await page.close()

            # First attempt failed: rebuild context for a fresh CF cookie.
            if attempt == 1:
                logger.info(
                    "Recreating browser context after landing failure to "
                    "shed Cloudflare flag on the current session."
                )
                await self._recreate_context()

        return False

    async def _recreate_context(self) -> None:
        """Close the current browser context and create a fresh one.

        Resets the Cloudflare cookie session. Useful when the current
        session has been flagged and continued use just collects 403s.
        """
        if self._ctx is not None:
            try:
                await self._ctx.close()
            except Exception:
                pass
            self._ctx = None
        if self._browser is None:
            return
        self._ctx = await self._browser.new_context(
            user_agent=self._user_agent,
            viewport={"width": 1280, "height": 800},
            accept_downloads=True,
            locale="en-US",
        )
        self._challenge_cleared = False

    async def download_pdf(self, doi: str) -> bytes | None:
        """Download the PDF for an ACM DOI.

        Returns PDF bytes, or None on any failure (bot challenge not cleared,
        404, timeout, non-PDF body, etc.). Callers should treat None as "try
        the next source" rather than a fatal error.

        Circuit breaker: after `consecutive_failure_circuit_breaker` failures
        in a row, all subsequent calls return None immediately without
        touching the network — protects against silently burning hours when
        ACM changes its page UX.
        """
        if not is_acm_doi(doi):
            logger.warning(f"Not an ACM DOI: {doi}")
            return None
        if not is_acm_paper_doi(doi):
            # Journal/proceedings-level DOI — no single PDF exists. Hitting
            # /doi/pdf/ for these redirects to /doi/abs/ which trips Cloudflare
            # and poisons the session for subsequent paper requests.
            logger.info(f"Skipping non-paper ACM DOI (journal/proc-level): {doi}")
            return None
        if self._ctx is None:
            raise RuntimeError("Downloader not started; use `async with`.")
        if self._circuit_open:
            return None

        async with self._lock:
            await self._throttle()

            if not await self._ensure_challenge_cleared(doi):
                self._record_failure()
                return None

            pdf_url = _ACM_PDF.format(doi=doi)
            page = await self._ctx.new_page()
            tmp_path: Path | None = None
            download_future: asyncio.Future = (
                asyncio.get_event_loop().create_future()
            )

            def _on_download(d) -> None:  # noqa: ANN001 (Playwright Download)
                if not download_future.done():
                    download_future.set_result(d)

            page.on("download", _on_download)
            try:
                # page.goto() either:
                #  (a) raises "Download is starting" — Chromium recognized the
                #      response as a download. The `download` event has already
                #      fired (or fires concurrently). Wait briefly for the
                #      Playwright Download object via `download_future`.
                #  (b) returns a Response normally — the page rendered HTML
                #      (most commonly: ACM redirected /doi/pdf/* to /doi/abs/*
                #      because the paper has no free full-text PDF). Bail out
                #      immediately without waiting on a download that won't
                #      happen.
                started_download = False
                try:
                    response = await page.goto(
                        pdf_url,
                        wait_until="domcontentloaded",
                        timeout=self._landing_timeout,
                    )
                    # If we reach here, page rendered HTML (no download).
                    # This is NOT a system failure — most commonly the paper
                    # is paywalled or has no free PDF, so /doi/pdf/* redirects
                    # to /doi/abs/*. Don't count this toward the circuit
                    # breaker; reset consecutive_failures because a clean
                    # render proves the browser+session are healthy.
                    final_url = page.url or (response.url if response else "")
                    logger.info(
                        f"No free PDF for {doi}: page rendered "
                        f"{final_url!r} (likely paywalled or no public PDF)"
                    )
                    self._consecutive_failures = 0
                    return None
                except Exception as e:
                    if "Download is starting" not in str(e):
                        raise
                    started_download = True

                if not started_download:
                    return None  # unreachable, but defensive

                download = await asyncio.wait_for(
                    download_future, timeout=self._download_timeout / 1000.0
                )

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
                    self._record_failure()
                    return None
                self._consecutive_failures = 0
                return data

            except asyncio.TimeoutError:
                logger.warning(
                    f"ACM PDF download failed for {doi}: timed out after "
                    f"{self._download_timeout}ms waiting for download body"
                )
                self._record_failure()
                return None
            except Exception as e:
                logger.warning(f"ACM PDF download failed for {doi}: {e}")
                self._record_failure()
                return None
            finally:
                if tmp_path is not None and tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
                page.remove_listener("download", _on_download)
                await page.close()

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        # Note: we do NOT eagerly invalidate _challenge_cleared on failure.
        # Earlier versions did, and that triggered a cascade — every failure
        # forced a re-warm via landing page, which 403s once Cloudflare has
        # alarmed the session, which counted as another failure, which
        # forced another re-warm, ... Better to leave the existing cookie
        # alone and let _ensure_challenge_cleared handle recovery via
        # _recreate_context() when it actually sees a 403 landing.
        if (
            not self._circuit_open
            and self._consecutive_failures >= self._circuit_breaker_threshold
        ):
            self._circuit_open = True
            logger.error(
                f"ACM browser circuit breaker tripped after "
                f"{self._consecutive_failures} consecutive failures — "
                f"remaining ACM requests will short-circuit to None. "
                f"Investigate page UX change (ACM may have moved to a viewer iframe)."
            )
