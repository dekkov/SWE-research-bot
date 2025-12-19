"""
OpenAI API client wrapper with error handling and rate limiting.
"""

import logging
import json
from typing import Dict, Optional
from openai import AsyncOpenAI
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)

from config.settings import get_settings

logger = logging.getLogger(__name__)


class LLMClient:
    """Wrapper for OpenAI API with retry logic"""

    def __init__(self):
        self.settings = get_settings()
        self.client = AsyncOpenAI(api_key=self.settings.openai_api_key)
        self.model = self.settings.openai_model
        self.temperature = self.settings.openai_temperature
        self.max_tokens = self.settings.openai_max_tokens

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((Exception,)),
        reraise=True
    )
    async def chat_completion(
        self,
        prompt: str,
        system_message: Optional[str] = None,
        response_format: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ) -> str:
        """
        Make a chat completion request with retry logic.

        Args:
            prompt: User prompt
            system_message: Optional system message
            response_format: "json_object" for JSON response, None for text
            temperature: Override default temperature
            max_tokens: Override default max tokens

        Returns:
            Response text or JSON string
        """
        messages = []

        if system_message:
            messages.append({"role": "system", "content": system_message})

        messages.append({"role": "user", "content": prompt})

        # Build request parameters
        params = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature or self.temperature,
            "max_tokens": max_tokens or self.max_tokens
        }

        # Add response format if specified
        if response_format == "json_object":
            params["response_format"] = {"type": "json_object"}

        logger.debug(f"Making LLM request: {self.model}")

        try:
            response = await self.client.chat.completions.create(**params)

            content = response.choices[0].message.content

            # Log token usage
            usage = response.usage
            logger.info(
                f"LLM tokens: {usage.prompt_tokens} in, "
                f"{usage.completion_tokens} out, "
                f"{usage.total_tokens} total"
            )

            return content

        except Exception as e:
            logger.error(f"LLM request failed: {e}")
            raise

    async def parse_json_response(
        self,
        prompt: str,
        system_message: Optional[str] = None
    ) -> Dict:
        """
        Make a chat completion request expecting JSON response.

        Args:
            prompt: User prompt
            system_message: Optional system message

        Returns:
            Parsed JSON dict

        Raises:
            ValueError: If response is not valid JSON
        """
        response = await self.chat_completion(
            prompt=prompt,
            system_message=system_message,
            response_format="json_object"
        )

        try:
            return json.loads(response)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.error(f"Response was: {response}")
            raise ValueError(f"Invalid JSON response from LLM: {e}")


# Global LLM client instance
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """Get or create global LLM client instance"""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
