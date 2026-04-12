"""
CubeDBTool

Stateless, reusable wrapper around CubeClient.
No pipeline context dependency — takes a query dict, returns rows.

Can be used:
  - As an injected dependency in pipeline steps (current use)
  - As a DSPy tool in an agentic pipeline (future use)
"""

import logging
import time

from app.services.cube.cube_client import CubeClient, CubeHTTPError, CubeQueryExecutionError

logger = logging.getLogger(__name__)

_RETRY_DELAY_SECONDS = 0.3


class CubeDBTool:
    """Executes a pre-built Cube.js query and returns result rows.

    Responsibilities:
      - SQL validation via get_sql
      - Query execution via load
      - Single retry on empty result
      - No knowledge of pipeline state, intent, or strategy

    Usage:
        db = CubeDBTool()
        rows = db.run(query_dict)

    Raises:
        CubeHTTPError            — on HTTP-level failures (caller decides fatality)
        CubeQueryExecutionError  — on execution-level failures (caller decides fatality)
    """

    def run(self, query: dict) -> list:
        """Execute a Cube.js query dict and return result rows.

        Args:
            query: A fully-built Cube.js query dict (measures, dimensions, filters, etc.)

        Returns:
            List of result row dicts. May be empty.

        Raises:
            CubeHTTPError, CubeQueryExecutionError
        """
        client = CubeClient()

        # Validate query SQL before executing (catches schema/measure errors early)
        client.get_sql(query)

        data = client.load(query).data

        if not data:
            logger.warning("CubeDBTool: query returned 0 rows, retrying once...")
            time.sleep(_RETRY_DELAY_SECONDS)
            data = client.load(query).data

        return data