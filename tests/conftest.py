"""Shared pytest fixtures for the Datadog MCP test suite."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from datadog_mcp.auth import DatadogAuth


@pytest.fixture
def fake_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Provide fake Datadog credentials so DatadogAuth() can be constructed.

    No real network calls are made when only credentials are set; tools that
    hit the network are expected to mock the relevant `datadog_api_client` API
    class in their own tests.
    """
    monkeypatch.setenv("DD_API_KEY", "fake-api-key")
    monkeypatch.setenv("DD_APP_KEY", "fake-app-key")
    monkeypatch.setenv("DD_SITE", "datadoghq.com")
    yield


@pytest.fixture
def fake_auth(fake_env: None) -> DatadogAuth:
    """A DatadogAuth instance backed by fake credentials (no network access)."""
    return DatadogAuth()
