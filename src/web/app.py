"""
FastAPI web application for job dashboard.
"""

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

# Import API routers
from src.web.api import jobs, search, export, companies

# Create FastAPI app
app = FastAPI(
    title="SWE Job Research Bot",
    description="Search and analyze software engineering jobs",
    version="1.0.0"
)

# Setup templates and static files
BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Mount static files (CSS, JS)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Include API routers
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(export.router, prefix="/api/export", tags=["export"])
app.include_router(companies.router, prefix="/api/companies", tags=["companies"])


@app.get("/")
async def home(request: Request):
    """Dashboard home page"""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/jobs")
async def jobs_page(request: Request):
    """Jobs browser page"""
    return templates.TemplateResponse("jobs.html", {"request": request})


@app.get("/companies")
async def companies_page(request: Request):
    """Company management page"""
    return templates.TemplateResponse("companies.html", {"request": request})


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}
