"""
CLI commands using Click.
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Optional

import click

from config.settings import get_settings
from src.storage.database import Database, generate_url_hash
from src.storage.models import Company, Job
from src.scraper.discovery import discover_all_jobs_for_company
from src.scraper.extractor import extract_multiple_jobs
from src.analyzer.parser import parse_multiple_jobs, requirements_dict_to_model
from src.analyzer.categorizer import categorize_multiple_jobs, categorization_to_models
from src.analyzer.summarizer import generate_all_summaries

logger = logging.getLogger(__name__)


def setup_logging(level: str = "INFO"):
    """Setup logging configuration"""
    settings = get_settings()

    # Create logs directory
    log_file = Path(settings.log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )


@click.group()
@click.option('--log-level', default='INFO', help='Logging level')
def cli(log_level):
    """SWE Job Research Bot - Scrape and analyze software engineering jobs"""
    setup_logging(log_level)


@cli.command()
def init():
    """Initialize database and load initial company data"""
    click.echo("Initializing database...")

    settings = get_settings()
    db = Database(settings.database_path)

    # Create tables
    db.initialize()
    click.echo(f"✅ Database initialized: {settings.database_path}")

    # Load companies from companies.json
    companies_file = Path("config/companies.json")

    if companies_file.exists():
        with open(companies_file) as f:
            data = json.load(f)

        for company_data in data.get('companies', []):
            company = Company(**company_data)

            # Check if company already exists
            existing = db.get_company_by_name(company.name)

            if existing:
                click.echo(f"   Company already exists: {company.name}")
            else:
                company_id = db.add_company(company)
                click.echo(f"✅ Added company: {company.name} (ID: {company_id})")

    click.echo("\n✅ Initialization complete!")
    click.echo(f"\nNext steps:")
    click.echo(f"  1. Set up your .env file (copy from .env.example)")
    click.echo(f"  2. Run: python main.py scrape")


@cli.command()
@click.option('--company', help='Company name to scrape (default: all active)')
@click.option('--limit', type=int, help='Limit number of jobs to scrape (useful for testing)')
def scrape(company: Optional[str], limit: Optional[int]):
    """Scrape job listings from company careers pages"""
    asyncio.run(_scrape_async(company, limit))


async def _scrape_async(company_name: Optional[str], job_limit: Optional[int] = None):
    """Async scrape implementation"""
    settings = get_settings()
    db = Database(settings.database_path)

    # Get companies to scrape
    if company_name:
        company = db.get_company_by_name(company_name)
        if not company:
            click.echo(f"❌ Company not found: {company_name}")
            return
        companies = [company]
    else:
        companies = db.get_all_companies(active_only=True)

    if not companies:
        click.echo("❌ No active companies found")
        return

    categories = settings.get_job_categories()
    click.echo(f"Searching {len(categories)} categories: {', '.join(categories)}")
    if job_limit:
        click.echo(f"🧪 TEST MODE: Limiting to {job_limit} jobs\n")
    else:
        click.echo()

    for company in companies:
        click.echo(f"{'='*60}")
        click.echo(f"Scraping: {company.name}")
        click.echo(f"{'='*60}\n")

        # Create scrape run
        run_id = db.create_scrape_run(company.id, "Multiple categories")

        try:
            # Discover jobs
            click.echo(f"🔍 Discovering jobs...")
            jobs_discovered = await discover_all_jobs_for_company(company, categories)

            db.update_scrape_run(run_id, jobs_discovered=len(jobs_discovered))
            click.echo(f"✅ Discovered {len(jobs_discovered)} total jobs\n")

            # Filter out already-scraped jobs
            new_jobs = [
                job for job in jobs_discovered
                if not db.job_exists(job.url_hash)
            ]

            already_scraped = len(jobs_discovered) - len(new_jobs)

            # Apply limit if in test mode
            if job_limit and len(new_jobs) > job_limit:
                click.echo(f"📝 Found {len(new_jobs)} new jobs, limiting to {job_limit} for testing")
                new_jobs = new_jobs[:job_limit]
            else:
                click.echo(f"📝 New jobs to scrape: {len(new_jobs)}")

            click.echo(f"⏭️  Already scraped: {already_scraped}\n")

            if not new_jobs:
                click.echo("✅ No new jobs to scrape!")
                db.update_scrape_run(run_id, status="completed")
                continue

            # Extract and save job details in batches
            click.echo(f"📥 Extracting job details in batches...")

            batch_size = 20
            saved_count = 0

            for batch_start in range(0, len(new_jobs), batch_size):
                batch_end = min(batch_start + batch_size, len(new_jobs))
                batch = new_jobs[batch_start:batch_end]

                click.echo(f"  Batch {batch_start // batch_size + 1}: Extracting jobs {batch_start + 1}-{batch_end}...")

                # Extract this batch
                jobs_extracted = await extract_multiple_jobs(
                    batch,
                    company.id,
                    company.selectors,
                    batch_size=batch_size  # Process the whole batch at once
                )

                # Save to database immediately after each batch
                for job in jobs_extracted:
                    job_id = db.add_job(job)
                    saved_count += 1

                click.echo(f"  ✅ Batch saved: {len(jobs_extracted)} jobs (Total saved: {saved_count})")

            db.update_scrape_run(run_id, jobs_scraped=saved_count, status="completed")
            db.update_company_last_scraped(company.id)

            click.echo(f"\n✅ Scraped {saved_count} new jobs for {company.name}")

        except Exception as e:
            logger.error(f"Scraping failed for {company.name}: {e}")
            db.update_scrape_run(run_id, status="failed", error_message=str(e))
            click.echo(f"\n❌ Scraping failed: {e}")

    click.echo(f"\n{'='*60}")
    click.echo("✅ Scraping complete!")


@cli.command()
@click.option('--company', help='Company name to analyze (default: all)')
@click.option('--limit', type=int, help='Limit number of jobs to analyze')
def analyze(company: Optional[str], limit: Optional[int]):
    """Analyze scraped jobs (parse requirements and categorize)"""
    asyncio.run(_analyze_async(company, limit))


async def _analyze_async(company_name: Optional[str], limit: Optional[int]):
    """Async analyze implementation"""
    settings = get_settings()
    db = Database(settings.database_path)

    # Get unprocessed jobs
    jobs = db.get_unprocessed_jobs(limit=limit)

    if not jobs:
        click.echo("✅ No unprocessed jobs found!")
        return

    click.echo(f"{'='*60}")
    click.echo(f"Analyzing {len(jobs)} jobs")
    click.echo(f"{'='*60}\n")

    # Parse requirements
    click.echo("🤖 Parsing job requirements with LLM...")
    parsed_results = await parse_multiple_jobs(jobs)

    click.echo(f"✅ Parsed {len(parsed_results)} jobs\n")

    # Save requirements and update experience levels
    jobs_with_requirements = []

    for job in jobs:
        if job.id in parsed_results:
            parsed = parsed_results[job.id]

            # Save requirements
            requirements = requirements_dict_to_model(job.id, parsed)
            db.add_requirements(requirements)

            # Update job experience level
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE jobs SET experience_level = ? WHERE id = ?",
                    (parsed.get('experience_level'), job.id)
                )

            # Update job object for categorization
            job.experience_level = parsed.get('experience_level')

            jobs_with_requirements.append((job, requirements))

    # Categorize jobs
    click.echo("🏷️  Categorizing jobs...")
    categorizations = await categorize_multiple_jobs(jobs_with_requirements)

    click.echo(f"✅ Categorized {len(categorizations)} jobs\n")

    # Save categories
    for job_id, categorization in categorizations.items():
        job_categories = categorization_to_models(job_id, categorization)
        for job_category in job_categories:
            db.add_job_category(job_category)

    # Mark jobs as processed
    for job in jobs:
        db.mark_job_processed(job.id)

    click.echo(f"{'='*60}")
    click.echo("✅ Analysis complete!")


@cli.command()
@click.option('--company', help='Company name (default: all)')
def summarize(company: Optional[str]):
    """Generate category summaries"""
    asyncio.run(_summarize_async(company))


async def _summarize_async(company_name: Optional[str]):
    """Async summarize implementation"""
    settings = get_settings()
    db = Database(settings.database_path)

    company_id = None
    if company_name:
        company = db.get_company_by_name(company_name)
        if not company:
            click.echo(f"❌ Company not found: {company_name}")
            return
        company_id = company.id

    click.echo(f"{'='*60}")
    click.echo(f"Generating category summaries")
    click.echo(f"{'='*60}\n")

    summaries = await generate_all_summaries(db, company_id=company_id)

    # Save summaries
    for summary in summaries:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO category_summaries
                (company_id, category, job_count, core_technologies, summary, last_updated)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
            """, (
                summary.company_id,
                summary.category,
                summary.job_count,
                json.dumps(summary.core_technologies),
                summary.summary
            ))

    click.echo(f"✅ Generated {len(summaries)} summaries\n")

    # Display summaries
    for summary in summaries:
        click.echo(f"\n{'='*60}")
        click.echo(f"{summary.category} ({summary.job_count} jobs)")
        click.echo(f"{'='*60}")
        click.echo(f"\nTop Skills: {', '.join(summary.core_technologies[:10])}")
        click.echo(f"\n{summary.summary}\n")


