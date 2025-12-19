"""
Parse job descriptions into structured requirements using LLM.
"""

import logging
from typing import Dict, List

from src.storage.models import Job, Requirements
from .llm_client import get_llm_client

logger = logging.getLogger(__name__)


async def parse_job_requirements(job: Job) -> Dict:
    """
    Parse job description into structured requirements and experience level.

    Args:
        job: Job object with raw_description

    Returns:
        Dict with requirements and experience_level
    """
    logger.info(f"Parsing requirements for: {job.title}")

    if not job.raw_description:
        logger.warning(f"No description for job {job.id}")
        return _empty_requirements()

    llm = get_llm_client()

    prompt = f"""
Extract and structure the following information from this job posting:

Job Title: {job.title}
Team: {job.team or 'Not specified'}
Location: {job.location or 'Not specified'}

Job Description:
{job.raw_description}

Return a JSON object with these fields:
{{
  "responsibilities": [...],           // Key responsibilities (array of strings)
  "required_skills": [...],             // Must-have technical skills (array of strings)
  "preferred_skills": [...],            // Nice-to-have skills (array of strings)
  "experience": [...],                  // Years of experience, domain experience (array of strings)
  "education": [...],                   // Degree requirements (array of strings)
  "experience_level": "..."            // One of: "Internship", "Entry-level", "Mid-level", "Senior", "Staff"
}}

Guidelines for experience_level detection:
- "Internship": Job title contains "Intern", or description mentions internship/student program
- "Entry-level": 0-2 years required, or job title contains "Junior", "Associate", or no explicit experience mentioned for non-senior roles
- "Mid-level": 2-5 years required, standard engineer role without senior/staff designation
- "Senior": 5+ years required, or job title contains "Senior", or requires leadership/mentorship
- "Staff": 8+ years, or job title contains "Staff", "Principal", "Distinguished", "Lead", or requires setting technical direction

Extract skills as specific technologies, languages, frameworks, and tools (e.g., "Python", "React", "Kubernetes", not generic terms like "programming").
"""

    system_message = """You are a technical recruiter expert at analyzing job descriptions.
Extract precise, specific information. For skills, list concrete technologies/tools, not vague descriptions.
Be consistent with experience level categorization based on the guidelines provided."""

    try:
        result = await llm.parse_json_response(
            prompt=prompt,
            system_message=system_message
        )

        logger.info(f"Parsed {len(result.get('required_skills', []))} required skills, "
                   f"{len(result.get('preferred_skills', []))} preferred skills")
        logger.info(f"Experience level: {result.get('experience_level', 'Unknown')}")

        return result

    except Exception as e:
        logger.error(f"Failed to parse job requirements: {e}")
        return _empty_requirements()


async def parse_multiple_jobs(jobs: List[Job]) -> Dict[int, Dict]:
    """
    Parse requirements for multiple jobs.

    Args:
        jobs: List of Job objects

    Returns:
        Dict mapping job_id to parsed requirements
    """
    logger.info(f"Parsing requirements for {len(jobs)} jobs...")

    results = {}

    for i, job in enumerate(jobs):
        logger.info(f"Progress: {i+1}/{len(jobs)}")

        parsed = await parse_job_requirements(job)
        results[job.id] = parsed

    logger.info(f"Successfully parsed {len(results)} jobs")
    return results


def requirements_dict_to_model(job_id: int, requirements_dict: Dict) -> Requirements:
    """
    Convert parsed requirements dict to Requirements model.

    Args:
        job_id: Job database ID
        requirements_dict: Parsed requirements from LLM

    Returns:
        Requirements model instance
    """
    return Requirements(
        job_id=job_id,
        responsibilities=requirements_dict.get('responsibilities', []),
        required_skills=requirements_dict.get('required_skills', []),
        preferred_skills=requirements_dict.get('preferred_skills', []),
        experience=requirements_dict.get('experience', []),
        education=requirements_dict.get('education', [])
    )


def _empty_requirements() -> Dict:
    """Return empty requirements structure"""
    return {
        "responsibilities": [],
        "required_skills": [],
        "preferred_skills": [],
        "experience": [],
        "education": [],
        "experience_level": "Mid-level"  # Default fallback
    }
