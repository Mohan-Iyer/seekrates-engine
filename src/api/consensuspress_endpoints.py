#!/usr/bin/env python3
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
# v1.3.0 - 2026-04-19: CCI-SE-235-01 (INDRA-235) — FLAG-226-01 close-out.
#   Response envelope now includes credits_used + credits_limit
#   (post-increment state). Caller unpacks 5-tuple from check_cp_credits.
#   Additive only — no existing fields removed or renamed.
# v1.2.0 - 2026-04-10: CCI-SE-198 (INDRA-198) — Server-side credit enforcement.
#   SE-189B-02: cp_billing.check_cp_credits() enforces per-cycle quota.
#   SE-189B-03: Response envelope includes credits_remaining + tier.
#   HTTP 402 on credit exhaustion. increment_credits_used() on success only.
#   user_manager import removed (unused). cp_billing import added.
#   Authority: INDRA-198, Option A (single shared CONSENSUSPRESS_API_KEY).
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
from pydantic import BaseModel, validator
from typing import Optional

from src.agents.consensus_engine import generate_expert_panel_response_v4
from src.billing.cp_billing import check_cp_credits, increment_credits_used

router = APIRouter(prefix="/api/v1/cp", tags=["consensuspress"])


# =============================================================================
# REQUEST MODEL
# =============================================================================

class ConsensusPressRequest(BaseModel):
    """
    Request body for POST /api/v1/cp/consensus.

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

    Auth: Bearer API key validated against CONSENSUSPRESS_API_KEY env var.
    Enforcement: Server-side credit ledger via cp_billing (INDRA-198 SE-189B-02).
    Response: Includes credits_remaining + tier for plugin display cache
              (INDRA-198 SE-189B-03 — tier sync via consensus response).

    HTTP 402 returned on credit exhaustion. HTTP 401 on invalid/missing key.
    HTTP 500 on server config error or engine failure.

    Args:
        request:       Validated ConsensusPressRequest body.
        authorization: HTTP Authorization header ('Bearer <api_key>').

    Returns:
        dict: {
            "success": True,
            "data": {...ConsensusResult fields..., "query": str, "mode": str},
            "credits_remaining": int,  -- post-decrement (display-ready)
            "credits_used": int,       -- post-increment (display-ready)
            "credits_limit": int,      -- cycle cap per tier
            "tier": str                -- "free" | "silver" | "gold"
        }

    Raises:
        HTTPException 401: Missing or invalid Authorization header / API key.
        HTTPException 402: Credit limit reached for this billing cycle.
        HTTPException 500: Server config error or engine failure.
    """

    # -------------------------------------------------------------------------
    # 1. Validate CP API key
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

    # -------------------------------------------------------------------------
    # 2. Credit enforcement (SE-189B-02)
    #    check_cp_credits() inserts cycle row if missing, checks limit.
    #    Does NOT increment — increment happens after successful consensus only.
    # -------------------------------------------------------------------------
    allowed, credits_remaining, credits_used, credits_limit, cp_tier = check_cp_credits(cp_api_key)

    if not allowed:
        raise HTTPException(
            status_code=402,
            detail="Credit limit reached for this billing cycle.",
        )

    # -------------------------------------------------------------------------
    # 3. Call consensus engine
    #    Tier passed to engine = 'oracle' — SE engine tier, unchanged.
    #    cp_tier is the CP billing tier (free/silver/gold) — display only.
    # -------------------------------------------------------------------------
    try:
        result = await generate_expert_panel_response_v4(
            query=request.query,
            providers=["openai", "claude", "gemini", "mistral", "cohere"],
            tier="oracle",
        )
    except Exception as exc:  # pragma: no cover — engine errors logged server-side
        raise HTTPException(
            status_code=500,
            detail="Consensus engine failure. Please try again.",
        ) from exc

    # -------------------------------------------------------------------------
    # 4. Increment credits_used on success only (SE-189B-02)
    # -------------------------------------------------------------------------
    increment_credits_used(cp_api_key)

    # -------------------------------------------------------------------------
    # 5. Build response envelope (SE-189B-03 — tier sync via response)
    #    Plugin reads credits_remaining + tier for display cache (wp_options).
    #    Railway 402 = sole enforcement gate (D-37-SECURITY-FINAL-01).
    #    FLAG-226-01 close-out (CCI-SE-235-01): credits_used + credits_limit
    #    added to envelope for plugin progress UI. All 4 billing fields
    #    emit post-increment state.
    # -------------------------------------------------------------------------
    data = result.model_dump()
    data["query"] = request.query   # D-08-08: query injected by endpoint
    data["mode"] = request.mode     # mode forwarded for plugin context

    return {
        "success": True,
        "data": data,
        "credits_remaining": credits_remaining - 1,  # post-increment value
        "credits_used": credits_used + 1,
        "credits_limit": credits_limit,
        "tier": cp_tier,
    }
