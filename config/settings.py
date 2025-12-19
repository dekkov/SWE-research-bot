"""
Configuration management using Pydantic Settings.
Loads environment variables from .env file.
"""

from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )

    # OpenAI API
    openai_api_key: str = Field(..., description="OpenAI API key")
    openai_model: str = Field(default="gpt-4o-mini", description="Model to use")
    openai_temperature: float = Field(default=0.3, description="Temperature for LLM calls")
    openai_max_tokens: int = Field(default=2000, description="Max tokens for responses")

    # Scraper
    scraper_headless: bool = Field(default=True, description="Run browser in headless mode")
    scraper_scroll_pause: int = Field(default=2, description="Pause between scrolls (seconds)")
    scraper_max_retries: int = Field(default=3, description="Max retries for failed requests")
    scraper_timeout: int = Field(default=30000, description="Page load timeout (ms)")

    # Database
    database_path: str = Field(default="data/jobs.db", description="SQLite database path")

    # Web Dashboard
    web_host: str = Field(default="127.0.0.1", description="Web server host")
    web_port: int = Field(default=8000, description="Web server port")

    # Logging
    log_level: str = Field(default="INFO", description="Logging level")
    log_file: str = Field(default="logs/scraper.log", description="Log file path")

    # Job Categories (comma-separated in .env)
    job_categories: str = Field(
        default="Backend Engineer,Frontend Engineer,Full Stack Engineer,"
                "Infrastructure Engineer,Platform Engineer,Machine Learning Engineer,"
                "ML Engineer,Systems Engineer,Security Engineer,Mobile Engineer",
        description="Comma-separated list of job categories to search"
    )

    # Experience Levels (comma-separated in .env)
    experience_levels: str = Field(
        default="Internship,Entry-level,Mid-level,Senior,Staff",
        description="Comma-separated list of experience levels"
    )

    def get_job_categories(self) -> List[str]:
        """Parse job categories from comma-separated string"""
        return [cat.strip() for cat in self.job_categories.split(',') if cat.strip()]

    def get_experience_levels(self) -> List[str]:
        """Parse experience levels from comma-separated string"""
        return [level.strip() for level in self.experience_levels.split(',') if level.strip()]


# Global settings instance
_settings: Settings = None


def get_settings() -> Settings:
    """Get or create global settings instance"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
