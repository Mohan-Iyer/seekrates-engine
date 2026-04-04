#!/usr/bin/env python3
# filename: seekrates_engine_production/src/utils/tier_response_formatter.py
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
# defines_classes: "RawConsensusDict, RawConsensusInnerDict, RawProviderResponseDict, FormattedLLMResponse, FormattedResponse, TierFeatures, TierConfig"
# defines_functions: "format_response_for_tier, get_tier_config, _extract_synthesis, _extract_dissenting_view, _extract_confidence, _format_synthesis, _strip_html_tags, _format_llm_responses, get_tier_code, should_show_llm_responses, get_llm_truncate_limit"
# =============================================================================
# DEPENDENCIES:
# =============================================================================
# =============================================================================
# FIELD CONTRACTS:
# =============================================================================
#   input_sources:
#     - path: "src/agents/consensus_contract.py"
#       type: "ConsensusResult_Dict"
#     - path: "src/billing/stripe_integration.py"
#       type: "UserTierInfo"
#   output_destinations:
#     - path: "src/utils/email_notifier.py"
#       type: "FormattedResponse"
#     - path: "src/api/auth_endpoints.py"
#       type: "FormattedLLMResponse"
# =============================================================================
# CHANGE LOG:
# =============================================================================
# v2.1.0 - 2026-03-25: CCI_SE_ILL3_03 — 5 Dict[str,Any] params replaced with
#   RawConsensusDict/RawProviderResponseDict TypedDicts. Annotation only — zero
#   logic changes. project_name corrected seekrates_ai → seekrates_engine.
# v2.0.0 - 2026-02-26: HAL-001 sprint — 1 return annotation fixed, 5 deferred.
# v1.0.0 - 2026-02-25: Previous production release.
# === END OF SCRIPT DNA HEADER ====================================

from pydantic import BaseModel
from typing import Optional, List, Dict, Any, TypedDict
import os
import logging

logger = logging.getLogger(__name__)

# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class FormattedLLMResponse(BaseModel):
    """Individual LLM response, possibly truncated."""
    provider: str
    response: str
    truncated: bool = False
    original_length: Optional[int] = None


class FormattedResponse(BaseModel):
    """Tier-formatted consensus response."""
    synthesis: str
    synthesis_format: str  # "one_paragraph", "detailed", "full"
    llm_responses: Optional[List[FormattedLLMResponse]] = None
    show_llm_responses: bool
    dissenting_view: Optional[str] = None
    show_dissenting_view: bool
    upgrade_prompt: Optional[str] = None
    tier_code: str
    tier_name: str
    query: str
    confidence_score: float


# =============================================================================
# HAL-001 TYPED RESULT CLASSES
# =============================================================================

class TierFeatures(TypedDict, total=False):
    """Tier response_features config block. total=False: synthesis_max_chars
    and llm_response_truncate absent for oracle/sage tiers (None treated as absent)."""
    synthesis_format: str
    synthesis_max_chars: Optional[int]
    show_individual_llm: bool
    llm_response_truncate: Optional[int]
    show_dissenting_view: bool


class TierConfig(TypedDict):
    """Return type for get_tier_config(). Both fields always present."""
    code: str
    response_features: TierFeatures


# =============================================================================
# RAW CONSENSUS DICT TYPEDICTS (CCI_SE_ILL3_03)
# tier_response_formatter receives the RAW consensus engine output dict,
# not ConsensusResult Pydantic model. These TypedDicts describe that shape.
# =============================================================================

