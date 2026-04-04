# =============================================================================
# SCRIPT DNA METADATA - GPS FOUNDATION COMPLIANT
# =============================================================================
# CORE METADATA:
# =============================================================================
# =============================================================================
# PURPOSE AND DESCRIPTION:
# =============================================================================
# =============================================================================
# DEFINES:
# =============================================================================
# defines_classes: "None"
# defines_functions: "consensuspress_endpoint"
# =============================================================================
# DEPENDENCIES:
# =============================================================================
# =============================================================================
# FIELD CONTRACTS:
# =============================================================================
#   input_sources:
#     - path: "POST /api/v1/cp/consensus"
#       type: "HTTP_Request"
#   output_destinations:
#     - path: "src/server/main.py"
#       type: "consensuspress_router"
# =============================================================================
# CHANGE LOG:
# =============================================================================
# v1.1.0 - 2026-03-30: CCI-SE-CP-02 (INDRA-165) — Replace session token auth
#   with CONSENSUSPRESS_API_KEY env var auth. Oracle tier applied on valid key.
#   T&C gate, rate limit gate, user_manager lookup removed for API key auth
#   path. Pre-Stripe phase. Future: replace with Stripe-based tier auth.
# v1.0.1 - 2026-03-24: CCI_SE_ILL2_01 — GPS DNA header added (ILL-2 repair)
# v1.0.0 - 2026-02-25: Initial production release (C-C Session 09, Sprint 7)
# === END OF SCRIPT DNA HEADER ====================================

import os
import logging
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, validator
from typing import Optional

from src.agents.consensus_engine import generate_expert_panel_response_v4
from src.auth.user_manager import UserManager

router = APIRouter(prefix="/api/v1/cp", tags=["consensuspress"])
user_manager = UserManager()


# =============================================================================
# REQUEST MODEL
# =============================================================================

class ConsensusPressRequest(BaseModel):
    """
    Request body for POST /api/v1/consensus.

    Attributes:
        query:   The topic or question to pass to the consensus engine.
                 Minimum 10 characters after strip.
        mode:    'create' (new post) or 'rescue' (restructure existing content).
        context: Optional additional context for rescue mode. Max 2000 chars.
    """

    query: str
    mode: str = "create"
    context: str = ""

    @validator("query")
    def query_min_length(cls, v: str) -> str:  # noqa: N805
        """Reject queries shorter than 10 characters."""
        if len(v.strip()) < 10:
            raise ValueError("Query must be at least 10 characters")
        return v

    @validator("mode")
    def mode_valid(cls, v: str) -> str:  # noqa: N805
        """Reject modes other than 'create' and 'rescue'."""
        if v not in ("create", "rescue"):
            raise ValueError("Mode must be 'create' or 'rescue'")
        return v


# =============================================================================
# ENDPOINT
# =============================================================================

@router.post("/consensus")
async def consensuspress_endpoint(
    request: ConsensusPressRequest,
    authorization: Optional[str] = Header(None),
) -> dict:
    """
    ConsensusPress plugin consensus endpoint.

    Validates the Bearer API key against CONSENSUSPRESS_API_KEY env var,
    applies Oracle tier (D-SE-03 minimum), calls generate_expert_panel_response_v4(),
    and returns the full ConsensusResult as JSON with query and mode injected.

    Auth path: API key comparison only. No session token. No user_manager lookup.
    No T&C gate. No rate limit gate. Pre-Stripe phase — see future migration note
    in CCI-SE-CP-02.

    Args:
        request:       Validated ConsensusPressRequest body.
        authorization: HTTP Authorization header ('Bearer <api_key>').

    Returns:
        dict: {"success": True, "data": {...ConsensusResult fields..., "query": str, "mode": str}}

    Raises:
        HTTPException 401: Missing or invalid Authorization header / API key.
        HTTPException 500: Server config error (key not set) or engine failure.
    """

    # -------------------------------------------------------------------------
    # 1. Validate CP API key (INDRA-165 Option B — pre-Stripe phase)
    #    FUTURE: replace with Stripe-based tier auth when Stripe live.
    # -------------------------------------------------------------------------
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header.",
        )

    token = authorization.split(" ", 1)[1].strip()
    cp_api_key = os.environ.get("CONSENSUSPRESS_API_KEY", "")

    if not cp_api_key:
        logging.error("[CP-AUTH] CONSENSUSPRESS_API_KEY not set in environment.")
        raise HTTPException(
            status_code=500,
            detail="Server configuration error. Contact administrator.",
        )

    if token != cp_api_key:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key.",
        )

    # Valid API key — apply Oracle tier directly (D-SE-03 minimum).
    # No user_manager lookup. No T&C gate. No rate limit gate.
    # These gates are bypassed for the API key auth path.
    user_email = "consensuspress@seekrates-engine.internal"
    user_tier = "oracle"  # D-SE-27: Oracle-unconditional — DEPRECATED-PENDING tier resolution layer (INDRA-172 scope boundary)

    # -------------------------------------------------------------------------
    # 2. Call consensus engine
    # -------------------------------------------------------------------------
    try:
        result = await generate_expert_panel_response_v4(
            query=request.query,
            providers=["openai", "claude", "gemini", "mistral", "cohere"],
            tier=user_tier,
        )
    except Exception as exc:  # pragma: no cover — engine errors logged server-side
        raise HTTPException(
            status_code=500,
            detail="Consensus engine failure. Please try again.",
        ) from exc

    # -------------------------------------------------------------------------
    # 3. Serialise + inject query and mode (query is NOT in ConsensusResult model)
    # -------------------------------------------------------------------------
    data = result.model_dump()
    data["query"] = request.query   # D-08-08: query injected by endpoint
    data["mode"] = request.mode     # mode forwarded for plugin context

    return {"success": True, "data": data}