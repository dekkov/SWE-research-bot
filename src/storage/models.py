"""
Pydantic models for type safety and data validation.
"""

from datetime import datetime
from typing import List, Optional, Dict
from pydantic import BaseModel, Field


class Company(BaseModel):
    """Company model"""
    id: Optional[int] = None
    name: str
    careers_url: str
    selectors: Dict[str, str]
    active: bool = True
    last_scraped: Optional[datetime] = None
    created_at: Optional[datetime] = None


class JobDiscovered(BaseModel):
    """Job discovered during scraping (before full extraction)"""
    url: str
    title: str
    location: Optional[str] = None
    team: Optional[str] = None
    url_hash: str
    search_category: Optional[str] = None  # Category it was found under


class Job(BaseModel):
    """Full job model"""
    id: Optional[int] = None
    company_id: int
    job_url: str
    job_url_hash: str
    title: str
    team: Optional[str] = None
    location: Optional[str] = None
    employment_type: Optional[str] = "Full-time"
    experience_level: Optional[str] = None
    raw_description: Optional[str] = None
    scraped_at: Optional[datetime] = None
    processed: bool = False


class Requirements(BaseModel):
    """Parsed job requirements"""
    id: Optional[int] = None
    job_id: int
    responsibilities: List[str] = Field(default_factory=list)
    required_skills: List[str] = Field(default_factory=list)
    preferred_skills: List[str] = Field(default_factory=list)
    experience: List[str] = Field(default_factory=list)
    education: List[str] = Field(default_factory=list)


class JobCategory(BaseModel):
    """Job category assignment"""
    id: Optional[int] = None
    job_id: int
    category: str
    is_primary: bool = False
    confidence: Optional[float] = None


class CategorySummary(BaseModel):
    """Category-level summary"""
    id: Optional[int] = None
    company_id: Optional[int] = None
    category: str
    job_count: int = 0
    core_technologies: List[str] = Field(default_factory=list)
    summary: Optional[str] = None
    last_updated: Optional[datetime] = None


class ScrapeRun(BaseModel):
    """Scrape run tracking"""
    id: Optional[int] = None
    company_id: Optional[int] = None
    search_term: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    jobs_discovered: int = 0
    jobs_scraped: int = 0
    status: str = "running"  # running, completed, failed
    error_message: Optional[str] = None


# Response models for API

class JobResponse(BaseModel):
    """Job response with requirements and categories"""
    job: Job
    requirements: Optional[Requirements] = None
    categories: List[JobCategory] = Field(default_factory=list)
    company_name: Optional[str] = None
    tech_stack: List[str] = Field(default_factory=list)


class JobListResponse(BaseModel):
    """Paginated job list response"""
    jobs: List[JobResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class StatsResponse(BaseModel):
    """Dashboard statistics"""
    total_jobs: int
    total_companies: int
    jobs_by_company: Dict[str, int]
    jobs_by_level: Dict[str, int]
    jobs_by_category: Dict[str, int]
    top_skills: List[tuple[str, int]]  # (skill, count)
    last_scrape: Optional[datetime] = None
