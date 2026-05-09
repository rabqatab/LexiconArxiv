"""Probe ACM's /doi/pdf/<DOI> page to see what it actually serves now.

Writes:
  - the response status + content-type for the navigation
  - the response status + content-type for any subsidiary requests for PDF bytes
  - all <embed>, <iframe>, <object> URLs on the page
  - any network response whose URL ends in .pdf or whose content-type starts
    with application/pdf

Run:
    uv run python scripts/maintenance/probe_acm_pdf_page.py
"""
import asyncio
import sys

PROBE_DOI = "10.1145/3292500.3340409"  # KDD'19 — definitely published

CHROMIUM_ARGS = [
    "--disable-gpu",
    "--disable-software-rasterizer",
    "--disable-dev-shm-usage",
    "--no-sandbox",
    "--use-gl=swiftshader",
    "--disable-blink-features=AutomationControlled",
]
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


async def main():
    from playwright.async_api import async_playwright

    pdf_responses: list[dict] = []
    embedded_urls: list[str] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=CHROMIUM_ARGS)
        ctx = await browser.new_context(
            user_agent=UA,
            viewport={"width": 1280, "height": 800},
            accept_downloads=True,
            locale="en-US",
        )

        # Warm Cloudflare via landing page.
        warmer = await ctx.new_page()
        landing = f"https://dl.acm.org/doi/{PROBE_DOI}"
        print(f"[1/3] Warming via {landing}")
        landing_resp = await warmer.goto(landing, wait_until="domcontentloaded", timeout=45_000)
        print(f"      landing status={landing_resp.status if landing_resp else '?'}")
        await warmer.close()

        page = await ctx.new_page()

        async def on_response(resp):
            ct = (resp.headers.get("content-type") or "").lower()
            if ".pdf" in resp.url.lower() or ct.startswith("application/pdf"):
                pdf_responses.append({
                    "url": resp.url,
                    "status": resp.status,
                    "content-type": ct,
                    "content-length": resp.headers.get("content-length"),
                    "content-disposition": resp.headers.get("content-disposition"),
                })

        page.on("response", on_response)

        pdf_url = f"https://dl.acm.org/doi/pdf/{PROBE_DOI}"
        print(f"[2/3] Visiting {pdf_url}")
        try:
            nav = await page.goto(pdf_url, wait_until="domcontentloaded", timeout=45_000)
            print(f"      nav status={nav.status if nav else '?'}")
            print(f"      nav url={page.url}")
            print(f"      nav content-type={(nav.headers.get('content-type') if nav else '') or ''}")
            print(f"      nav content-disposition={(nav.headers.get('content-disposition') if nav else '') or ''}")
        except Exception as e:
            print(f"      nav exception: {e!r}")

        # Give the page a moment to load any embed/iframe.
        await page.wait_for_timeout(3000)

        # Inspect DOM for embedded PDF URLs.
        embed_srcs = await page.eval_on_selector_all(
            "embed, iframe, object",
            "els => els.map(e => ({tag: e.tagName, src: e.getAttribute('src') || e.getAttribute('data')}))",
        )
        print(f"[3/3] Embedded media refs in DOM:")
        for e in embed_srcs:
            print(f"      <{e['tag']}> {e['src']}")
            if e['src']:
                embedded_urls.append(e['src'])

        # Wait an additional 5s in case the viewer asynchronously requests the PDF.
        await page.wait_for_timeout(5000)

        print(f"\n=== Network responses for PDF/.pdf URLs ===")
        for r in pdf_responses:
            print(f"  {r['status']} {r['content-type']} {r['url']}")
            print(f"     CL={r['content-length']} CD={r['content-disposition']}")

        await browser.close()

    if not pdf_responses and not embedded_urls:
        print("\n[!] No PDF traffic and no embedded refs detected. Page may be HTML-only viewer.")
        sys.exit(2)


if __name__ == "__main__":
    asyncio.run(main())
