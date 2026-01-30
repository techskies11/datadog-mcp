"""Dashboard tools for creating and managing Datadog dashboards."""

from typing import Optional, Any
from datadog_api_client.v1.api.dashboards_api import DashboardsApi
from datadog_api_client.v1.model.dashboard import Dashboard
from datadog_api_client.v1.model.dashboard_layout_type import DashboardLayoutType

from ..auth import DatadogAuth
from ..utils.response import ResponseBuilder, format_error_response
from ..utils.auth import get_api_instance


def list_dashboards(
    filter_query: Optional[str] = None,
    limit: int = 50,
    auth: Optional[DatadogAuth] = None
) -> dict:
    """List all dashboards with optional filtering.
    
    Args:
        filter_query: Optional search query to filter dashboards by name or tags
        limit: Maximum number of dashboards to return (default: 50, max: 50)
        auth: DatadogAuth instance (injected dependency)
    
    Returns:
        dict: List of dashboards with basic information (size-limited)
    """
    api_instance, auth = get_api_instance(DashboardsApi, auth)
        
    try:
        response = api_instance.list_dashboards()
        
        dashboards = []
        if hasattr(response, 'dashboards') and response.dashboards:
            for dashboard in response.dashboards:
                # Convert dashboard object to dict
                if hasattr(dashboard, 'to_dict'):
                    dashboard_dict = dashboard.to_dict()
                else:
                    dashboard_dict = dashboard if isinstance(dashboard, dict) else {}
                
                # Apply filter if provided
                if filter_query:
                    title = dashboard_dict.get('title', '').lower()
                    if filter_query.lower() not in title:
                        continue
                
                dashboard_entry = {
                    "id": dashboard_dict.get('id'),
                    "title": dashboard_dict.get('title'),
                    "description": dashboard_dict.get('description'),
                    "author_handle": dashboard_dict.get('author_handle'),
                    "created_at": dashboard_dict.get('created_at'),
                    "modified_at": dashboard_dict.get('modified_at'),
                    "url": dashboard_dict.get('url'),
                    "is_read_only": dashboard_dict.get('is_read_only', False),
                    "layout_type": str(dashboard_dict.get('layout_type', '')) if dashboard_dict.get('layout_type') else None
                }
                dashboards.append(dashboard_entry)
                
                if len(dashboards) >= limit:
                    break
        
        return ResponseBuilder.success("dashboards", dashboards)
        
    except Exception as e:
        return format_error_response("dashboards", e)


