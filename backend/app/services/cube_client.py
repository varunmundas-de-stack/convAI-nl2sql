"""
Cube Client - HTTP transport layer for Cube.js API.

This module handles communication with the Cube.js REST API.
It is a TRANSPORT LAYER only - no business logic.

RESPONSIBILITIES:
1. Send queries to Cube's REST API (/cubejs-api/v1/load)
2. Handle authentication (API secret)
3. Handle HTTP transport concerns (timeouts, retries, errors)
4. Return Cube's response verbatim

This module does NOT:
- Interpret results
- Summarize data
- Reshape metrics
- Apply business rules
- Validate query structure (that's upstream)
"""

import os
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


# =============================================================================
# CONFIGURATION
# =============================================================================

CUBE_API_URL = os.getenv("CUBE_API_URL", "http://localhost:4000/cubejs-api/v1")
CUBE_API_SECRET = os.getenv("CUBE_API_SECRET", "")

# Execution guardrails
REQUEST_TIMEOUT_SECONDS = float(os.getenv("CUBE_REQUEST_TIMEOUT", "30.0"))
MAX_ROWS_LIMIT = int(os.getenv("CUBE_MAX_ROWS", "10000"))

# Retry configuration
MAX_RETRIES = 1  # Single retry on transient failures


# =============================================================================
# EXCEPTIONS (Transport-level only)
# =============================================================================

class CubeClientError(Exception):
    """Base exception for Cube client errors."""
    pass


class CubeConnectionError(CubeClientError):
    """Failed to connect to Cube service."""
    pass


class CubeTimeoutError(CubeClientError):
    """Cube request timed out."""
    pass


