"""Monitors tools for creating and managing Datadog monitors and alerts."""

from typing import Optional, Any
from datadog_api_client.v1.api.monitors_api import MonitorsApi
from datadog_api_client.v1.model.monitor import Monitor
from datadog_api_client.v1.model.monitor_type import MonitorType
from datadog_api_client.v1.model.monitor_options import MonitorOptions

from ..auth import DatadogAuth
from ..utils.response import ResponseBuilder, format_error_response
from ..utils.auth import get_api_instance


def list_monitors(
    group_states: Optional[str] = None,
    name: Optional[str] = None,
    tags: Optional[str] = None,
    monitor_tags: Optional[str] = None,
    with_downtimes: bool = False,
    limit: int = 50,
    auth: Optional[DatadogAuth] = None
) -> dict:
    """List monitors with optional filtering.
    
    Args:
        group_states: Filter by group states (e.g., "alert,warn,no data")
        name: Filter by monitor name substring
        tags: Filter by tags (e.g., "env:prod,service:api")
        monitor_tags: Filter by monitor-specific tags
        with_downtimes: Include downtime information (default: False)
        limit: Maximum number of monitors to return (default: 50, max: 50)
        auth: DatadogAuth instance (injected dependency)
    
    Returns:
        dict: List of monitors (size-limited)
    """
    api_instance, auth = get_api_instance(MonitorsApi, auth)
    
    try:
        kwargs = {}
        if group_states:
            kwargs["group_states"] = group_states
        if name:
            kwargs["name"] = name
        if tags:
            kwargs["tags"] = tags
        if monitor_tags:
            kwargs["monitor_tags"] = monitor_tags
        if with_downtimes:
            kwargs["with_downtimes"] = with_downtimes
        
        response = api_instance.list_monitors(**kwargs)
        
        monitors = []
        if response:
            for monitor in response[:limit]:
                monitor_entry = {
                    "id": monitor.id if hasattr(monitor, 'id') else None,
                    "name": monitor.name if hasattr(monitor, 'name') else None,
                    "type": str(monitor.type) if hasattr(monitor, 'type') else None,
                    "query": monitor.query if hasattr(monitor, 'query') else None,
                    "message": monitor.message if hasattr(monitor, 'message') else None,
                    "tags": monitor.tags if hasattr(monitor, 'tags') else [],
                    "overall_state": str(monitor.overall_state) if hasattr(monitor, 'overall_state') else None,
                    "created": monitor.created.isoformat() if hasattr(monitor, 'created') and monitor.created else None,
                    "modified": monitor.modified.isoformat() if hasattr(monitor, 'modified') and monitor.modified else None,
                    "priority": monitor.priority if hasattr(monitor, 'priority') else None
                }
                monitors.append(monitor_entry)
        
        return ResponseBuilder.success("monitors", monitors)
        
    except Exception as e:
        return format_error_response("monitors", e)


def get_monitor(monitor_id: int, auth: Optional[DatadogAuth] = None) -> dict:
    """Get detailed information about a specific monitor.
    
    Args:
        monitor_id: The numeric ID of the monitor
        auth: DatadogAuth instance (injected dependency)
    
    Returns:
        dict: Complete monitor configuration
    """
    if auth is None:
        auth = DatadogAuth()
    
    # Use API client directly - no context manager needed
    api_instance = MonitorsApi(auth.api_client)
    
    try:
            response = api_instance.get_monitor(monitor_id)
            
            monitor_dict = response.to_dict() if hasattr(response, 'to_dict') else {}
            
            return {
                "success": True,
                "monitor": monitor_dict
            }
            
    except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }


def create_monitor(
    name: str,
    monitor_type: str,
    query: str,
    message: str,
    tags: Optional[list[str]] = None,
    priority: Optional[int] = None,
    options: Optional[dict] = None,
    auth: Optional[DatadogAuth] = None
) -> dict:
    """Create a new monitor/alert.
    
    Args:
        name: Monitor name
        monitor_type: Type of monitor - "metric alert", "service check", "event alert", 
                     "query alert", "composite", "log alert", "rum alert", "trace-analytics alert"
        query: The monitor query (syntax depends on monitor_type)
        message: Notification message with optional @mentions (e.g., "@user@example.com Service is down!")
        tags: Optional list of tags (e.g., ["env:prod", "team:backend"])
        priority: Optional priority (1-5, where 1 is highest)
        options: Optional monitor options dict (thresholds, notify_no_data, etc.)
        auth: DatadogAuth instance (injected dependency)
    
    Returns:
        dict: Created monitor information including ID
    """
    if auth is None:
        auth = DatadogAuth()
    
    # Map string type to MonitorType enum
    type_mapping = {
        "metric alert": MonitorType.METRIC_ALERT,
        "service check": MonitorType.SERVICE_CHECK,
        "event alert": MonitorType.EVENT_ALERT,
        "query alert": MonitorType.QUERY_ALERT,
        "composite": MonitorType.COMPOSITE,
        "log alert": MonitorType.LOG_ALERT,
        "rum alert": MonitorType.RUM_ALERT,
        "trace-analytics alert": MonitorType.TRACE_ANALYTICS_ALERT
    }
    
    if monitor_type not in type_mapping:
        return {
            "success": False,
            "error": f"Invalid monitor_type. Must be one of: {list(type_mapping.keys())}"
        }
    
    # Use API client directly - no context manager needed
    api_instance = MonitorsApi(auth.api_client)
    
    try:
            # Build monitor object
            monitor_data = {
                "name": name,
                "type": type_mapping[monitor_type],
                "query": query,
                "message": message
            }
            
            if tags:
                monitor_data["tags"] = tags
            if priority:
                monitor_data["priority"] = priority
            if options:
                monitor_data["options"] = MonitorOptions(**options)
            
            body = Monitor(**monitor_data)
            response = api_instance.create_monitor(body=body)
            
            return {
                "success": True,
                "monitor_id": response.id if hasattr(response, 'id') else None,
                "name": response.name if hasattr(response, 'name') else name,
                "type": str(response.type) if hasattr(response, 'type') else monitor_type
            }
            
    except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }


