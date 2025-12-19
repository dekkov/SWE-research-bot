"""
SQLite database operations and schema management.
"""

import sqlite3
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Tuple
from contextlib import contextmanager

from .models import (
    Company, Job, Requirements, JobCategory,
    CategorySummary, ScrapeRun, JobDiscovered
)


class Database:
    """SQLite database manager"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        # Ensure data directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def get_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Access columns by name
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def initialize(self):
        """Create all tables"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Companies table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS companies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    careers_url TEXT NOT NULL,
                    selectors TEXT NOT NULL,
                    active BOOLEAN DEFAULT TRUE,
                    last_scraped TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Jobs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    job_url TEXT UNIQUE NOT NULL,
                    job_url_hash TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    team TEXT,
                    location TEXT,
                    employment_type TEXT,
                    experience_level TEXT,
                    raw_description TEXT,
                    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    processed BOOLEAN DEFAULT FALSE,
                    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
                )
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_company_id ON jobs(company_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_experience_level ON jobs(experience_level)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_processed ON jobs(processed)")

            # Requirements table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS requirements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL,
                    responsibilities TEXT,
                    required_skills TEXT,
                    preferred_skills TEXT,
                    experience TEXT,
                    education TEXT,
                    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
                )
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_requirements_job_id ON requirements(job_id)")

            # Job categories table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS job_categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL,
                    category TEXT NOT NULL,
                    is_primary BOOLEAN DEFAULT FALSE,
                    confidence REAL,
                    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
                )
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_job_categories_job_id ON job_categories(job_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_job_categories_category ON job_categories(category)")

            # Category summaries table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS category_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER,
                    category TEXT NOT NULL,
                    job_count INTEGER,
                    core_technologies TEXT,
                    summary TEXT,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
                    UNIQUE(company_id, category)
                )
            """)

            # Scrape runs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scrape_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER,
                    search_term TEXT,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    jobs_discovered INTEGER DEFAULT 0,
                    jobs_scraped INTEGER DEFAULT 0,
                    status TEXT,
                    error_message TEXT,
                    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
                )
            """)

    # ==================== Company CRUD ====================

    def add_company(self, company: Company) -> int:
        """Add a new company"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO companies (name, careers_url, selectors, active)
                VALUES (?, ?, ?, ?)
            """, (
                company.name,
                company.careers_url,
                json.dumps(company.selectors),
                company.active
            ))
            return cursor.lastrowid

    def get_company(self, company_id: int) -> Optional[Company]:
        """Get company by ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM companies WHERE id = ?", (company_id,))
            row = cursor.fetchone()
            if row:
                return Company(
                    id=row['id'],
                    name=row['name'],
                    careers_url=row['careers_url'],
                    selectors=json.loads(row['selectors']),
                    active=bool(row['active']),
                    last_scraped=row['last_scraped'],
                    created_at=row['created_at']
                )
            return None

    def get_company_by_name(self, name: str) -> Optional[Company]:
        """Get company by name"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM companies WHERE name = ?", (name,))
            row = cursor.fetchone()
            if row:
                return Company(
                    id=row['id'],
                    name=row['name'],
                    careers_url=row['careers_url'],
                    selectors=json.loads(row['selectors']),
                    active=bool(row['active']),
                    last_scraped=row['last_scraped'],
                    created_at=row['created_at']
                )
            return None

    def get_all_companies(self, active_only: bool = False) -> List[Company]:
        """Get all companies"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM companies"
            if active_only:
                query += " WHERE active = 1"
            cursor.execute(query)
            rows = cursor.fetchall()
            return [
                Company(
                    id=row['id'],
                    name=row['name'],
                    careers_url=row['careers_url'],
                    selectors=json.loads(row['selectors']),
                    active=bool(row['active']),
                    last_scraped=row['last_scraped'],
                    created_at=row['created_at']
                )
                for row in rows
            ]

    def update_company_last_scraped(self, company_id: int):
        """Update last_scraped timestamp"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE companies SET last_scraped = ? WHERE id = ?
            """, (datetime.now().isoformat(), company_id))

    # ==================== Job CRUD ====================

    def job_exists(self, url_hash: str) -> bool:
        """Check if job already exists"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM jobs WHERE job_url_hash = ?", (url_hash,))
            count = cursor.fetchone()[0]
            return count > 0

    def add_job(self, job: Job) -> int:
        """Add a new job"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO jobs (
                    company_id, job_url, job_url_hash, title, team, location,
                    employment_type, experience_level, raw_description, processed
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job.company_id, job.job_url, job.job_url_hash, job.title,
                job.team, job.location, job.employment_type, job.experience_level,
                job.raw_description, job.processed
            ))
            return cursor.lastrowid

    def get_job(self, job_id: int) -> Optional[Job]:
        """Get job by ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_job(row)
            return None

    def get_unprocessed_jobs(self, limit: Optional[int] = None) -> List[Job]:
        """Get jobs that haven't been analyzed yet"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM jobs WHERE processed = 0"
            if limit:
                query += f" LIMIT {limit}"
            cursor.execute(query)
            rows = cursor.fetchall()
            return [self._row_to_job(row) for row in rows]

    def mark_job_processed(self, job_id: int):
        """Mark job as processed"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE jobs SET processed = 1 WHERE id = ?", (job_id,))

    def search_jobs(
        self,
        company_id: Optional[int] = None,
        experience_level: Optional[str] = None,
        category: Optional[str] = None,
        tech_stack: Optional[List[str]] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[List[Job], int]:
        """
        Search jobs with filters.
        Returns (jobs, total_count)
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Build query
            conditions = []
            params = []

            if company_id:
                conditions.append("jobs.company_id = ?")
                params.append(company_id)

            if experience_level:
                conditions.append("jobs.experience_level = ?")
                params.append(experience_level)

            if category:
                conditions.append("""
                    EXISTS (
                        SELECT 1 FROM job_categories jc
                        WHERE jc.job_id = jobs.id AND jc.category = ?
                    )
                """)
                params.append(category)

            if tech_stack:
                for tech in tech_stack:
                    conditions.append("""
                        EXISTS (
                            SELECT 1 FROM requirements r
                            WHERE r.job_id = jobs.id
                            AND (r.required_skills LIKE ? OR r.preferred_skills LIKE ?)
                        )
                    """)
                    search_term = f"%{tech}%"
                    params.extend([search_term, search_term])

            where_clause = " AND ".join(conditions) if conditions else "1=1"

            # Get total count
            count_query = f"SELECT COUNT(*) FROM jobs WHERE {where_clause}"
            cursor.execute(count_query, params)
            total_count = cursor.fetchone()[0]

            # Get jobs
            query = f"""
                SELECT * FROM jobs
                WHERE {where_clause}
                ORDER BY scraped_at DESC
                LIMIT ? OFFSET ?
            """
            cursor.execute(query, params + [limit, offset])
            rows = cursor.fetchall()
            jobs = [self._row_to_job(row) for row in rows]

            return jobs, total_count

    def _row_to_job(self, row) -> Job:
        """Convert database row to Job model"""
        return Job(
            id=row['id'],
            company_id=row['company_id'],
            job_url=row['job_url'],
            job_url_hash=row['job_url_hash'],
            title=row['title'],
            team=row['team'],
            location=row['location'],
            employment_type=row['employment_type'],
            experience_level=row['experience_level'],
            raw_description=row['raw_description'],
            scraped_at=row['scraped_at'],
            processed=bool(row['processed'])
        )

    # ==================== Requirements CRUD ====================

    def add_requirements(self, requirements: Requirements) -> int:
        """Add job requirements"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO requirements (
                    job_id, responsibilities, required_skills,
                    preferred_skills, experience, education
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                requirements.job_id,
                json.dumps(requirements.responsibilities),
                json.dumps(requirements.required_skills),
                json.dumps(requirements.preferred_skills),
                json.dumps(requirements.experience),
                json.dumps(requirements.education)
            ))
            return cursor.lastrowid

    def get_requirements(self, job_id: int) -> Optional[Requirements]:
        """Get requirements for a job"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM requirements WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()
            if row:
                return Requirements(
                    id=row['id'],
                    job_id=row['job_id'],
                    responsibilities=json.loads(row['responsibilities'] or '[]'),
                    required_skills=json.loads(row['required_skills'] or '[]'),
                    preferred_skills=json.loads(row['preferred_skills'] or '[]'),
                    experience=json.loads(row['experience'] or '[]'),
                    education=json.loads(row['education'] or '[]')
                )
            return None

    # ==================== Job Categories CRUD ====================

    def add_job_category(self, job_category: JobCategory) -> int:
        """Add job category"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO job_categories (job_id, category, is_primary, confidence)
                VALUES (?, ?, ?, ?)
            """, (
                job_category.job_id,
                job_category.category,
                job_category.is_primary,
                job_category.confidence
            ))
            return cursor.lastrowid

    def get_job_categories(self, job_id: int) -> List[JobCategory]:
        """Get categories for a job"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM job_categories WHERE job_id = ?
            """, (job_id,))
            rows = cursor.fetchall()
            return [
                JobCategory(
                    id=row['id'],
                    job_id=row['job_id'],
                    category=row['category'],
                    is_primary=bool(row['is_primary']),
                    confidence=row['confidence']
                )
                for row in rows
            ]

    # ==================== Scrape Runs ====================

    def create_scrape_run(self, company_id: int, search_term: str) -> int:
        """Create a new scrape run"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO scrape_runs (company_id, search_term, status)
                VALUES (?, ?, 'running')
            """, (company_id, search_term))
            return cursor.lastrowid

    def update_scrape_run(
        self,
        run_id: int,
        jobs_discovered: Optional[int] = None,
        jobs_scraped: Optional[int] = None,
        status: Optional[str] = None,
        error_message: Optional[str] = None
    ):
        """Update scrape run"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            updates = []
            params = []

            if jobs_discovered is not None:
                updates.append("jobs_discovered = ?")
                params.append(jobs_discovered)

            if jobs_scraped is not None:
                updates.append("jobs_scraped = ?")
                params.append(jobs_scraped)

            if status:
                updates.append("status = ?")
                params.append(status)
                if status == "completed":
                    updates.append("completed_at = ?")
                    params.append(datetime.now().isoformat())

            if error_message:
                updates.append("error_message = ?")
                params.append(error_message)

            if updates:
                query = f"UPDATE scrape_runs SET {', '.join(updates)} WHERE id = ?"
                params.append(run_id)
                cursor.execute(query, params)

    # ==================== Statistics ====================

    def get_stats(self) -> Dict:
        """Get dashboard statistics"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Total jobs
            cursor.execute("SELECT COUNT(*) FROM jobs")
            total_jobs = cursor.fetchone()[0]

            # Total companies
            cursor.execute("SELECT COUNT(*) FROM companies WHERE active = 1")
            total_companies = cursor.fetchone()[0]

            # Jobs by company
            cursor.execute("""
                SELECT c.name, COUNT(j.id) as count
                FROM companies c
                LEFT JOIN jobs j ON c.id = j.company_id
                GROUP BY c.id, c.name
            """)
            jobs_by_company = {row['name']: row['count'] for row in cursor.fetchall()}

            # Jobs by experience level
            cursor.execute("""
                SELECT experience_level, COUNT(*) as count
                FROM jobs
                WHERE experience_level IS NOT NULL
                GROUP BY experience_level
            """)
            jobs_by_level = {row['experience_level']: row['count'] for row in cursor.fetchall()}

            # Jobs by category
            cursor.execute("""
                SELECT category, COUNT(*) as count
                FROM job_categories
                WHERE is_primary = 1
                GROUP BY category
            """)
            jobs_by_category = {row['category']: row['count'] for row in cursor.fetchall()}

            # Last scrape
            cursor.execute("""
                SELECT MAX(last_scraped) as last_scrape
                FROM companies
            """)
            last_scrape = cursor.fetchone()['last_scrape']

            return {
                'total_jobs': total_jobs,
                'total_companies': total_companies,
                'jobs_by_company': jobs_by_company,
                'jobs_by_level': jobs_by_level,
                'jobs_by_category': jobs_by_category,
                'last_scrape': last_scrape
            }


def generate_url_hash(url: str) -> str:
    """Generate SHA-256 hash of URL for deduplication"""
    return hashlib.sha256(url.encode()).hexdigest()
