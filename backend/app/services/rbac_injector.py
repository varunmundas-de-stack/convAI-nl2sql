"""
RBAC Context Injector for DSPy Pipeline

Builds RBAC hint strings and injects user authorization context into DSPy agents.
This ensures all agents are aware of user permissions and can generate appropriate queries.

DESIGN:
- UserContextInjector builds a concise RBAC hint string summarizing user permissions
- Hints are injected into DSPy session context for agents to reference
- build_rbac_filter() (from intel/rbac.py) generates WHERE clauses for Cube.js
- This module handles LLM prompt injection; filtering happens at query execution
"""

import logging
from typing import Optional

from app.security.context import UserContext
from app.intel.rbac import build_rbac_filter

logger = logging.getLogger(__name__)


class UserContextInjector:
    """Injects user RBAC context into DSPy pipeline."""

    @staticmethod
    def build_rbac_hint(user_context: Optional[UserContext]) -> str:
        """
        Build a concise RBAC hint string for LLM injection.

        Format:
        - ADMIN/NSM: "(Authorized for NATIONAL view of all data)"
        - ZSM: "(Authorized for zsm_name=XYZ: ASM/SO under your region)"
        - ASM: "(Authorized for asm_name=ABC: SO/SR under your area)"
        - SO: "(Authorized for so_code=SO001: own sales rep data only)"
        - SR: "(Authorized for salesrep_code=SR001: own sales rep data only)"

        Args:
            user_context: User's authorization context, or None for no filtering

        Returns:
            Concise RBAC hint string to inject into LLM prompts
        """
        if user_context is None:
            return ""

        role = user_context.role.upper()

        # Admin and NSM have unrestricted access
        if role in ("ADMIN", "NSM"):
            return "(Authorized for NATIONAL view of all data)"

        # ZSM can see team data (ASM/SO under region)
        if role == "ZSM" and user_context.zsm_code:
            return f"(Authorized for zsm_code={user_context.zsm_code}: ASM/SO under your region)"

        # ASM can see SO/SR in their area
        if role == "ASM" and user_context.asm_code:
            return f"(Authorized for asm_code={user_context.asm_code}: SO/SR under your area)"

        # SO and SR can see their own data
        if role == "SO" and user_context.so_code:
            return f"(Authorized for so_code={user_context.so_code}: own sales rep data only)"

        if role == "SR" and user_context.salesrep_code:
            return f"(Authorized for salesrep_code={user_context.salesrep_code}: own sales rep data only)"

        # Fallback for unknown role
        logger.warning(f"Unknown role {role} with codes: zsm={user_context.zsm_code}, "
                       f"asm={user_context.asm_code}, so={user_context.so_code}, "
                       f"sr={user_context.salesrep_code}")
        return "(Authorization scope: unknown role - query may be restricted)"

    @staticmethod
    def get_rbac_filter_for_cube(user_context: Optional[UserContext]) -> Optional[dict]:
        """
        Get RBAC filter dict to apply to Cube.js query.

        Args:
            user_context: User's authorization context

        Returns:
            Dict with 'dimension', 'operator', 'value' or None if no filtering needed
        """
        if user_context is None:
            return None

        # Use existing RBAC builder
        try:
            filter_clause = build_rbac_filter(
                role=user_context.role,
                zsm_code=user_context.zsm_code,
                asm_code=user_context.asm_code,
                so_code=user_context.so_code,
                salesrep_code=user_context.salesrep_code,
            )

            if not filter_clause:
                return None

            # Parse filter_clause (SQL WHERE format) into normalized filter dict
            # Example: "zsm_name = 'North'" -> {"dimension": "zsm_name", "operator": "equals", "value": "North"}
            return UserContextInjector._parse_rbac_filter(filter_clause)

        except Exception as e:
            logger.error(f"Error building RBAC filter for role {user_context.role}: {e}")
            return None

    @staticmethod
    def _parse_rbac_filter(filter_clause: str) -> Optional[dict]:
        """
        Parse SQL WHERE clause filter into normalized filter dict.

        Handles:
        - "zsm_name = 'value'" -> {"dimension": "zsm_name", "operator": "equals", "value": "value"}
        - "so_code IN ('val1','val2')" -> {"dimension": "so_code", "operator": "in", "value": ["val1", "val2"]}

        Args:
            filter_clause: SQL WHERE clause fragment

        Returns:
            Normalized filter dict or None if parsing fails
        """
        try:
            filter_clause = filter_clause.strip()

            # Handle IN operator
            if " IN " in filter_clause.upper():
                parts = filter_clause.upper().split(" IN ")
                if len(parts) != 2:
                    return None

                dimension = parts[0].strip()
                values_str = parts[1].strip()

                # Extract values from parentheses: ('val1','val2')
                if values_str.startswith("(") and values_str.endswith(")"):
                    values_str = values_str[1:-1]
                    # Split by comma and clean quotes
                    values = [v.strip().strip("'\"") for v in values_str.split(",")]
                    return {
                        "dimension": dimension,
                        "operator": "in",
                        "value": values,
                    }

            # Handle equals operator
            if " = " in filter_clause:
                parts = filter_clause.split(" = ")
                if len(parts) != 2:
                    return None

                dimension = parts[0].strip()
                value = parts[1].strip().strip("'\"")

                return {
                    "dimension": dimension,
                    "operator": "equals",
                    "value": value,
                }

            logger.warning(f"Could not parse RBAC filter: {filter_clause}")
            return None

        except Exception as e:
            logger.error(f"Error parsing RBAC filter '{filter_clause}': {e}")
            return None
