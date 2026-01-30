"""Pagination utilities for consistent pagination across tools."""

from dataclasses import dataclass
from typing import Optional


DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 50


@dataclass
class PaginationParams:
    """Parameters for paginated requests."""
    
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE
    cursor: Optional[str] = None
    
    def validate(self) -> None:
        """Validate pagination parameters."""
        if self.page < 1:
            raise ValueError("page must be >= 1")
        if self.page_size < 1:
            raise ValueError("page_size must be >= 1")
        if self.page_size > MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be <= {MAX_PAGE_SIZE}")


@dataclass
class PaginatedResponse:
    """Standard paginated response structure."""
    
    data: list
    page: int
    page_size: int
    total_count: Optional[int] = None
    has_next: bool = False
    next_cursor: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        result = {
            "data": self.data,
            "page": self.page,
            "page_size": self.page_size,
            "count": len(self.data),
            "has_next": self.has_next,
        }
        
        if self.total_count is not None:
            result["total_count"] = self.total_count
        
        if self.next_cursor is not None:
            result["next_cursor"] = self.next_cursor
        
        return result
