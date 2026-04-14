"""Central config: env vars, constants, table names."""
import os
from typing import Final

# AWS
AWS_REGION: Final[str] = os.environ.get("AWS_REGION", "us-east-1")

# DynamoDB tables
TABLE_AUDIT: Final[str] = "fabops_audit"
TABLE_SESSIONS: Final[str] = "fabops_sessions"
TABLE_FORECASTS: Final[str] = "fabops_forecasts"
TABLE_POLICIES: Final[str] = "fabops_policies"
TABLE_INVENTORY: Final[str] = "fabops_inventory"
TABLE_SUPPLIERS: Final[str] = "fabops_suppliers"
TABLE_EDGAR: Final[str] = "fabops_edgar_index"
TABLE_INCIDENTS: Final[str] = "fabops_incidents"
TABLE_MACRO: Final[str] = "fabops_macro_cache"

# S3 buckets
S3_FRONTEND: Final[str] = "fabops-copilot-frontend"
S3_ARTIFACTS: Final[str] = "fabops-copilot-artifacts"
S3_EVALS: Final[str] = "fabops-copilot-evals"

# LLM config
GEMINI_FLASH_MODEL: Final[str] = "gemini-2.5-flash"
GEMINI_PRO_MODEL: Final[str] = "gemini-2.5-pro"
CLAUDE_JUDGE_MODEL: Final[str] = "claude-haiku-4-5-20251001"

# Agent caps (from spec Section 4.2)
MAX_GEMINI_PRO_CALLS: Final[int] = 6
MAX_TOTAL_LLM_CALLS: Final[int] = 8
MAX_TOOL_CALLS: Final[int] = 15
LAMBDA_DEADLINE_SECONDS: Final[int] = 90

# Budget caps (from spec Section 14.1)
ANTHROPIC_HARD_CAP_USD: Final[float] = 9.00
OPENAI_HARD_CAP_USD: Final[float] = 4.00
