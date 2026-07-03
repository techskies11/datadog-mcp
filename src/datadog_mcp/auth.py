"""Authentication management for Datadog API."""

import os

from datadog_api_client import ApiClient, Configuration
from dotenv import load_dotenv

# Load environment variables from .env file (local development only; the
# supported path is Cursor's mcp.json - see README.md)
load_dotenv()

# Network calls from a long-lived MCP server process should never hang
# indefinitely on a slow/partitioned Datadog endpoint - a stuck request
# blocks the whole server for the agent. This is independent of any
# `timeout=` set on individual `@mcp.tool()` definitions: FastMCP's tool
# timeout cancels the *async* wait for a result, but does not interrupt a
# blocking HTTP call already in flight on a worker thread. The real cutoff
# has to live in the HTTP client itself.
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30


class DatadogAuth:
    """Manages Datadog API authentication and configuration.

    This class follows a dependency injection pattern similar to FastAPI.
    The ApiClient is created once and reused, no context managers needed.

    Example (similar to FastAPI):
        auth = DatadogAuth()
        api_instance = LogsApi(auth.api_client)
        response = api_instance.list_logs(...)
    """

    def __init__(
        self, api_key: str | None = None, app_key: str | None = None, site: str | None = None
    ):
        """Initialize Datadog authentication and create API client.

        Args:
            api_key: Datadog API key (defaults to DD_API_KEY env var)
            app_key: Datadog Application key (defaults to DD_APP_KEY env var)
            site: Datadog site/region (defaults to DD_SITE env var or datadoghq.com)
        """
        self.api_key = api_key or os.getenv("DD_API_KEY")
        self.app_key = app_key or os.getenv("DD_APP_KEY")
        self.site = site or os.getenv("DD_SITE", "datadoghq.com")

        if not self.api_key:
            raise ValueError("DD_API_KEY is required (via parameter or environment variable)")
        if not self.app_key:
            raise ValueError("DD_APP_KEY is required (via parameter or environment variable)")

        configuration = Configuration()  # type: ignore[no-untyped-call]
        configuration.api_key["apiKeyAuth"] = self.api_key
        configuration.api_key["appKeyAuth"] = self.app_key
        configuration.server_variables["site"] = self.site
        # Honors Datadog's `X-RateLimit-Reset` header on 429s instead of the
        # agent seeing a raw error on the first burst of calls.
        configuration.enable_retry = True
        configuration.request_timeout = DEFAULT_REQUEST_TIMEOUT_SECONDS

        # Create and store API client (no context manager needed)
        # This client can be reused for multiple API calls
        self._api_client = ApiClient(configuration)

    @property
    def api_client(self) -> ApiClient:
        """Get the configured Datadog API client.

        This property provides direct access to the API client.
        No context manager needed - just use it directly like in FastAPI.

        Returns:
            ApiClient: Ready-to-use Datadog API client instance
        """
        return self._api_client

    def close(self) -> None:
        """Close the API client and cleanup resources.

        This is optional - only call if you need to explicitly cleanup.
        The client will be garbage collected automatically when the auth instance is destroyed.
        """
        if hasattr(self, "_api_client") and self._api_client:
            self._api_client.close()


_auth_instance: DatadogAuth | None = None


def get_auth_instance() -> DatadogAuth:
    """Get or create the process-wide `DatadogAuth` singleton.

    Lives here (not in `server.py`) so tool registration modules can import
    it without creating a `server -> tools -> server` import cycle.

    Credentials are loaded from environment variables:
    - DD_API_KEY: Datadog API key
    - DD_APP_KEY: Datadog Application key
    - DD_SITE: Datadog site (default: datadoghq.com)

    These should be set in Cursor's mcp.json, NOT in this project's .env.
    """
    global _auth_instance
    if _auth_instance is None:
        _auth_instance = DatadogAuth()
    return _auth_instance
