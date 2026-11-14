from __future__ import annotations


class ScraperError(Exception):
    """Base exception for scraper errors."""

    failure_code = "SCRAPE_FAILED"
    public_message = "Scrape failed. Please try again."


class BrowserError(ScraperError):
    """The Playwright runtime or browser is unavailable."""

    failure_code = "BROWSER_UNAVAILABLE"


class PageLoadError(ScraperError):
    """A transient marketplace or network failure."""

    failure_code = "MARKETPLACE_UNAVAILABLE"

    def __init__(self, message: str, retry_after: int = 0) -> None:
        super().__init__(message, retry_after)
        self.retry_after = retry_after

    def __str__(self) -> str:
        return str(self.args[0])


class RequestTimeoutError(PageLoadError):
    failure_code = "MARKETPLACE_TIMEOUT"


class RateLimitError(PageLoadError):
    failure_code = "MARKETPLACE_RATE_LIMITED"
    public_message = "Daraz is rate limiting requests. Please try again later."


class PermanentAccessError(ScraperError):
    failure_code = "MARKETPLACE_ACCESS_DENIED"
    public_message = "Daraz access is unavailable for this scrape."


class ParseError(ScraperError):
    """The response did not contain a recognizable search result."""

    failure_code = "MARKETPLACE_PARSE_FAILED"


class SimilarityError(ScraperError):
    """Similarity scoring failed unexpectedly."""

    failure_code = "SIMILARITY_FAILED"
    public_message = "Competitor matching failed. Please try again."


class SimilarityUnavailableError(SimilarityError):
    """The embedding model or its runtime could not be loaded."""

    failure_code = "SIMILARITY_UNAVAILABLE"
    public_message = "Competitor matching is temporarily unavailable."


def public_failure_message(code: str | None) -> str:
    return _PUBLIC_FAILURE_MESSAGES.get(code or "", ScraperError.public_message)


_PUBLIC_FAILURE_MESSAGES = {
    error.failure_code: error.public_message
    for error in (RateLimitError, PermanentAccessError, SimilarityError, SimilarityUnavailableError)
}