class RawConsensusDict(TypedDict, total=False):
    """Raw consensus engine output dict as received by tier_response_formatter.
    total=False: not all keys present in all call paths.
    Shape confirmed from consensus_engine.py output + formatter access patterns."""
    query: str
    consensus: Dict[str, Any]      # ConsensusMetadata as dict — contains synthesis, panel etc  # HAL-001-DEFERRED [ARCH_EXCEPTION] EX-SE-009
    responses: List[Dict[str, Any]]  # Provider responses list  # HAL-001-DEFERRED [ARCH_EXCEPTION] EX-SE-010
    divergence: Dict[str, Any]     # DivergenceReport as dict (Optional)  # HAL-001-DEFERRED [ARCH_EXCEPTION] EX-SE-011
    risk_analysis: Dict[str, Any]  # OracleRiskAnalysis as dict (Optional)  # HAL-001-DEFERRED [ARCH_EXCEPTION] EX-SE-012
    tier: str


class RawConsensusInnerDict(TypedDict, total=False):
    """Inner 'consensus' dict within RawConsensusDict.
    Fields confirmed from ConsensusMetadata model in consensus_contract.py."""
    consensus_panel: str
    champion: str
    champion_score: int
    confidence: float
    consensus_text: str
    divergence_highlight: str
    dissenting_provider: str
    dissent_confidence: float
    convergence_count: int
    convergence_percentage: int
    consensus_confidence: str
    agreement_percentage: float
    reached: bool
    synthesis: str


class RawProviderResponseDict(TypedDict, total=False):
    """Individual provider response dict in responses list.
    Confirmed from _format_llm_responses access patterns."""
    provider: str
    answer: str
    response: str
    confidence: float
    score: int


# =============================================================================
# TIER CONFIGURATION (Defaults - can be overridden by system.yaml)
# =============================================================================

DEFAULT_TIER_CONFIG = {
    "seeker": {
        "code": "SEK",
        "response_features": {
            "synthesis_format": "one_paragraph",
            "synthesis_max_chars": 600,
            "show_individual_llm": False,
            "llm_response_truncate": None,
            "show_dissenting_view": True
        }
    },
    "acolyte": {
        "code": "AKO",
        "response_features": {
            "synthesis_format": "detailed",
            "synthesis_max_chars": 2000,
            "show_individual_llm": True,
            "llm_response_truncate": 500,
            "show_dissenting_view": True
        }
    },
    "oracle": {
        "code": "ORA",
        "response_features": {
            "synthesis_format": "full",
            "synthesis_max_chars": None,
            "show_individual_llm": True,
            "llm_response_truncate": None,
            "show_dissenting_view": True
        }
    },
    "sage": {
        "code": "SAG",
        "response_features": {
            "synthesis_format": "full",
            "synthesis_max_chars": None,
            "show_individual_llm": True,
            "llm_response_truncate": None,
            "show_dissenting_view": True
        }
    },
    # Legacy mapping for 'free' tier name
    "free": {
        "code": "SEK",
        "response_features": {
            "synthesis_format": "one_paragraph",
            "synthesis_max_chars": 600,
            "show_individual_llm": False,
            "llm_response_truncate": None,
            "show_dissenting_view": True
        }
    }
}

UPGRADE_PROMPTS = {
    "SEK": "Want to see what each AI said? Upgrade to Acolyte →",
    "AKO": "Need full AI responses? Upgrade to Oracle →",
    "ORA": None,
    "SAG": None
}


# =============================================================================
# CORE FUNCTION
# =============================================================================

