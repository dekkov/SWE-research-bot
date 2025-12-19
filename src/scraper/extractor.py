"""
Job detail extraction - extract full job information from individual job pages.
"""

import logging
from typing import Dict, Optional
from playwright.async_api import Page

from src.storage.models import Job, JobDiscovered
from config.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def extract_job_details(
    page: Page,
    job_discovered: JobDiscovered,
    company_id: int,
    selectors: Dict[str, str],
    max_retries: int = 3
) -> Optional[Job]:
    """
    Extract full job details from job detail page.

    Args:
        page: Playwright page object
        job_discovered: Discovered job with URL
        company_id: Company database ID
        selectors: CSS selectors for detail page
        max_retries: Maximum retry attempts

    Returns:
        Job object with full details, or None if extraction fails
    """
    logger.info(f"Extracting details for: {job_discovered.title}")

    for attempt in range(max_retries):
        try:
            # Navigate to job detail page - wait for network to be idle
            await page.goto(job_discovered.url, wait_until="networkidle", timeout=60000)

            # Give JavaScript time to render (longer wait for dynamic content)
            await page.wait_for_timeout(3000)

            # Scroll to bottom to trigger any lazy-loaded content
            await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await page.wait_for_timeout(2000)

            # Wait for job description to appear (REQUIRED - will retry if missing)
            desc_selector = selectors['detail_description']
            await page.wait_for_selector(desc_selector, state='visible', timeout=15000)

            # Extract fields
            job_data = await _extract_fields(page, selectors)

            # Use discovered data as fallback
            title = job_data.get('title') or job_discovered.title
            team = job_data.get('team') or job_discovered.team
            location = job_data.get('location') or job_discovered.location

            # Create Job object
            job = Job(
                company_id=company_id,
                job_url=job_discovered.url,
                job_url_hash=job_discovered.url_hash,
                title=title,
                team=team,
                location=location,
                employment_type=job_data.get('employment_type', 'Full-time'),
                raw_description=job_data.get('raw_description'),
                processed=False
            )

            logger.info(f"Successfully extracted: {job.title}")
            return job

        except Exception as e:
            logger.warning(f"Attempt {attempt + 1}/{max_retries} failed for {job_discovered.url}: {e}")

            if attempt < max_retries - 1:
                # Wait before retry
                await page.wait_for_timeout(2000)
            else:
                logger.error(f"Failed to extract job after {max_retries} attempts: {job_discovered.url}")
                return None

    return None


async def _extract_fields(page: Page, selectors: Dict[str, str]) -> Dict[str, str]:
    """
    Extract all fields from job detail page.

    Args:
        page: Playwright page object
        selectors: CSS selectors dict

    Returns:
        Dict of extracted fields
    """
    fields = {}

    # Title
    title_elem = await page.query_selector(selectors.get('detail_title', 'h1'))
    if title_elem:
        fields['title'] = await title_elem.inner_text()
        fields['title'] = fields['title'].strip()

    # Description (required) - try multiple selectors
    desc_elem = await page.query_selector(selectors['detail_description'])
    if desc_elem:
        fields['raw_description'] = await desc_elem.inner_text()
        fields['raw_description'] = fields['raw_description'].strip()
    else:
        # Fallback: try to get main or body content
        for fallback_selector in ['main', 'article', 'body']:
            elem = await page.query_selector(fallback_selector)
            if elem:
                fields['raw_description'] = await elem.inner_text()
                fields['raw_description'] = fields['raw_description'].strip()
                logger.debug(f"Used fallback selector '{fallback_selector}' for description")
                break

    # Team/Department (optional)
    if 'detail_team' in selectors and selectors['detail_team']:
        team_elem = await page.query_selector(selectors['detail_team'])
        if team_elem:
            fields['team'] = await team_elem.inner_text()
            fields['team'] = fields['team'].strip()

    # Location (optional)
    if 'detail_location' in selectors and selectors['detail_location']:
        location_elem = await page.query_selector(selectors['detail_location'])
        if location_elem:
            fields['location'] = await location_elem.inner_text()
            fields['location'] = fields['location'].strip()

    # Employment type (optional)
    if 'detail_type' in selectors and selectors['detail_type']:
        type_elem = await page.query_selector(selectors['detail_type'])
        if type_elem:
            fields['employment_type'] = await type_elem.inner_text()
            fields['employment_type'] = fields['employment_type'].strip()

    return fields


async def extract_multiple_jobs(
    jobs_discovered: list[JobDiscovered],
    company_id: int,
    selectors: Dict[str, str],
    batch_size: int = 20
) -> list[Job]:
    """
    Extract details for multiple jobs in batches to prevent memory issues.

    Args:
        jobs_discovered: List of discovered jobs
        company_id: Company database ID
        selectors: CSS selectors
        batch_size: Number of jobs to extract before restarting browser (default: 20)

    Returns:
        List of extracted jobs
    """
    from .browser import BrowserManager

    logger.info(f"Extracting details for {len(jobs_discovered)} jobs in batches of {batch_size}...")

    all_extracted_jobs = []

    # Process in batches
    for batch_num in range(0, len(jobs_discovered), batch_size):
        batch = jobs_discovered[batch_num:batch_num + batch_size]
        batch_end = min(batch_num + batch_size, len(jobs_discovered))

        logger.info(f"Processing batch {batch_num // batch_size + 1} (jobs {batch_num + 1}-{batch_end})")

        # Use fresh browser for each batch to prevent memory buildup
        async with BrowserManager() as browser:
            for i, job_disc in enumerate(batch):
                overall_idx = batch_num + i
                logger.info(f"Progress: {overall_idx + 1}/{len(jobs_discovered)}")

                job = await extract_job_details(
                    browser.page,
                    job_disc,
                    company_id,
                    selectors
                )

                if job:
                    all_extracted_jobs.append(job)

                # Politeness delay
                if i < len(batch) - 1:
                    await browser.page.wait_for_timeout(
                        settings.scraper_scroll_pause * 1000
                    )

        logger.info(f"Batch complete. Total extracted so far: {len(all_extracted_jobs)}/{len(jobs_discovered)}")

    logger.info(f"All batches complete. Successfully extracted {len(all_extracted_jobs)}/{len(jobs_discovered)} jobs")
    return all_extracted_jobs