def get_dashboard(dashboard_id: str, auth: Optional[DatadogAuth] = None) -> dict:
    """Get complete dashboard definition including all widgets and configuration.
    
    Args:
        dashboard_id: The unique identifier of the dashboard
        auth: DatadogAuth instance (injected dependency)
    
    Returns:
        dict: Complete dashboard definition (auto-truncated if too large)
    """
    api_instance, auth = get_api_instance(DashboardsApi, auth)
        
    try:
        response = api_instance.get_dashboard(dashboard_id)
        
        # Convert to dict for easier handling
        dashboard_dict = response.to_dict() if hasattr(response, 'to_dict') else {}
        
        return {
            "success": True,
            "dashboard": dashboard_dict
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def create_dashboard(
    title: str,
    layout_type: str,
    widgets: list[dict],
    description: Optional[str] = None,
    template_variables: Optional[list[dict]] = None,
    notify_list: Optional[list[str]] = None,
    tags: Optional[list[str]] = None,
    auth: Optional[DatadogAuth] = None
) -> dict:
    """Create a new Datadog dashboard with advanced configuration.
    
    Args:
        title: Dashboard title
        layout_type: Layout type - "ordered" (timeline) or "free" (free-form)
        widgets: List of widget definitions (see Datadog API docs for widget schemas)
        description: Optional dashboard description
        template_variables: Optional list of template variable definitions
        notify_list: Optional list of handles to notify on changes
        tags: Optional list of tags
        auth: DatadogAuth instance (injected dependency)
    
    Returns:
        dict: Created dashboard information including ID
    """
    if auth is None:
        auth = DatadogAuth()
    
    # Validate layout type
    valid_layouts = ["ordered", "free"]
    if layout_type not in valid_layouts:
        return {
            "success": False,
            "error": f"Invalid layout_type. Must be one of: {valid_layouts}"
        }
    
    # Use API client directly - no context manager needed
    api_instance = DashboardsApi(auth.api_client)
        
    try:
        # Build dashboard object
        dashboard_data = {
            "title": title,
            "layout_type": layout_type,
            "widgets": widgets
        }
        
        if description:
            dashboard_data["description"] = description
        if template_variables:
            dashboard_data["template_variables"] = template_variables
        if notify_list:
            dashboard_data["notify_list"] = notify_list
        if tags:
            dashboard_data["tags"] = tags
        
        body = Dashboard(**dashboard_data)
        response = api_instance.create_dashboard(body=body)
        
        return {
            "success": True,
            "dashboard_id": response.id if hasattr(response, 'id') else None,
            "url": response.url if hasattr(response, 'url') else None,
            "title": response.title if hasattr(response, 'title') else title
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def update_dashboard(
    dashboard_id: str,
    title: Optional[str] = None,
    widgets: Optional[list[dict]] = None,
    description: Optional[str] = None,
    template_variables: Optional[list[dict]] = None,
    layout_type: Optional[str] = None,
    notify_list: Optional[list[str]] = None,
    tags: Optional[list[str]] = None,
    auth: Optional[DatadogAuth] = None
) -> dict:
    """Update an existing dashboard.
    
    Args:
        dashboard_id: The unique identifier of the dashboard to update
        title: Optional new title
        widgets: Optional new widget configuration
        description: Optional new description
        template_variables: Optional new template variables
        layout_type: Optional new layout type - "ordered" or "free"
        notify_list: Optional new notify list
        tags: Optional new tags
        auth: DatadogAuth instance (injected dependency)
    
    Returns:
        dict: Updated dashboard information
    """
    if auth is None:
        auth = DatadogAuth()
    
    # Use API client directly - no context manager needed
    api_instance = DashboardsApi(auth.api_client)
        
    try:
        # First get the existing dashboard
        existing = api_instance.get_dashboard(dashboard_id)
        existing_dict = existing.to_dict() if hasattr(existing, 'to_dict') else {}
        
        # Update only provided fields
        dashboard_data = {
            "title": title or existing_dict.get("title"),
            "layout_type": layout_type or existing_dict.get("layout_type"),
            "widgets": widgets if widgets is not None else existing_dict.get("widgets", [])
        }
        
        if description is not None:
            dashboard_data["description"] = description
        elif "description" in existing_dict:
            dashboard_data["description"] = existing_dict["description"]
        
        if template_variables is not None:
            dashboard_data["template_variables"] = template_variables
        elif "template_variables" in existing_dict:
            dashboard_data["template_variables"] = existing_dict["template_variables"]
        
        if notify_list is not None:
            dashboard_data["notify_list"] = notify_list
        elif "notify_list" in existing_dict:
            dashboard_data["notify_list"] = existing_dict["notify_list"]
        
        if tags is not None:
            dashboard_data["tags"] = tags
        elif "tags" in existing_dict:
            dashboard_data["tags"] = existing_dict["tags"]
        
        body = Dashboard(**dashboard_data)
        response = api_instance.update_dashboard(dashboard_id, body=body)
        
        return {
            "success": True,
            "dashboard_id": response.id if hasattr(response, 'id') else dashboard_id,
            "url": response.url if hasattr(response, 'url') else None,
            "title": response.title if hasattr(response, 'title') else title
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def delete_dashboard(dashboard_id: str, auth: Optional[DatadogAuth] = None) -> dict:
    """Delete a dashboard.
    
    Args:
        dashboard_id: The unique identifier of the dashboard to delete
        auth: DatadogAuth instance (injected dependency)
    
    Returns:
        dict: Deletion result
    """
    if auth is None:
        auth = DatadogAuth()
    
    # Use API client directly - no context manager needed
    api_instance = DashboardsApi(auth.api_client)
        
    try:
        api_instance.delete_dashboard(dashboard_id)
        
        return {
            "success": True,
            "dashboard_id": dashboard_id,
            "message": "Dashboard deleted successfully"
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
