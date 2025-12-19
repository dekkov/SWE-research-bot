"""
Job discovery - find all job listings on careers pages.
"""

import logging
from typing import List, Dict
from urllib.parse import urljoin
from playwright.async_api import Page

from src.storage.models import Company, JobDiscovered
from src.storage.database import generate_url_hash
from .browser import BrowserManager

logger = logging.getLogger(__name__)


async def discover_jobs(
    page: Page,
    search_url: str,
    selectors: Dict[str, str]
) -> List[JobDiscovered]:
    """
    Discover all job listings on a search page.

    Args:
        page: Playwright page object
        search_url: Full search URL
        selectors: Dict of CSS selectors

    Returns:
        List of discovered jobs
    """
    logger.info(f"Discovering jobs at: {search_url}")

    try:
        # Navigate to search page
        await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)

        # Give JavaScript time to render
        await page.wait_for_timeout(3000)

        # Wait for job cards to load
        job_card_selector = selectors['job_card']

        try:
            await page.wait_for_selector(job_card_selector, timeout=10000)
        except Exception:
            logger.warning(f"No jobs found with selector: {job_card_selector}")
            return []

        # Perform infinite scroll
        browser_manager = BrowserManager()
        total_cards = await browser_manager.infinite_scroll(page, job_card_selector)

        logger.info(f"Found {total_cards} job cards after scrolling")

        # Extract job data
        job_elements = await page.query_selector_all(job_card_selector)
        jobs = []

        for i, element in enumerate(job_elements):
            try:
                job = await extract_job_from_card(element, selectors, search_url)
                if job:
                    jobs.append(job)
                    logger.debug(f"Extracted job {i+1}/{len(job_elements)}: {job.title}")
            except Exception as e:
                logger.error(f"Error extracting job card {i+1}: {e}")
                continue

        logger.info(f"Successfully extracted {len(jobs)} jobs")
        return jobs

    except Exception as e:
        logger.error(f"Error discovering jobs: {e}")
        return []


async def extract_job_from_card(
    element,
    selectors: Dict[str, str],
    base_url: str
) -> JobDiscovered:
    """
    Extract job data from a single job card element.

    Args:
        element: Playwright element locator
        selectors: CSS selectors dict
        base_url: Base URL for normalizing relative links

    Returns:
        JobDiscovered object
    """
    # Extract title
    title = None
    title_elem = await element.query_selector(selectors['job_title'])
    if title_elem:
        title = await title_elem.inner_text()
        title = title.strip() if title else None

    # Extract job URL
    job_url = None
    link_elem = await element.query_selector(selectors['job_link'])
    if link_elem:
        job_url = await link_elem.get_attribute('href')

        # Normalize URL (convert relative to absolute)
        if job_url and not job_url.startswith('http'):
            job_url = urljoin(base_url, job_url)

    # Extract location (optional)
    location = None
    if 'job_location' in selectors and selectors['job_location']:
        location_elem = await element.query_selector(selectors['job_location'])
        if location_elem:
            location = await location_elem.inner_text()
            location = location.strip() if location else None

    # Extract team (optional)
    team = None
    if 'job_team' in selectors and selectors['job_team']:
        team_elem = await element.query_selector(selectors['job_team'])
        if team_elem:
            team = await team_elem.inner_text()
            team = team.strip() if team else None

    # Validate required fields
    if not job_url or not title:
        logger.warning(f"Missing required fields (url or title) for job card")
        return None

    # Generate URL hash for deduplication
    url_hash = generate_url_hash(job_url)

    return JobDiscovered(
        url=job_url,
        title=title,
        location=location,
        team=team,
        url_hash=url_hash
    )


async def discover_all_jobs_for_company(
    company: Company,
    search_categories: List[str]
) -> List[JobDiscovered]:
    """
    Discover all jobs for a company by searching multiple categories.

    Args:
        company: Company object with careers_url and selectors
        search_categories: List of categories to search (e.g., "Backend Engineer")

    Returns:
        Deduplicated list of discovered jobs
    """
    logger.info(f"Discovering jobs for {company.name} across {len(search_categories)} categories")

    async with BrowserManager() as browser:
        all_jobs = {}  # Use dict for deduplication by URL hash

        for category in search_categories:
            logger.info(f"Searching category: {category}")

            # Build search URL
            search_url = f"{company.careers_url}{category.replace(' ', '+')}"

            # Discover jobs for this category
            jobs = await discover_jobs(browser.page, search_url, company.selectors)

            logger.info(f"  Found {len(jobs)} jobs for {category}")

            # Add to deduplicated collection
            for job in jobs:
                if job.url_hash not in all_jobs:
                    # Add search_category hint for categorization
                    job.search_category = category
                    all_jobs[job.url_hash] = job
                else:
                    logger.debug(f"  Duplicate job skipped: {job.title}")

        total_unique = len(all_jobs)
        logger.info(f"Total unique jobs discovered for {company.name}: {total_unique}")

        return list(all_jobs.values())
