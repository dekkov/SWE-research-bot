"""
Companies API endpoints.
"""

import asyncio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict

from config.settings import get_settings
from src.storage.database import Database
from src.storage.models import Company
from src.cli.commands import _scrape_async

router = APIRouter()


class ScrapeRequest(BaseModel):
    company_name: str


def _get_db():
    """Get database instance"""
    settings = get_settings()
    return Database(settings.database_path)


@router.get("/")
async def list_companies():
    """List all companies"""
    db = _get_db()
    companies = db.get_all_companies()

    return {
        'companies': [c.dict() for c in companies]
    }


@router.post("/scrape")
async def trigger_scrape(request: ScrapeRequest):
    """Trigger scrape for a company"""
    db = _get_db()

    company = db.get_company_by_name(request.company_name)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Run scrape in background
    # For now, run synchronously (in production, use background tasks)
    try:
        await _scrape_async(request.company_name)
        return {"status": "completed", "company": request.company_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/add")
async def add_company(company: Company):
    """Add a new company"""
    db = _get_db()

    # Check if exists
    existing = db.get_company_by_name(company.name)
    if existing:
        raise HTTPException(status_code=400, detail="Company already exists")

    company_id = db.add_company(company)

    return {"id": company_id, "name": company.name}
