"""
Jobs API endpoints.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
import json

from config.settings import get_settings
from src.storage.database import Database
from src.storage.models import JobResponse, JobListResponse

router = APIRouter()


def _get_db():
    """Get database instance"""
    settings = get_settings()
    return Database(settings.database_path)


@router.get("/stats")
async def get_stats():
    """Get dashboard statistics"""
    db = _get_db()
    return db.get_stats()


@router.get("/", response_model=JobListResponse)
async def list_jobs(
    company: Optional[str] = None,
    level: Optional[str] = None,
    category: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100)
):
    """
    List jobs with filters and pagination.
    """
    db = _get_db()

    # Get company_id if company name provided
    company_id = None
    if company:
        comp = db.get_company_by_name(company)
        if comp:
            company_id = comp.id

    # Calculate offset
    offset = (page - 1) * page_size

    # Search jobs
    jobs, total = db.search_jobs(
        company_id=company_id,
        experience_level=level,
        category=category,
        limit=page_size,
        offset=offset
    )

    # Build response
    job_responses = []
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

        job_responses.append(JobResponse(
            job=job,
            requirements=requirements,
            categories=categories,
            company_name=company_obj.name if company_obj else None,
            tech_stack=tech_stack
        ))

    total_pages = (total + page_size - 1) // page_size

    return JobListResponse(
        jobs=job_responses,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.get("/{job_id}")
async def get_job(job_id: int):
    """Get single job with full details"""
    db = _get_db()

    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    requirements = db.get_requirements(job_id)
    categories = db.get_job_categories(job_id)
    company = db.get_company(job.company_id)

    # Extract tech stack from requirements
    tech_stack = []
    if requirements:
        tech_stack = requirements.required_skills[:8]
        if len(tech_stack) < 8 and requirements.preferred_skills:
            remaining = 8 - len(tech_stack)
            tech_stack.extend(requirements.preferred_skills[:remaining])

    return JobResponse(
        job=job,
        requirements=requirements,
        categories=categories,
        company_name=company.name if company else None,
        tech_stack=tech_stack
    )
