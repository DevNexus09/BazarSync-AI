from __future__ import annotations


class ScraperError(Exception):
    """Base exception for scraper errors."""


class BrowserError(ScraperError):
    """Raised when the browser cannot be launched or reused."""


class PageLoadError(ScraperError):
    """Raised when a target page fails to load after retries."""


class ParseError(ScraperError):
    """Raised when the parser cannot extract expected data."""


class SimilarityError(ScraperError):
    """Raised when similarity computations fail."""
