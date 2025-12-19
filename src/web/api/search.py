"""
Search API endpoints.
"""

from fastapi import APIRouter, Query
from typing import List, Optional

from config.settings import get_settings
from src.storage.database import Database

router = APIRouter()


def _get_db():
    """Get database instance"""
    settings = get_settings()
    return Database(settings.database_path)


@router.get("/")
async def search_jobs(
    tech: Optional[str] = Query(None, description="Comma-separated tech stack"),
    company: Optional[str] = None,
    level: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100)
):
    """
    Search jobs by tech stack and other filters.
    """
    db = _get_db()

    # Parse tech stack
    tech_list = None
    if tech:
        tech_list = [t.strip() for t in tech.split(',') if t.strip()]

    # Get company_id if needed
    company_id = None
    if company:
        comp = db.get_company_by_name(company)
        if comp:
            company_id = comp.id

    # Search
    jobs, total = db.search_jobs(
        company_id=company_id,
        experience_level=level,
        category=category,
        tech_stack=tech_list,
        limit=limit,
        offset=0
    )

    # Build response with requirements
    results = []
    for job in jobs:
        requirements = db.get_requirements(job.id)
        categories = db.get_job_categories(job.id)
        company_obj = db.get_company(job.company_id)

        # Extract tech stack from requirements
        tech_stack = []
        if requirements:
            # Combine required and preferred skills
            tech_stack = requirements.required_skills[:8]  # Top 8 required skills
            if len(tech_stack) < 8 and requirements.preferred_skills:
                # Add preferred skills to fill up to 8 total
                remaining = 8 - len(tech_stack)
                tech_stack.extend(requirements.preferred_skills[:remaining])

        results.append({
            'job': job.dict(),
            'requirements': requirements.dict() if requirements else None,
            'categories': [c.dict() for c in categories],
            'company_name': company_obj.name if company_obj else None,
            'tech_stack': tech_stack  # Add condensed tech stack list
        })

    return {
        'results': results,
        'total': total,
        'tech_filter': tech_list
    }
