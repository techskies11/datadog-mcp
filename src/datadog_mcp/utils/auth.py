"""Authentication utilities for API client management."""

from typing import Protocol, TypeVar

from datadog_api_client import ApiClient

from datadog_mcp.auth import DatadogAuth


class _AcceptsApiClient(Protocol):
    """Structural type for `datadog_api_client` API classes.

    Every `<Foo>Api` class in `datadog_api_client` takes a single
    `ApiClient` positional argument. Binding `get_api_instance`'s TypeVar to
    this protocol (instead of a bare `TypeVar`) lets type checkers verify
    the constructor call below without a `type: ignore[call-arg]`.
    """

    def __init__(self, api_client: ApiClient) -> None: ...


T = TypeVar("T", bound=_AcceptsApiClient)


def get_api_instance(api_class: type[T], auth: DatadogAuth) -> T:
    """Instantiate a Datadog API class bound to the given auth's client.

    `auth` is always required and explicit (typically `get_auth_instance()`
    from `datadog_mcp.auth`, called once per tool invocation). This module
    intentionally does not fall back to constructing its own `DatadogAuth()`:
    an implicit fallback made every call site's auth handling inconsistent
    and hid failures in tests that forgot to inject a fake.

    Example:
        auth = get_auth_instance()
        api_instance = get_api_instance(LogsApi, auth)
    """
    return api_class(auth.api_client)