@cli.command()
def status():
    """Show statistics and status"""
    settings = get_settings()
    db = Database(settings.database_path)

    stats = db.get_stats()

    click.echo(f"\n{'='*60}")
    click.echo("📊 Job Research Bot Status")
    click.echo(f"{'='*60}\n")

    click.echo(f"Total Jobs: {stats['total_jobs']}")
    click.echo(f"Active Companies: {stats['total_companies']}")

    if stats['last_scrape']:
        click.echo(f"Last Scrape: {stats['last_scrape']}")

    click.echo(f"\nJobs by Company:")
    for company, count in stats['jobs_by_company'].items():
        click.echo(f"  {company}: {count}")

    click.echo(f"\nJobs by Experience Level:")
    for level, count in stats['jobs_by_level'].items():
        click.echo(f"  {level}: {count}")

    click.echo(f"\nJobs by Category:")
    for category, count in stats['jobs_by_category'].items():
        click.echo(f"  {category}: {count}")

    click.echo()


@cli.command()
@click.option('--limit', type=int, help='Limit number of jobs to scrape (useful for testing)')
def run_all(limit: Optional[int]):
    """Run full pipeline: scrape -> analyze -> summarize"""
    click.echo("Running full pipeline...\n")

    # Scrape
    ctx = click.get_current_context()
    ctx.invoke(scrape, limit=limit)

    click.echo("\n")

    # Analyze
    ctx.invoke(analyze)

    click.echo("\n")

    # Summarize
    ctx.invoke(summarize)

    click.echo("\n")

    # Status
    ctx.invoke(status)

    click.echo("\n✅ Full pipeline complete!")


