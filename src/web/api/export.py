"""
Export API endpoints.
"""

import json
import csv
import io
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List

from config.settings import get_settings
from src.storage.database import Database

router = APIRouter()


class ExportRequest(BaseModel):
    job_ids: List[int]
    format: str = "json"  # json, csv, markdown


def _get_db():
    """Get database instance"""
    settings = get_settings()
    return Database(settings.database_path)


@router.post("/")
async def export_jobs(request: ExportRequest):
    """Export selected jobs in specified format"""
    db = _get_db()

    # Fetch jobs with details
    jobs_data = []
    for job_id in request.job_ids:
        job = db.get_job(job_id)
        if not job:
            continue

        requirements = db.get_requirements(job_id)
        categories = db.get_job_categories(job_id)
        company = db.get_company(job.company_id)

        jobs_data.append({
            'job': job,
            'requirements': requirements,
            'categories': categories,
            'company': company
        })

    if not jobs_data:
        raise HTTPException(status_code=404, detail="No jobs found")

    # Generate export based on format
    if request.format == "json":
        return _export_json(jobs_data)
    elif request.format == "csv":
        return _export_csv(jobs_data)
    elif request.format == "markdown":
        return _export_markdown(jobs_data)
    else:
        raise HTTPException(status_code=400, detail="Invalid format")


def _export_json(jobs_data):
    """Export as JSON"""
    output = []

    for data in jobs_data:
        job_dict = data['job'].dict()
        job_dict['company_name'] = data['company'].name if data['company'] else None
        job_dict['requirements'] = data['requirements'].dict() if data['requirements'] else None
        job_dict['categories'] = [c.dict() for c in data['categories']]

        output.append(job_dict)

    content = json.dumps(output, indent=2, default=str)

    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={
            "Content-Disposition": "attachment; filename=jobs_export.json"
        }
    )


def _export_csv(jobs_data):
    """Export as CSV"""
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        'Company', 'Title', 'Team', 'Location', 'Experience Level',
        'Employment Type', 'Primary Category', 'Required Skills',
        'Preferred Skills', 'URL'
    ])

    # Rows
    for data in jobs_data:
        job = data['job']
        company = data['company']
        requirements = data['requirements']
        categories = data['categories']

        primary_category = next(
            (c.category for c in categories if c.is_primary),
            ''
        )

        required_skills = ', '.join(requirements.required_skills) if requirements else ''
        preferred_skills = ', '.join(requirements.preferred_skills) if requirements else ''

        writer.writerow([
            company.name if company else '',
            job.title,
            job.team or '',
            job.location or '',
            job.experience_level or '',
            job.employment_type or '',
            primary_category,
            required_skills,
            preferred_skills,
            job.job_url
        ])

    content = output.getvalue()

    return StreamingResponse(
        iter([content]),
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=jobs_export.csv"
        }
    )


def _export_markdown(jobs_data):
    """Export as Markdown"""
    lines = ["# Job Export\n"]

    for data in jobs_data:
        job = data['job']
        company = data['company']
        requirements = data['requirements']
        categories = data['categories']

        lines.append(f"## {job.title}\n")
        lines.append(f"**Company:** {company.name if company else 'Unknown'}\n")
        lines.append(f"**Team:** {job.team or 'N/A'}\n")
        lines.append(f"**Location:** {job.location or 'N/A'}\n")
        lines.append(f"**Experience Level:** {job.experience_level or 'N/A'}\n")
        lines.append(f"**URL:** {job.job_url}\n")

        if categories:
            cats = ', '.join(c.category for c in categories)
            lines.append(f"**Categories:** {cats}\n")

        if requirements:
            if requirements.required_skills:
                lines.append(f"\n**Required Skills:**\n")
                for skill in requirements.required_skills:
                    lines.append(f"- {skill}\n")

            if requirements.responsibilities:
                lines.append(f"\n**Responsibilities:**\n")
                for resp in requirements.responsibilities[:5]:
                    lines.append(f"- {resp}\n")

        lines.append("\n---\n\n")

    content = '\n'.join(lines)

    return StreamingResponse(
        iter([content]),
        media_type="text/markdown",
        headers={
            "Content-Disposition": "attachment; filename=jobs_export.md"
        }
    )
