#!/usr/bin/env python3
# =============================================================================
# SCRIPT DNA METADATA - GPS FOUNDATION COMPLIANT
# =============================================================================
# =============================================================================
# PURPOSE AND DESCRIPTION:
# =============================================================================
# =============================================================================
# VERSION HISTORY:
# =============================================================================
# =============================================================================
# DEFINES:
# =============================================================================
# defines_classes: |
# defines_functions: "None"
# =============================================================================
# DEPENDENCIES:
# =============================================================================
# =============================================================================
# FIELD CONTRACTS:
# =============================================================================
# =============================================================================
# TRANSFORMS:
# =============================================================================
# new_section_transforms: |
# === END OF SCRIPT DNA HEADER ====================================

from typing_extensions import TypedDict
from typing import List, Optional, Dict, Any

# =============================================================================
# SUB-TYPES (v2.0.0 — replaces Dict[str, Any] where structure is known)
# Source evidence in response_transformer.py lines cited per field
# =============================================================================

class SocratesAgentResponse(TypedDict):
    """Individual agent response in Socrates format.
    Structure fully known — built in response_transformer.py L171-177.
    """
    agent: str           # agent_name.replace('_', ' ').title()
    content: str         # response_data.get('response', '').strip()
    word_count: int      # response_data.get('word_count', ...)
    score: int           # int(min(100, max(0, confidence * 100)))
    response_time: float # response_data.get('latency_ms', 0) / 1000.0


class SocratesMetrics(TypedDict):
    """Socrates format metrics dict.
    Structure fully known — built in response_transformer.py L220-226.
    """
    response_count: int   # len(responses)
    total_words: int      # sum(r['word_count'] for r in responses)
    total_tokens: int     # sum(r.get('tokens', 0) for r in raw_responses)
    champion_score: int   # champion_response['score']
    process_time: float   # round(processing_time, 1)


class AgentScore(TypedDict):
    """Per-agent score entry in SocratesResponse.agents dict.
    Structure fully known — built in response_transformer.py L179-182.
    """
    score: int      # int(min(100, max(0, confidence * 100)))
    champion: bool  # True if agent_name matches champion


class ProviderResponseItem(TypedDict, total=False):
    """Individual provider response item in panel/responses/successful_responses lists.
    total=False: fields are optional — dict is populated in multiple locations
    with different subsets. Known minimum from response_transformer.py L101, L163-177.
    """
    agent: str
    success: bool
    response: str
    word_count: int
    confidence: float
    latency_ms: int
    error: Optional[str]


class BackendMetadata(TypedDict, total=False):
    """Metadata dict in BackendResponse.
    total=False: populated in multiple locations with different subsets.
    Known fields from response_transformer.py L74/L122 + consensus_engine.py L1486-1492.
    """
    session_id: str
    error: str
    success_count: int
    failure_count: int
    elapsed_time: str
    total_tokens: int


# =============================================================================
# CONTRACTS (public interface — all existing classes preserved)
# =============================================================================

class FrontendRequest(TypedDict):
    """Explicit contract for frontend requests"""
    query: str
    agents: List[str]
    # HAL-001-DEFERRED: Frontend-controlled options — structure not owned by server
    options: Optional[Dict[str, Any]]
    session_id: Optional[str]


class BackendResponse(TypedDict):
    """Explicit contract ensuring frontend compatibility"""
    consensus: str
    confidence: float
    panel: List[ProviderResponseItem]
    metadata: BackendMetadata
    session_id: str
    consensus_panel: str  # Alias for frontend compatibility
    participating_agents: List[str]
    champion: Optional[str]
    scores: Dict[str, float]
    responses: List[ProviderResponseItem]
    # HAL-001-DEFERRED [TYPE-B] D-SE-TYPEB-001
    # reason: same metrics shape dependency as TB-SE-005
    # trigger: consensus_engine.py contract sprint — resolve together
    metrics: Dict[str, Any]  # HAL-001-DEFERRED [ARCH_EXCEPTION] EX-SE-023
    agents_total: int
    agents_responded: int
    successful_responses: List[ProviderResponseItem]
    agent_status: Dict[str, str]
    response_count: int  # UI counter alias
    agent_count: int     # UI counter alias


class AgentResponse(TypedDict):
    """Internal agent response structure"""
    agent_id: str
    content: str
    confidence: float
    # HAL-001-DEFERRED: Callers not fully enumerated — trace all producers before typing
    metadata: Dict[str, Any]
    success: bool
    word_count: int
    response_time: float
    tokens: int
    error: Optional[str]


class SocratesResponse(TypedDict):
    """Socrates v4.1 compatibility format"""
    success: bool
    responses: List[SocratesAgentResponse]
    synthesis: str
    champion: Optional[str]
    metrics: SocratesMetrics
    agents: Dict[str, AgentScore]
    error: Optional[str]
    trace: Optional[str]


class ConsensusRequest(TypedDict):
    """Internal consensus request structure"""
    query: str
    agents: List[str]
    timeout: int
    max_tokens: int
    temperature: float
    session_id: Optional[str]


class ProviderResponse(TypedDict):
    """Provider API response structure"""
    status: str
    response: str
    confidence: float
    latency_ms: int
    usage: Optional[Dict[str, int]]
    error: Optional[str]
    model_used: Optional[str]


class SessionState(TypedDict):
    """Session state structure"""
    session_id: str
    query_history: List[str]
    # HAL-001-DEFERRED: Population source not found in examined files — enumerate callers
    response_history: List[Dict[str, Any]]
    agent_preferences: List[str]
    created_at: str
    updated_at: str
    # HAL-001-DEFERRED: Population source not found in examined files — enumerate callers
    metadata: Dict[str, Any]