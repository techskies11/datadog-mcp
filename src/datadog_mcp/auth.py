"""Authentication management for Datadog API."""

import os

from datadog_api_client import ApiClient, Configuration
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


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

        # Create configuration
        configuration = Configuration()
        configuration.api_key["apiKeyAuth"] = self.api_key
        configuration.api_key["appKeyAuth"] = self.app_key
        configuration.server_variables["site"] = self.site

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

    def close(self):
        """Close the API client and cleanup resources.

        This is optional - only call if you need to explicitly cleanup.
        The client will be garbage collected automatically when the auth instance is destroyed.
        """
        if hasattr(self, "_api_client") and self._api_client:
            self._api_client.close()