class CubeHTTPError(CubeClientError):
    """Cube returned an HTTP error."""
    
    def __init__(self, message: str, status_code: int, response_body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class CubeServiceUnavailable(CubeClientError):
    """Cube service is unavailable (503)."""
    pass


class CubeQueryTooLarge(CubeClientError):
    """Query would return too many rows."""
    pass


# =============================================================================
# RESPONSE WRAPPER
# =============================================================================

@dataclass(frozen=True)
class CubeResponse:
    """
    Wrapper for Cube API response.
    
    Contains raw Cube response data plus transport metadata.
    Does NOT interpret or reshape the data.
    """
    # Raw Cube response fields
    data: list[dict[str, Any]]
    annotation: dict[str, Any] | None = None
    query: dict[str, Any] | None = None
    slow_query: bool = False
    
    # Transport metadata
    request_id: str = ""
    
    @classmethod
    def from_cube_response(cls, response_json: dict[str, Any], request_id: str) -> "CubeResponse":
        """Create CubeResponse from raw Cube JSON response."""
        return cls(
            data=response_json.get("data", []),
            annotation=response_json.get("annotation"),
            query=response_json.get("query"),
            slow_query=response_json.get("slowQuery", False),
            request_id=request_id,
        )


# =============================================================================
# CLIENT CLASS
# =============================================================================

class CubeClient:
    """
    HTTP client for Cube.js REST API.
    
    Handles transport-level concerns:
    - HTTP connection/errors
    - Timeouts
    - Retries (minimal)
    - Authentication
    - Request IDs
    
    Does NOT handle:
    - Query building (upstream)
    - Result interpretation (downstream)
    - Business logic
    
    Usage:
        client = CubeClient()
        response = client.load(query_json)
        print(response.data)
    """
    
    def __init__(
        self,
        base_url: str | None = None,
        api_secret: str | None = None,
        timeout: float | None = None,
        max_rows: int | None = None,
    ):
        """
        Initialize Cube client.
        
        Args:
            base_url: Cube API base URL (default: from env CUBE_API_URL)
            api_secret: Cube API secret (default: from env CUBE_API_SECRET)
            timeout: Request timeout in seconds (default: from env CUBE_REQUEST_TIMEOUT)
            max_rows: Maximum rows to allow (default: from env CUBE_MAX_ROWS)
        """
        self.base_url = base_url or CUBE_API_URL
        self.api_secret = api_secret or CUBE_API_SECRET
        self.timeout = timeout or REQUEST_TIMEOUT_SECONDS
        self.max_rows = max_rows or MAX_ROWS_LIMIT
    
    def _generate_request_id(self) -> str:
        """Generate unique request ID for tracing."""
        return str(uuid.uuid4())[:8]
    
    def _build_headers(self, request_id: str) -> dict[str, str]:
        """Build HTTP headers for Cube request."""
        headers = {
            "Content-Type": "application/json",
            "X-Request-Id": request_id,
        }
        
        # Add authorization if secret is configured
        if self.api_secret:
            headers["Authorization"] = self.api_secret
        
        return headers
    
    def _enforce_guardrails(self, query: dict[str, Any]) -> dict[str, Any]:
        """
        Apply execution guardrails to query.
        
        - Enforce max rows limit
        - (Future: other guardrails)
        
        Returns modified query (does not mutate original).
        """
        query = query.copy()
        
        # Enforce max rows limit
        query_limit = query.get("limit", self.max_rows)
        if query_limit > self.max_rows:
            raise CubeQueryTooLarge(
                f"Query limit ({query_limit}) exceeds maximum allowed ({self.max_rows})"
            )
        
        # Ensure limit is always set
        if "limit" not in query:
            query["limit"] = self.max_rows
        
        return query
    
    def load(self, query: dict[str, Any]) -> CubeResponse:
        """
        Execute a Cube load query.
        
        This is the main entry point for querying Cube.
        
        Args:
            query: Cube query JSON (measures, dimensions, filters, etc.)
            
        Returns:
            CubeResponse with raw Cube data
            
        Raises:
            CubeConnectionError: Cannot connect to Cube
            CubeTimeoutError: Request timed out
            CubeHTTPError: Cube returned HTTP error
            CubeServiceUnavailable: Cube service is down
            CubeQueryTooLarge: Query exceeds row limit
        """
        request_id = self._generate_request_id()
        
        # Apply guardrails
        query = self._enforce_guardrails(query)
        
        # Build request
        url = f"{self.base_url}/load"
        headers = self._build_headers(request_id)
        
        # Execute with retry
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                return self._execute_request(url, headers, query, request_id)
            except (CubeConnectionError, CubeTimeoutError) as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    continue  # Retry on transient errors
                raise
            except CubeHTTPError:
                raise  # Don't retry HTTP errors
        
        # Should not reach here, but satisfy type checker
        raise last_error  # type: ignore
    
    def _execute_request(
        self,
        url: str,
        headers: dict[str, str],
        query: dict[str, Any],
        request_id: str,
    ) -> CubeResponse:
        """Execute HTTP request to Cube."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    url,
                    json={"query": query},
                    headers=headers,
                )
        except httpx.ConnectError as e:
            raise CubeConnectionError(f"Cannot connect to Cube at {url}: {e}") from e
        except httpx.TimeoutException as e:
            raise CubeTimeoutError(f"Cube request timed out after {self.timeout}s") from e
        except httpx.HTTPError as e:
            raise CubeConnectionError(f"HTTP error: {e}") from e
        
        # Handle HTTP status codes
        if response.status_code == 503:
            raise CubeServiceUnavailable("Cube service is unavailable (503)")
        
        if response.status_code >= 400:
            try:
                error_body = response.json()
            except Exception:
                error_body = response.text
            
            raise CubeHTTPError(
                f"Cube returned HTTP {response.status_code}",
                status_code=response.status_code,
                response_body=error_body,
            )
        
        # Parse successful response
        try:
            response_json = response.json()
        except Exception as e:
            raise CubeClientError(f"Invalid JSON response from Cube: {e}") from e
        
        return CubeResponse.from_cube_response(response_json, request_id)


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

def execute_cube_query(query: dict[str, Any]) -> CubeResponse:
    """
    Convenience function to execute a Cube query.
    
    Creates a CubeClient and executes the query.
    
    Args:
        query: Cube query JSON
        
    Returns:
        CubeResponse with raw data
        
    Example:
        >>> query = {"measures": ["sales_fact.count"], "limit": 100}
        >>> response = execute_cube_query(query)
        >>> print(response.data)
    """
    client = CubeClient()
    return client.load(query)
