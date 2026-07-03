"""Shared pagination constants for cursor-paginated tools."""

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 50


def clamp_page_size(page_size: int) -> int:
    """Clamp a requested page size to `[1, MAX_PAGE_SIZE]`."""
    return max(1, min(page_size, MAX_PAGE_SIZE))
