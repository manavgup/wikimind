"""Middleware stack for the WikiMind gateway.

Provides security headers, error handling, and other cross-cutting
concerns applied to every HTTP request.
"""

from wikimind.middleware.error_handling import ErrorHandlingMiddleware
from wikimind.middleware.security_headers import SecurityHeadersMiddleware

__all__ = ["ErrorHandlingMiddleware", "SecurityHeadersMiddleware"]