def update_monitor(
    monitor_id: int,
    name: Optional[str] = None,
    query: Optional[str] = None,
    message: Optional[str] = None,
    tags: Optional[list[str]] = None,
    priority: Optional[int] = None,
    options: Optional[dict] = None,
    auth: Optional[DatadogAuth] = None
) -> dict:
    """Update an existing monitor.
    
    Args:
        monitor_id: The numeric ID of the monitor to update
        name: Optional new name
        query: Optional new query
        message: Optional new notification message
        tags: Optional new tags
        priority: Optional new priority
        options: Optional new monitor options
        auth: DatadogAuth instance (injected dependency)
    
    Returns:
        dict: Updated monitor information
    """
    if auth is None:
        auth = DatadogAuth()
    
    # Use API client directly - no context manager needed
    api_instance = MonitorsApi(auth.api_client)
    
    try:
            # Get existing monitor
            existing = api_instance.get_monitor(monitor_id)
            existing_dict = existing.to_dict() if hasattr(existing, 'to_dict') else {}
            
            # Update only provided fields
            monitor_data = {
                "name": name or existing_dict.get("name"),
                "type": existing.type,
                "query": query or existing_dict.get("query"),
                "message": message or existing_dict.get("message")
            }
            
            if tags is not None:
                monitor_data["tags"] = tags
            elif "tags" in existing_dict:
                monitor_data["tags"] = existing_dict["tags"]
            
            if priority is not None:
                monitor_data["priority"] = priority
            elif "priority" in existing_dict:
                monitor_data["priority"] = existing_dict["priority"]
            
            if options is not None:
                monitor_data["options"] = MonitorOptions(**options)
            elif hasattr(existing, 'options'):
                monitor_data["options"] = existing.options
            
            body = Monitor(**monitor_data)
            response = api_instance.update_monitor(monitor_id, body=body)
            
            return {
                "success": True,
                "monitor_id": response.id if hasattr(response, 'id') else monitor_id,
                "name": response.name if hasattr(response, 'name') else name
            }
            
    except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }


def delete_monitor(monitor_id: int, auth: Optional[DatadogAuth] = None) -> dict:
    """Delete a monitor.
    
    Args:
        monitor_id: The numeric ID of the monitor to delete
        auth: DatadogAuth instance (injected dependency)
    
    Returns:
        dict: Deletion result
    """
    if auth is None:
        auth = DatadogAuth()
    
    # Use API client directly - no context manager needed
    api_instance = MonitorsApi(auth.api_client)
    
    try:
            api_instance.delete_monitor(monitor_id)
            
            return {
                "success": True,
                "monitor_id": monitor_id,
                "message": "Monitor deleted successfully"
            }
            
    except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }


def mute_monitor(
    monitor_id: int,
    scope: Optional[str] = None,
    end_timestamp: Optional[int] = None,
    auth: Optional[DatadogAuth] = None
) -> dict:
    """Mute/silence a monitor to stop sending alerts.
    
    Args:
        monitor_id: The numeric ID of the monitor to mute
        scope: Optional scope to mute (e.g., "host:myhost" or "env:prod")
        end_timestamp: Optional Unix timestamp when the mute should end
        auth: DatadogAuth instance (injected dependency)
    
    Returns:
        dict: Mute operation result
    """
    if auth is None:
        auth = DatadogAuth()
    
    # Use API client directly - no context manager needed
    api_instance = MonitorsApi(auth.api_client)
    
    try:
            kwargs = {}
            if scope:
                kwargs["scope"] = scope
            if end_timestamp:
                kwargs["end"] = end_timestamp
            
            body = kwargs
            response = api_instance.mute_monitor(monitor_id, body=body)
            
            return {
                "success": True,
                "monitor_id": monitor_id,
                "message": "Monitor muted successfully",
                "scope": scope,
                "end_timestamp": end_timestamp
            }
            
    except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }


def unmute_monitor(
    monitor_id: int,
    scope: Optional[str] = None,
    auth: Optional[DatadogAuth] = None
) -> dict:
    """Unmute a monitor to resume sending alerts.
    
    Args:
        monitor_id: The numeric ID of the monitor to unmute
        scope: Optional scope to unmute (must match the mute scope)
        auth: DatadogAuth instance (injected dependency)
    
    Returns:
        dict: Unmute operation result
    """
    if auth is None:
        auth = DatadogAuth()
    
    # Use API client directly - no context manager needed
    api_instance = MonitorsApi(auth.api_client)
    
    try:
            kwargs = {}
            if scope:
                kwargs["scope"] = scope
            
            body = kwargs
            response = api_instance.unmute_monitor(monitor_id, body=body)
            
            return {
                "success": True,
                "monitor_id": monitor_id,
                "message": "Monitor unmuted successfully",
                "scope": scope
            }
            
    except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
