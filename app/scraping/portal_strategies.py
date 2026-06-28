"""Platform-specific extraction strategies for career portals.

Each strategy takes a Playwright Page and returns a list of RawJob objects.
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

from .base import RawJob

logger = logging.getLogger(__name__)


def _make_external_id(url: str) -> str:
    """Generate a stable external ID from a job URL."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _make_slug(name: str) -> str:
    """Convert company name to a URL-safe slug."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


async def _dismiss_cookies(page: "Page") -> None:
    """Try to dismiss common cookie consent banners."""
    selectors = [
        "button:has-text('Alle akzeptieren')",
        "button:has-text('Accept all')",
        "button:has-text('Accept All')",
        "button:has-text('Akzeptieren')",
        "button:has-text('Zustimmen')",
        "button:has-text('Alle Cookies akzeptieren')",
        "[data-testid='cookie-accept']",
        "[id*='cookie'] button:has-text('Accept')",
        "[id*='consent'] button:has-text('Accept')",
        "#onetrust-accept-btn-handler",
        ".cookie-banner button.accept",
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1000):
                await btn.click()
                logger.debug("Dismissed cookie banner with: %s", sel)
                return
        except Exception:
            continue


async def extract_workday(page: "Page", company_name: str, slug: str) -> list[RawJob]:
    """Extract jobs from Workday-powered career sites.

    Workday DOM patterns:
    - Job cards: <a data-automation-id="jobTitle">
    - Or: <a> inside elements with class containing 'job'
    - Pagination: "Show More" button
    """
    jobs: list[RawJob] = []

    # Wait for job results to load
    try:
        await page.wait_for_selector(
            "[data-automation-id='jobTitle'], .css-19uc56f, [class*='job'] a",
            timeout=15000,
        )
    except Exception:
        logger.warning("Workday %s: no job elements found", company_name)
        return []

    # Click "Show More" to load all results (up to 5 clicks)
    for _ in range(5):
        try:
            show_more = page.locator(
                "button[data-automation-id='loadMoreButton'], "
                "button:has-text('Show More'), "
                "button:has-text('Mehr anzeigen')"
            ).first
            if await show_more.is_visible(timeout=2000):
                await show_more.click()
                await page.wait_for_timeout(2000)
            else:
                break
        except Exception:
            break

    # Extract jobs via JavaScript
    raw = await page.evaluate("""() => {
        const jobs = [];
        // Try data-automation-id pattern first
        const links = document.querySelectorAll('a[data-automation-id="jobTitle"]');
        if (links.length > 0) {
            links.forEach(a => {
                const card = a.closest('li, [data-automation-id="jobItem"], div[class*="job"]');
                const loc = card?.querySelector('[data-automation-id="locations"], [class*="location"]');
                jobs.push({
                    title: a.textContent.trim(),
                    url: a.href,
                    location: loc?.textContent?.trim() || '',
                });
            });
        } else {
            // Fallback: find all links that look like job links
            document.querySelectorAll('a[href*="/job/"], a[href*="/en-US/"]').forEach(a => {
                const title = a.textContent.trim();
                if (title && title.length > 5 && title.length < 200) {
                    const parent = a.closest('li, tr, div');
                    const locEl = parent?.querySelector('[class*="location"], [class*="Location"]');
                    jobs.push({
                        title: title,
                        url: a.href,
                        location: locEl?.textContent?.trim() || '',
                    });
                }
            });
        }
        return jobs;
    }""")

    for item in raw:
        if not item.get("url"):
            continue
        jobs.append(RawJob(
            source=f"portal:{slug}",
            external_id=_make_external_id(item["url"]),
            title=item.get("title", ""),
            company=company_name,
            location=item.get("location", ""),
            url=item["url"],
        ))

    return jobs


async def extract_successfactors(page: "Page", company_name: str, slug: str) -> list[RawJob]:
    """Extract jobs from SAP SuccessFactors career sites."""
    jobs: list[RawJob] = []

    try:
        await page.wait_for_selector(
            ".jobTitle, .job-title, a[href*='/job/'], .resultsColumn a, table.jobs a",
            timeout=15000,
        )
    except Exception:
        logger.warning("SuccessFactors %s: no job elements found", company_name)
        return []

    raw = await page.evaluate("""() => {
        const jobs = [];
        // SuccessFactors patterns
        const selectors = [
            '.jobTitle a', '.job-title a', '.resultsColumn a',
            'a[href*="/job/"]', 'a[href*="/career/"]',
            'table.jobs a', '.listSingleColumnView a',
        ];
        const seen = new Set();
        for (const sel of selectors) {
            document.querySelectorAll(sel).forEach(a => {
                const url = a.href;
                if (seen.has(url)) return;
                seen.add(url);
                const title = a.textContent.trim();
                if (title && title.length > 3 && title.length < 200) {
                    const row = a.closest('tr, li, div');
                    const locEl = row?.querySelector('.jobLocation, .location, [class*="location"]');
                    jobs.push({
                        title: title,
                        url: url,
                        location: locEl?.textContent?.trim() || '',
                    });
                }
            });
            if (jobs.length > 0) break;
        }
        return jobs;
    }""")

    for item in raw:
        if not item.get("url"):
            continue
        jobs.append(RawJob(
            source=f"portal:{slug}",
            external_id=_make_external_id(item["url"]),
            title=item.get("title", ""),
            company=company_name,
            location=item.get("location", ""),
            url=item["url"],
        ))

    return jobs


async def extract_generic(page: "Page", company_name: str, slug: str) -> list[RawJob]:
    """Generic extraction for custom career sites.

    Heuristic: find repeated <a> elements whose href contains job-like paths
    (/job/, /career/, /stelle/, /position/, /vacancy/) and extract title + URL.
    """
    jobs: list[RawJob] = []

    # Wait for page to settle
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass  # Continue anyway — some pages never reach networkidle

    raw = await page.evaluate("""() => {
        const jobs = [];
        const seen = new Set();
        const jobPatterns = /\\/(job|jobs|career|careers|stelle|stellen|position|positions|vacancy|vacancies|posting|opening|requisition|apply)[\\/\\?#]/i;
        const skipPatterns = /\\/(login|register|signup|faq|about|contact|privacy|imprint|impressum|datenschutz|cookie)/i;

        document.querySelectorAll('a[href]').forEach(a => {
            const href = a.href;
            if (!href || seen.has(href) || !jobPatterns.test(href) || skipPatterns.test(href)) return;
            seen.add(href);

            const title = a.textContent.trim().replace(/\\s+/g, ' ');
            if (!title || title.length < 5 || title.length > 300) return;
            // Skip navigation-like links
            if (['Home', 'Back', 'Next', 'Previous', 'Search', 'Filter', 'Apply'].includes(title)) return;

            const parent = a.closest('li, tr, div, article, section');
            let location = '';
            if (parent) {
                const locEl = parent.querySelector('[class*="location"], [class*="Location"], [class*="ort"], [data-field="location"]');
                location = locEl?.textContent?.trim() || '';
            }

            jobs.push({ title, url: href, location });
        });

        return jobs;
    }""")

    for item in raw:
        if not item.get("url"):
            continue
        jobs.append(RawJob(
            source=f"portal:{slug}",
            external_id=_make_external_id(item["url"]),
            title=item.get("title", ""),
            company=company_name,
            location=item.get("location", ""),
            url=item["url"],
        ))

    return jobs


STRATEGIES: dict[str, object] = {
    "workday": extract_workday,
    "successfactors": extract_successfactors,
    "generic": extract_generic,
    # SmartRecruiters and Greenhouse/Lever/Ashby are handled by the ATS scraper,
    # but if configured here they fall through to generic.
    "smartrecruiters": extract_generic,
}
