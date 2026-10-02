"""Audit logging utilities for tracking important actions."""
import logging
from functools import wraps
from django.utils import timezone

# Get the audit logger configured in settings
audit_logger = logging.getLogger('quiz_platform.audit')


def log_action(action_type, user, details=None):
    """
    Log an audit action.
    
    Args:
        action_type (str): Type of action (e.g., 'QUIZ_CREATE', 'SESSION_START')
        user: Django User object (can be None for unauthenticated)
        details (dict): Additional details about the action
    """
    username = user.username if user and user.is_authenticated else 'anonymous'
    details_str = ' | ' + ' '.join(f'{k}={v}' for k, v in (details or {}).items()) if details else ''
    message = f'[{action_type}] User: {username} {details_str}'
    audit_logger.info(message)


def audit_view(action_type, details_func=None):
    """
    Decorator to audit view actions.
    
    Args:
        action_type (str): Type of action
        details_func: Optional function(request, response) -> dict for extracting details
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            response = view_func(request, *args, **kwargs)
            
            details = {}
            if details_func:
                try:
                    details = details_func(request, response) or {}
                except Exception as e:
                    details['error'] = str(e)
            
            log_action(action_type, request.user, details)
            return response
        return wrapper
    return decorator
