"""
Categorize jobs into engineering role types using LLM.
"""

import logging
from typing import Dict, List, Optional

from src.storage.models import Job, JobCategory, Requirements
from config.settings import get_settings
from .llm_client import get_llm_client

logger = logging.getLogger(__name__)


async def categorize_job(
    job: Job,
    requirements: Requirements,
    available_categories: Optional[List[str]] = None
) -> Dict:
    """
    Categorize a job into one or more engineering categories.

    Args:
        job: Job object
        requirements: Parsed requirements
        available_categories: List of valid categories (from settings if None)

    Returns:
        Dict with primary_category, secondary_categories, confidence
    """
    logger.info(f"Categorizing: {job.title}")

    settings = get_settings()
    categories = available_categories or settings.get_job_categories()

    llm = get_llm_client()

    # Build skills summary
    skills_summary = ", ".join(requirements.required_skills[:10])  # Top 10 skills
    responsibilities_summary = " | ".join(requirements.responsibilities[:5])  # Top 5 responsibilities

    prompt = f"""
Categorize this software engineering job into the most appropriate category.

Job Title: {job.title}
Team: {job.team or 'Not specified'}
Location: {job.location or 'Not specified'}

Top Required Skills: {skills_summary or 'Not specified'}
Key Responsibilities: {responsibilities_summary or 'Not specified'}

Available Categories:
{chr(10).join(f'- {cat}' for cat in categories)}

Return JSON:
{{
  "primary_category": "...",           // Single best-fit category from the list above
  "secondary_categories": [...],       // Up to 2 additional relevant categories (can be empty)
  "confidence": 0.95,                  // Confidence score 0.0-1.0
  "reasoning": "..."                   // Brief explanation of categorization
}}

Guidelines:
- Choose the most specific category that matches the role
- If a job clearly fits multiple categories (e.g., Full Stack Engineer), include them in secondary_categories
- Confidence should reflect how clearly the job fits the category
- ML Engineer and Machine Learning Engineer are the same category
- Infrastructure Engineer and Platform Engineer are similar but distinct (Infrastructure is more ops/SRE, Platform is more developer tooling)
"""

    system_message = """You are an expert technical recruiter who understands engineering role specializations.
Categorize based on the actual responsibilities and skills, not just the job title.
A "Software Engineer" without specifics should be categorized based on the skills and responsibilities listed."""

    try:
        result = await llm.parse_json_response(
            prompt=prompt,
            system_message=system_message
        )

        primary = result.get('primary_category', categories[0])
        secondary = result.get('secondary_categories', [])
        confidence = result.get('confidence', 0.8)
        reasoning = result.get('reasoning', '')

        logger.info(f"Categorized as: {primary} (confidence: {confidence:.2f})")
        if secondary:
            logger.info(f"Secondary categories: {', '.join(secondary)}")
        logger.debug(f"Reasoning: {reasoning}")

        return {
            'primary_category': primary,
            'secondary_categories': secondary,
            'confidence': confidence,
            'reasoning': reasoning
        }

    except Exception as e:
        logger.error(f"Failed to categorize job: {e}")
        # Fallback: try to guess from title
        return _fallback_categorization(job, categories)


async def categorize_multiple_jobs(
    jobs_with_requirements: List[tuple[Job, Requirements]]
) -> Dict[int, Dict]:
    """
    Categorize multiple jobs.

    Args:
        jobs_with_requirements: List of (Job, Requirements) tuples

    Returns:
        Dict mapping job_id to categorization result
    """
    logger.info(f"Categorizing {len(jobs_with_requirements)} jobs...")

    results = {}

    for i, (job, requirements) in enumerate(jobs_with_requirements):
        logger.info(f"Progress: {i+1}/{len(jobs_with_requirements)}")

        categorization = await categorize_job(job, requirements)
        results[job.id] = categorization

    logger.info(f"Successfully categorized {len(results)} jobs")
    return results


def categorization_to_models(job_id: int, categorization: Dict) -> List[JobCategory]:
    """
    Convert categorization result to JobCategory models.

    Args:
        job_id: Job database ID
        categorization: Categorization result from LLM

    Returns:
        List of JobCategory model instances
    """
    categories = []

    # Primary category
    categories.append(JobCategory(
        job_id=job_id,
        category=categorization['primary_category'],
        is_primary=True,
        confidence=categorization.get('confidence', 0.8)
    ))

    # Secondary categories
    for secondary in categorization.get('secondary_categories', []):
        categories.append(JobCategory(
            job_id=job_id,
            category=secondary,
            is_primary=False,
            confidence=categorization.get('confidence', 0.8) * 0.8  # Lower confidence for secondary
        ))

    return categories


def _fallback_categorization(job: Job, categories: List[str]) -> Dict:
    """
    Fallback categorization based on title keywords.

    Args:
        job: Job object
        categories: List of available categories

    Returns:
        Basic categorization dict
    """
    logger.warning(f"Using fallback categorization for: {job.title}")

    title_lower = job.title.lower()

    # Simple keyword matching
    if 'backend' in title_lower:
        primary = 'Backend Engineer'
    elif 'frontend' in title_lower or 'front-end' in title_lower:
        primary = 'Frontend Engineer'
    elif 'full stack' in title_lower or 'fullstack' in title_lower:
        primary = 'Full Stack Engineer'
    elif 'ml' in title_lower or 'machine learning' in title_lower or 'ai' in title_lower:
        primary = 'Machine Learning Engineer'
    elif 'infrastructure' in title_lower or 'sre' in title_lower or 'devops' in title_lower:
        primary = 'Infrastructure Engineer'
    elif 'platform' in title_lower:
        primary = 'Platform Engineer'
    elif 'mobile' in title_lower or 'ios' in title_lower or 'android' in title_lower:
        primary = 'Mobile Engineer'
    elif 'security' in title_lower:
        primary = 'Security Engineer'
    elif 'systems' in title_lower:
        primary = 'Systems Engineer'
    else:
        # Default to Full Stack if unclear
        primary = 'Full Stack Engineer'

    # Make sure primary is in available categories
    if primary not in categories:
        primary = categories[0] if categories else 'Full Stack Engineer'

    return {
        'primary_category': primary,
        'secondary_categories': [],
        'confidence': 0.5,  # Low confidence for fallback
        'reasoning': 'Fallback categorization based on title keywords'
    }
