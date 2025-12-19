"""
Playwright browser management and utilities.
"""

import logging
from typing import Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from config.settings import get_settings

logger = logging.getLogger(__name__)


class BrowserManager:
    """Manages Playwright browser lifecycle"""

    def __init__(self):
        self.settings = get_settings()
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def __aenter__(self):
        """Async context manager entry"""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()

    async def start(self):
        """Start browser"""
        logger.info("Starting Playwright browser...")
        self.playwright = await async_playwright().start()

        # Launch browser
        self.browser = await self.playwright.chromium.launch(
            headless=self.settings.scraper_headless
        )

        # Create context (isolated session)
        self.context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )

        # Create page
        self.page = await self.context.new_page()

        # Set timeout
        self.page.set_default_timeout(self.settings.scraper_timeout)

        logger.info("Browser started successfully")

    async def close(self):
        """Close browser"""
        logger.info("Closing browser...")
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("Browser closed")

    async def new_page(self) -> Page:
        """Create a new page"""
        if not self.context:
            await self.start()
        return await self.context.new_page()

    async def scroll_to_bottom(self, page: Page, pause: Optional[int] = None):
        """
        Scroll to bottom of page.

        Args:
            page: Playwright page object
            pause: Pause duration in seconds (defaults to settings)
        """
        pause = pause or self.settings.scraper_scroll_pause

        await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        await page.wait_for_timeout(pause * 1000)

    async def infinite_scroll(
        self,
        page: Page,
        selector: str,
        max_scrolls: int = 20
    ) -> int:
        """
        Perform infinite scroll until no new elements load.

        Args:
            page: Playwright page object
            selector: CSS selector to count elements
            max_scrolls: Maximum number of scroll attempts

        Returns:
            Total number of elements found
        """
        logger.info(f"Starting infinite scroll (max: {max_scrolls} scrolls)...")

        previous_count = 0
        scroll_count = 0

        while scroll_count < max_scrolls:
            # Scroll to bottom
            await self.scroll_to_bottom(page)

            # Count elements
            try:
                elements = await page.query_selector_all(selector)
                current_count = len(elements)

                logger.debug(f"Scroll {scroll_count + 1}: Found {current_count} elements")

                # Stop if no new elements
                if current_count == previous_count:
                    logger.info(f"No new elements after {scroll_count} scrolls")
                    break

                previous_count = current_count
                scroll_count += 1

            except Exception as e:
                logger.warning(f"Error during scroll: {e}")
                break

        logger.info(f"Infinite scroll complete. Total elements: {previous_count}")
        return previous_count
