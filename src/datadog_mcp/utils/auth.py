"""Authentication utilities for API client management."""

from typing import Optional, Tuple, TypeVar
from datadog_mcp.auth import DatadogAuth

T = TypeVar('T')


def get_api_instance(
    api_class: type[T],
    auth: Optional[DatadogAuth] = None
) -> Tuple[T, DatadogAuth]:
    """Get an API instance with authentication.
    
    Args:
        api_class: The API class to instantiate (e.g., LogsApi, MetricsApi)
        auth: Optional DatadogAuth instance. If None, creates a new one.
    
    Returns:
        Tuple of (api_instance, auth_instance)
    
    Example:
        api_instance, auth = get_api_instance(LogsApi, auth)
    """
    if auth is None:
        auth = DatadogAuth()
    
    api_instance = api_class(auth.api_client)
    return api_instance, auth
