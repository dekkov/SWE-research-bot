"""
Generate category-level summaries by aggregating job requirements.
"""

import logging
from typing import List, Dict, Optional
from collections import Counter

from src.storage.models import CategorySummary
from src.storage.database import Database
from .llm_client import get_llm_client

logger = logging.getLogger(__name__)


async def generate_category_summary(
    db: Database,
    category: str,
    company_id: Optional[int] = None
) -> CategorySummary:
    """
    Generate a summary for a job category.

    Args:
        db: Database instance
        category: Category name
        company_id: Optional company ID to filter by

    Returns:
        CategorySummary model
    """
    logger.info(f"Generating summary for category: {category}")

    # Get all jobs in this category
    jobs = await _get_jobs_in_category(db, category, company_id)

    if not jobs:
        logger.warning(f"No jobs found for category: {category}")
        return CategorySummary(
            company_id=company_id,
            category=category,
            job_count=0,
            core_technologies=[],
            summary="No jobs found in this category."
        )

    logger.info(f"Found {len(jobs)} jobs in category: {category}")

    # Aggregate requirements
    aggregated = _aggregate_requirements(jobs)

    # Generate LLM summary
    summary_text = await _generate_llm_summary(
        category=category,
        job_count=len(jobs),
        aggregated_data=aggregated
    )

    return CategorySummary(
        company_id=company_id,
        category=category,
        job_count=len(jobs),
        core_technologies=aggregated['top_skills'][:15],  # Top 15 skills
        summary=summary_text
    )


async def generate_all_summaries(
    db: Database,
    company_id: Optional[int] = None,
    categories: Optional[List[str]] = None
) -> List[CategorySummary]:
    """
    Generate summaries for all categories.

    Args:
        db: Database instance
        company_id: Optional company ID to filter by
        categories: Optional list of categories (uses settings if None)

    Returns:
        List of CategorySummary models
    """
    from config.settings import get_settings

    if categories is None:
        settings = get_settings()
        categories = settings.get_job_categories()

    logger.info(f"Generating summaries for {len(categories)} categories...")

    summaries = []

    for i, category in enumerate(categories):
        logger.info(f"Progress: {i+1}/{len(categories)}")

        summary = await generate_category_summary(db, category, company_id)

        if summary.job_count > 0:
            summaries.append(summary)

    logger.info(f"Generated {len(summaries)} category summaries")
    return summaries


async def _get_jobs_in_category(
    db: Database,
    category: str,
    company_id: Optional[int] = None
) -> List[Dict]:
    """
    Get all jobs in a category with their requirements.

    Returns:
        List of dicts with job and requirements data
    """
    with db.get_connection() as conn:
        cursor = conn.cursor()

        query = """
            SELECT
                j.id, j.title, j.team, j.location, j.experience_level,
                r.required_skills, r.preferred_skills, r.responsibilities, r.experience
            FROM jobs j
            JOIN job_categories jc ON j.id = jc.job_id
            LEFT JOIN requirements r ON j.id = r.job_id
            WHERE jc.category = ?
        """

        params = [category]

        if company_id:
            query += " AND j.company_id = ?"
            params.append(company_id)

        cursor.execute(query, params)
        rows = cursor.fetchall()

        import json

        jobs = []
        for row in rows:
            jobs.append({
                'id': row['id'],
                'title': row['title'],
                'team': row['team'],
                'location': row['location'],
                'experience_level': row['experience_level'],
                'required_skills': json.loads(row['required_skills'] or '[]'),
                'preferred_skills': json.loads(row['preferred_skills'] or '[]'),
                'responsibilities': json.loads(row['responsibilities'] or '[]'),
                'experience': json.loads(row['experience'] or '[]')
            })

        return jobs


def _aggregate_requirements(jobs: List[Dict]) -> Dict:
    """
    Aggregate requirements across all jobs.

    Args:
        jobs: List of job dicts with requirements

    Returns:
        Dict with aggregated data
    """
    all_required_skills = []
    all_preferred_skills = []
    all_responsibilities = []
    all_experience_levels = []

    for job in jobs:
        all_required_skills.extend(job['required_skills'])
        all_preferred_skills.extend(job['preferred_skills'])
        all_responsibilities.extend(job['responsibilities'])

        if job['experience_level']:
            all_experience_levels.append(job['experience_level'])

    # Count skill frequencies
    skill_counts = Counter(all_required_skills + all_preferred_skills)
    top_skills = [skill for skill, count in skill_counts.most_common(20)]

    # Count experience levels
    level_counts = Counter(all_experience_levels)

    return {
        'top_skills': top_skills,
        'skill_counts': dict(skill_counts.most_common(20)),
        'sample_responsibilities': all_responsibilities[:20],  # Sample
        'experience_level_distribution': dict(level_counts),
        'total_jobs': len(jobs)
    }


async def _generate_llm_summary(
    category: str,
    job_count: int,
    aggregated_data: Dict
) -> str:
    """
    Generate natural language summary using LLM.

    Args:
        category: Category name
        job_count: Number of jobs in category
        aggregated_data: Aggregated requirements data

    Returns:
        Summary text
    """
    llm = get_llm_client()

    # Format skills with counts
    skills_with_counts = [
        f"{skill} ({count})"
        for skill, count in list(aggregated_data['skill_counts'].items())[:15]
    ]

    prompt = f"""
Summarize the requirements for {category} roles based on the following data from {job_count} job postings:

Top Technologies & Skills (with frequency):
{chr(10).join(f'- {s}' for s in skills_with_counts)}

Experience Level Distribution:
{chr(10).join(f'- {level}: {count} jobs' for level, count in aggregated_data['experience_level_distribution'].items())}

Sample Responsibilities:
{chr(10).join(f'- {r}' for r in aggregated_data['sample_responsibilities'][:10])}

Generate a concise 2-3 paragraph summary covering:
1. Core technologies and tools commonly required
2. Typical responsibilities and focus areas
3. Experience levels and seniority expectations
4. Any notable patterns or trends

Write in a professional, informative tone. Focus on actionable insights for job seekers.
"""

    system_message = """You are a technical career advisor helping software engineers understand job market requirements.
Provide clear, specific insights based on the data. Avoid generic advice."""

    try:
        summary = await llm.chat_completion(
            prompt=prompt,
            system_message=system_message,
            temperature=0.4  # Slightly higher for more natural writing
        )

        logger.info(f"Generated summary for {category}: {len(summary)} chars")
        return summary.strip()

    except Exception as e:
        logger.error(f"Failed to generate LLM summary: {e}")
        # Fallback summary
        return _generate_fallback_summary(category, job_count, aggregated_data)


def _generate_fallback_summary(category: str, job_count: int, aggregated_data: Dict) -> str:
    """Generate a basic summary without LLM"""
    top_skills = aggregated_data['top_skills'][:10]
    skills_text = ", ".join(top_skills)

    summary = f"""Based on {job_count} {category} job postings, the most in-demand skills are: {skills_text}. """

    if aggregated_data['experience_level_distribution']:
        most_common_level = max(
            aggregated_data['experience_level_distribution'].items(),
            key=lambda x: x[1]
        )[0]
        summary += f"Most positions are at the {most_common_level} level. "

    return summary
