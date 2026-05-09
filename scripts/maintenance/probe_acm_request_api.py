"""Verify that ctx.request.get(pdf_url) works after Cloudflare warmup.

Cookies and UA are inherited from the browser context, so once the cf_clearance
cookie is set by visiting the landing page, an API-style fetch should be
sufficient — no `expect_download()` dance needed, and no inline/attachment
header sensitivity.
"""
import asyncio

DOIS = [
    "10.1145/3292500.3340409",  # KDD'19
    "10.1145/3637528.3673870",  # KDD'24
    "10.1145/3404835",           # SIGIR'20 (one we tried earlier)
]

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

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=CHROMIUM_ARGS)
        ctx = await browser.new_context(
            user_agent=UA,
            viewport={"width": 1280, "height": 800},
            accept_downloads=True,
            locale="en-US",
        )

        # Warm Cloudflare via the FIRST DOI's landing page.
        warmer = await ctx.new_page()
        warm_url = f"https://dl.acm.org/doi/{DOIS[0]}"
        warm_resp = await warmer.goto(warm_url, wait_until="domcontentloaded", timeout=45_000)
        print(f"[warmup] landing status = {warm_resp.status if warm_resp else '?'}")
        await warmer.close()

        for doi in DOIS:
            url = f"https://dl.acm.org/doi/pdf/{doi}"
            try:
                resp = await ctx.request.get(url, timeout=60_000)
                body = await resp.body()
                ok = body[:4] == b"%PDF"
                print(
                    f"[fetch] {doi} → status={resp.status} "
                    f"len={len(body):,} ct={resp.headers.get('content-type')!r} "
                    f"cd={resp.headers.get('content-disposition')!r} %PDF={ok}"
                )
            except Exception as e:
                print(f"[fetch] {doi} → EXCEPTION {type(e).__name__}: {e}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
