import asyncio

async def test():
    from fifa_data.services.bracket import load_local_matches, build_bracket_data, INDEX_HTML

    local = load_local_matches()
    ko_matches = build_bracket_data(local)
    print(f"Loaded {len(ko_matches)} knockout matches")

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1200, "height": 1200})
        page = await context.new_page()

        hp = INDEX_HTML.replace("\\", "/")
        if not hp.startswith("/"):
            hp = "/" + hp
        fu = "file://" + hp
        print(f"Navigating to {fu}")
        await page.goto(fu, wait_until="load", timeout=15000)
        await page.wait_for_timeout(1000)

        await page.evaluate("(data) => { render(buildModel(normalize(data))); }", ko_matches)
        await page.wait_for_timeout(2500)

        stage_el = page.locator("#stage")
        count = await stage_el.count()
        print(f"#stage count: {count}")
        if count > 0:
            png = await stage_el.screenshot(type="png", omit_background=True)
            print(f"Captured {len(png)} bytes")
            with open("brackets_test.png", "wb") as f:
                f.write(png)
            print("Saved to brackets_test.png")
        else:
            print("ERROR: #stage not found!")
            print(await page.content())

        await browser.close()

asyncio.run(test())
