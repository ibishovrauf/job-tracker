"""Playwright-based career portal scraper.

Scrapes custom career websites of large companies that don't use
standard ATS platforms with public APIs.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time

from app.config import Settings

from . import register
from .base import RawJob, Source
from .portal_companies import PortalCompany, load_companies
from .portal_strategies import STRATEGIES, _dismiss_cookies, _make_slug

logger = logging.getLogger(__name__)

PORTAL_TIMEOUT = 30_000  # ms per page navigation
SCRAPE_CONCURRENCY = 3   # max parallel browser tabs
DELAY_BETWEEN = 1.0      # seconds between company scrapes


def _matches_keywords(text: str, keywords: list[str]) -> bool:
    """Check if text contains any keyword (word-boundary match)."""
    lower = text.lower()
    for kw in keywords:
        if re.search(r"\b" + re.escape(kw.lower()) + r"\b", lower):
            return True
    return False


@register("portals")
class PortalSource(Source):
    name = "portals"

    def fetch(self, settings: Settings) -> list[RawJob]:
        """Fetch jobs from all configured portal companies."""
        companies = load_companies(
            getattr(settings, "portal_companies_path", "companies.json")
        )
        if not companies:
            logger.info("No portal companies with URLs configured")
            return []

        # Skip platforms already handled by the ATS API scraper
        api_platforms = {"greenhouse", "lever", "ashby", "smartrecruiters"}
        playwright_companies = [c for c in companies if c.platform not in api_platforms]
        logger.info(
            "Scraping %d portal companies with Playwright "
            "(%d skipped — handled by ATS API scraper)...",
            len(playwright_companies), len(companies) - len(playwright_companies),
        )
        if not playwright_companies:
            return []
        return asyncio.run(self._fetch_async(playwright_companies, settings))

    async def _fetch_async(
        self, companies: list[PortalCompany], settings: Settings
    ) -> list[RawJob]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error(
                "Playwright not installed. Run: uv pip install 'job-tracker[portals]' "
                "&& playwright install chromium"
            )
            return []

        all_jobs: list[RawJob] = []
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            semaphore = asyncio.Semaphore(SCRAPE_CONCURRENCY)

            async def scrape_one(company: PortalCompany) -> list[RawJob]:
                async with semaphore:
                    return await self._scrape_company(browser, company, settings)

            tasks = [scrape_one(c) for c in companies]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.warning(
                        "Portal %s failed: %s", companies[i].name, result
                    )
                else:
                    all_jobs.extend(result)

            await browser.close()

        return all_jobs

    async def _scrape_company(
        self,
        browser: object,
        company: PortalCompany,
        settings: Settings,
    ) -> list[RawJob]:
        """Scrape a single company's career portal."""
        slug = _make_slug(company.name)
        start = time.time()
        logger.info("Portal scraping: %s (%s)", company.name, company.platform)

        context = await browser.new_context(
            locale="de-DE",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        try:
            await page.goto(company.search_url, timeout=PORTAL_TIMEOUT)
            await page.wait_for_load_state("domcontentloaded", timeout=PORTAL_TIMEOUT)

            # Wait a moment for JS to render
            await page.wait_for_timeout(3000)

            # Try to dismiss cookie consent
            await _dismiss_cookies(page)
            await page.wait_for_timeout(1000)

            # Select extraction strategy
            strategy_fn = STRATEGIES.get(company.platform, STRATEGIES["generic"])
            raw_jobs = await strategy_fn(page, company.name, slug)

            # Apply keyword filter
            keywords = settings.keywords
            matched: list[RawJob] = []
            for job in raw_jobs:
                searchable = " ".join(
                    filter(None, [job.title, job.description or "", job.job_type])
                )
                if _matches_keywords(searchable, keywords):
                    matched.append(job)

            elapsed = time.time() - start
            logger.info(
                "Portal %s: %d matched of %d found (%.1fs)",
                company.name, len(matched), len(raw_jobs), elapsed,
            )
            return matched

        except Exception:
            elapsed = time.time() - start
            logger.warning(
                "Portal %s: scrape error after %.1fs", company.name, elapsed,
                exc_info=True,
            )
            return []
        finally:
            await context.close()
            await asyncio.sleep(DELAY_BETWEEN)