@cli.command()
def rescrape_failed():
    """Re-scrape jobs that failed to extract descriptions"""
    asyncio.run(_rescrape_failed_async())


async def _rescrape_failed_async():
    """Re-scrape jobs with missing descriptions"""
    settings = get_settings()
    db = Database(settings.database_path)

    # Find jobs with missing descriptions
    import sqlite3
    conn = sqlite3.connect(settings.database_path)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, job_url, company_id
        FROM jobs
        WHERE raw_description IS NULL OR length(raw_description) < 100
    ''')
    failed_jobs = cursor.fetchall()
    conn.close()

    if not failed_jobs:
        click.echo("✅ No failed jobs found!")
        return

    click.echo(f"Found {len(failed_jobs)} jobs with missing descriptions\n")

    # Group by company
    from collections import defaultdict
    jobs_by_company = defaultdict(list)
    for job_id, job_url, company_id in failed_jobs:
        jobs_by_company[company_id].append((job_id, job_url))

    # Re-extract for each company
    for company_id, jobs in jobs_by_company.items():
        company = db.get_company(company_id)
        click.echo(f"Re-scraping {len(jobs)} jobs for {company.name}...")

        from src.scraper.browser import BrowserManager
        from src.storage.models import JobDiscovered

        # Process each job with a fresh browser to prevent session corruption
        for idx, (job_id, job_url) in enumerate(jobs, 1):
            click.echo(f"  [{idx}/{len(jobs)}] Re-extracting job {job_id}...")

            try:
                # Create fresh browser for each job
                async with BrowserManager() as browser:
                    # Navigate and wait for network to be idle
                    await browser.page.goto(job_url, wait_until="networkidle", timeout=60000)
                    await browser.page.wait_for_timeout(3000)

                    # Scroll to trigger lazy-loaded content
                    await browser.page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                    await browser.page.wait_for_timeout(2000)

                    # Wait for description element to be visible
                    desc_selector = company.selectors.get('detail_description')
                    if desc_selector:
                        await browser.page.wait_for_selector(desc_selector, state='visible', timeout=15000)

                    # Extract description
                    from src.scraper.extractor import _extract_fields
                    fields = await _extract_fields(browser.page, company.selectors)

                    if fields.get('raw_description'):
                        # Update database
                        conn = sqlite3.connect(settings.database_path)
                        cursor = conn.cursor()
                        cursor.execute('''
                            UPDATE jobs
                            SET raw_description = ?, processed = 0
                            WHERE id = ?
                        ''', (fields['raw_description'], job_id))
                        conn.commit()
                        conn.close()
                        click.echo(f"    ✅ Updated job {job_id} ({len(fields['raw_description'])} chars)")
                    else:
                        click.echo(f"    ❌ Still no description found for job {job_id}")

            except Exception as e:
                logger.error(f"Failed to rescrape job {job_id}: {e}")
                click.echo(f"    ❌ Failed: {e}")

            # Politeness delay between jobs
            import asyncio
            await asyncio.sleep(2)

    click.echo(f"\n✅ Re-scraping complete! Run 'python main.py analyze' to process the updated jobs.")


@cli.command()
@click.option('--host', default='127.0.0.1', help='Host to bind to')
@click.option('--port', type=int, default=8000, help='Port to bind to')
def web(host: str, port: int):
    """Launch web dashboard"""
    import uvicorn
    from src.web.app import app

    click.echo(f"🚀 Starting web dashboard...")
    click.echo(f"   URL: http://{host}:{port}")
    click.echo(f"\n   Press Ctrl+C to stop\n")

    uvicorn.run(app, host=host, port=port)


if __name__ == '__main__':
    cli()
