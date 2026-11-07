"""
In-memory browser context: rolling window of recently visited pages.
Nothing is persisted to disk; context lives only for the app's lifetime.
"""

from typing import Deque, Dict, List

from bs4 import BeautifulSoup
from collections import deque

from ..utils import Logger


class BrowserContext:
    """Holds the last few visited pages and the user's current selection."""

    def __init__(self, max_len: int = 3):
        self.context: Deque[Dict[str, str]] = deque(maxlen=max_len)
        self.selected_text: str = ""

    def push(self, url: str, title: str, body: str) -> None:
        soup = BeautifulSoup(body, "lxml")

        # Remove non-readable elements
        for element in soup(['script', 'style', 'noscript', 'iframe', 'svg', 'path', 'nav', 'header', 'footer']):
            element.decompose()

        clean_body = soup.get_text(strip=True, separator=' ')
        clean_body = ' '.join(clean_body.split())

        Logger.debug(f"Browser context: added page '{title}' with {len(clean_body)} chars of content")

        self.context.append({
            "url": url,
            "title": title,
            "body": clean_body
        })

    def pop(self) -> Dict[str, str]:
        """Pop the most recent page from the stack."""
        if self.context:
            return self.context.pop()
        return {}

    def get_context(self) -> List[Dict[str, str]]:
        """Get the current browser context as a list."""
        return list(self.context)