def format_response_for_tier(
    consensus_result: RawConsensusDict,  # CCI_SE_ILL3_03: RawConsensusDict replaces Dict[str,Any]  # HAL-001-DEFERRED [ARCH_EXCEPTION] EX-SE-013
    tier_name: str = "seeker"
) -> FormattedResponse:
    """
    Apply tier-specific formatting to consensus result.

    Args:
        consensus_result: Full output from consensus_engine (dict)
        tier_name: User's tier name ("seeker", "acolyte", "oracle", "sage", "free")

    Returns:
        FormattedResponse with tier-appropriate content
    """
    # Normalize tier name
    tier_name_lower = tier_name.lower() if tier_name else "seeker"

    # Get tier config (use defaults, could extend to read from system.yaml)
    tier_config = get_tier_config(tier_name_lower)
    features = tier_config.get('response_features', {})
    tier_code = tier_config.get('code', 'SEK')

    logger.info(f"[FORMATTER] Formatting for tier: {tier_name_lower} ({tier_code})")

    # 1. Format synthesis based on tier
    raw_synthesis = _extract_synthesis(consensus_result)
    synthesis = _format_synthesis(
        raw_synthesis,
        features.get('synthesis_format', 'full'),
        features.get('synthesis_max_chars')
    )

    # 2. Handle LLM responses (show/hide/truncate)
    llm_responses = None
    show_llm = features.get('show_individual_llm', True)

    if show_llm:
        truncate_limit = features.get('llm_response_truncate')
        llm_responses = _format_llm_responses(
            consensus_result.get('responses', []),
            truncate_limit
        )

    # 3. Handle dissenting view
    dissenting = None
    show_dissenting = features.get('show_dissenting_view', True)
    if show_dissenting:
        dissenting = _extract_dissenting_view(consensus_result)

    # 4. Generate upgrade prompt if applicable
    upgrade_prompt = UPGRADE_PROMPTS.get(tier_code)

    # 5. Extract query and confidence
    query = consensus_result.get('query', '')
    confidence = _extract_confidence(consensus_result)

    return FormattedResponse(
        synthesis=synthesis,
        synthesis_format=features.get('synthesis_format', 'full'),
        llm_responses=llm_responses,
        show_llm_responses=show_llm,
        dissenting_view=dissenting,
        show_dissenting_view=show_dissenting,
        upgrade_prompt=upgrade_prompt,
        tier_code=tier_code,
        tier_name=tier_name_lower,
        query=query,
        confidence_score=confidence
    )


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_tier_config(tier_name: str) -> TierConfig:
    """
    Get tier configuration.

    Currently uses DEFAULT_TIER_CONFIG.
    Could be extended to read from system.yaml.

    Args:
        tier_name: Tier name (seeker, acolyte, oracle, sage, free)

    Returns:
        Tier configuration dict
    """
    return DEFAULT_TIER_CONFIG.get(tier_name, DEFAULT_TIER_CONFIG["seeker"])


def _extract_synthesis(consensus_result: RawConsensusDict) -> str:  # CCI_SE_ILL3_03: RawConsensusDict replaces Dict[str,Any]  # HAL-001-DEFERRED [ARCH_EXCEPTION] EX-SE-014
    """Extract synthesis text from consensus result."""
    # Try multiple paths where synthesis might be stored
    consensus = consensus_result.get('consensus', {})

    # Path 1: consensus.synthesis
    if isinstance(consensus, dict):
        synthesis = consensus.get('synthesis', '')
        if synthesis:
            return str(synthesis)

    # Path 2: consensus_panel (might contain HTML)
    panel = consensus.get('consensus_panel', '')
    if panel:
        if isinstance(panel, dict):
            return panel.get('synthesis', panel.get('html', str(panel)))
        return str(panel)

    # Path 3: Direct synthesis key
    direct = consensus_result.get('synthesis', '')
    if direct:
        return str(direct)

    return ""


def _extract_dissenting_view(consensus_result: RawConsensusDict) -> Optional[str]:  # CCI_SE_ILL3_03: RawConsensusDict replaces Dict[str,Any]  # HAL-001-DEFERRED [ARCH_EXCEPTION] EX-SE-015
    """Extract dissenting/minority view from consensus result."""
    consensus = consensus_result.get('consensus', {})

    # Try various keys where dissenting view might be
    for key in ['dissenting_view', 'minority_view', 'outlier', 'dissent']:
        if isinstance(consensus, dict) and key in consensus:
            return str(consensus[key])

    # Check divergence data
    divergence = consensus_result.get('divergence', {})
    if divergence and divergence.get('outliers'):
        outliers = divergence['outliers']
        if isinstance(outliers, list) and outliers:
            return str(outliers[0])

    return None


def _extract_confidence(consensus_result: RawConsensusDict) -> float:  # CCI_SE_ILL3_03: RawConsensusDict replaces Dict[str,Any]  # HAL-001-DEFERRED [ARCH_EXCEPTION] EX-SE-016
    """Extract confidence score from consensus result."""
    consensus = consensus_result.get('consensus', {})

    if isinstance(consensus, dict):
        # Try various keys
        for key in ['confidence_score', 'agreement_percentage', 'confidence', 'score']:
            if key in consensus:
                try:
                    return float(consensus[key])
                except (ValueError, TypeError):
                    pass

    return 0.0


def _format_synthesis(synthesis: str, format_type: str, max_chars: Optional[int] = None) -> str:
    """Format synthesis based on tier setting."""
    if not synthesis:
        return ""

    if format_type == "one_paragraph":
        # Extract first paragraph or limit to max_chars (default 600)
        limit = max_chars or 600
        paragraphs = synthesis.split('\n\n')
        first_para = paragraphs[0] if paragraphs else synthesis

        # Strip HTML tags for cleaner truncation
        clean_text = _strip_html_tags(first_para)

        if len(clean_text) > limit:
            # Truncate at word boundary
            truncate_point = clean_text.rfind(' ', 0, limit - 20)
            if truncate_point == -1:
                truncate_point = limit - 20
            return clean_text[:truncate_point] + "..."
        return clean_text

    elif format_type == "detailed":
        # Limit to max_chars (default 2000)
        limit = max_chars or 2000
        if len(synthesis) > limit:
            truncate_point = synthesis.rfind(' ', 0, limit - 20)
            if truncate_point == -1:
                truncate_point = limit - 20
            return synthesis[:truncate_point] + "..."
        return synthesis

    else:  # "full"
        return synthesis


def _strip_html_tags(text: str) -> str:
    """Remove HTML tags from text for clean truncation."""
    import re
    clean = re.sub(r'<[^>]+>', '', text)
    # Also normalize whitespace
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


def _format_llm_responses(
    responses: List[RawProviderResponseDict],  # CCI_SE_ILL3_03: RawProviderResponseDict replaces List[Dict[str,Any]]  # HAL-001-DEFERRED [ARCH_EXCEPTION] EX-SE-017
    truncate_limit: Optional[int] = None
) -> List[FormattedLLMResponse]:
    """Format individual LLM responses with optional truncation."""
    formatted = []

    for response in responses:
        # Handle multiple possible keys for provider name
        provider = (
            response.get('provider') or
            response.get('agent') or
            'Unknown'
        )

        # Handle multiple possible keys for response text
        text = (
            response.get('response') or
            response.get('answer') or
            response.get('content') or
            ''
        )

        if not text:
            continue

        original_length = len(text)
        truncated = False

        if truncate_limit and len(text) > truncate_limit:
            # Truncate at word boundary
            truncate_point = text.rfind(' ', 0, truncate_limit - 10)
            if truncate_point == -1:
                truncate_point = truncate_limit - 10
            text = text[:truncate_point] + "..."
            truncated = True

        formatted.append(FormattedLLMResponse(
            provider=str(provider),
            response=text,
            truncated=truncated,
            original_length=original_length if truncated else None
        ))

    return formatted


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_tier_code(tier_name: str) -> str:
    """Get tier code from tier name."""
    config = get_tier_config(tier_name.lower() if tier_name else "seeker")
    return config.get('code', 'SEK')


def should_show_llm_responses(tier_name: str) -> bool:
    """Check if tier should show individual LLM responses."""
    config = get_tier_config(tier_name.lower() if tier_name else "seeker")
    features = config.get('response_features', {})
    return features.get('show_individual_llm', False)


def get_llm_truncate_limit(tier_name: str) -> Optional[int]:
    """Get LLM response truncation limit for tier."""
    config = get_tier_config(tier_name.lower() if tier_name else "seeker")
    features = config.get('response_features', {})
    return features.get('llm_response_truncate')