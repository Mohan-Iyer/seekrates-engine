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
# defines_classes: "ProviderResponse, ConsensusMetadata, Outlier, DivergenceReport, OracleRiskAnalysis, ConsensusResult, Config"
# defines_functions: "validate_consensus_dict, create_divergence_report, validate_confidence_level, champion_not_empty, validate_common_themes, validate_significance, validate_providers, validate_consensus"
# =============================================================================
# DEPENDENCIES:
# =============================================================================
# =============================================================================
# FIELD CONTRACTS:
# =============================================================================
#   input_sources:
#     - path: "src/agents/consensus_engine.py"
#       type: "ConsensusResult_Dict"
#     - path: "src/agents/synthesis.py"
#       type: "SynthesisResult"
#   output_destinations:
#     - path: "src/api/auth_endpoints.py"
#       type: "ConsensusResult"
#     - path: "src/telemetry/research_archive.py"
#       type: "ConsensusResult"
# =============================================================================
# CHANGE LOG:
# =============================================================================
# v4.0.0 — 2026-03-27 — CCI_SE_ILL1_TYPEB_03: RefusalIndicators defined inline, circular import eliminated.
# v3.0.0 - 2026-02-26: HAL-001 sprint — 2 violations annotated HAL-001-DEFERRED.
# v2.0.0 - 2026-02-25: Previous production release.
# === END OF SCRIPT DNA HEADER ====================================

from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any

# =============================================================================
# PROVIDER RESPONSE MODEL
# =============================================================================

class ProviderResponse(BaseModel):
    """Single LLM provider's response with quality metrics"""
    
    provider: str = Field(
        ...,
        description="Provider name: openai, claude, gemini, mistral, cohere"
    )
    
    answer: str = Field(
        ...,
        description="Full response text from LLM"
    )
    
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="LLM self-reported confidence (0.0-1.0)"
    )
    
    score: int = Field(
        ...,
        ge=0,
        le=100,
        description="Answer quality score (0-100) - NOT confidence!"
    )
    
    # v5.3.0 — Research archive fields (Session 109)
    quality_breakdown: Optional[Dict[str, Any]] = Field(  # HAL-001-DEFERRED: variable-structure accumulator (15+ mixed-type keys).
        None,                                               # Requires Union discriminator refactor. Deferred per D-114-01.
        description="Quality rubric sub-scores from score_answer_quality()"
    )
    is_refusal: bool = Field(
        False,
        description="True if response classified as refusal"
    )
    refusal_indicators: Optional[Dict[str, Any]] = Field(  # HAL-001-DEFERRED: importing RefusalIndicators from consensus_engine
        None,                                                # creates circular dependency. Requires nested BaseModel refactor.
        description="Refusal detection details (matched pattern, type)"
    )
    response_time_ms: Optional[int] = Field(
        None,
        description="Provider response latency in milliseconds"
    )
    token_count: Optional[int] = Field(
        None,
        description="Total tokens used by provider"
    )
    llm_version: Optional[str] = Field(
        None,
        description="Model string used (e.g., 'gpt-4o')"
    )
    status: str = Field(
        "success",
        description="'success' or 'error'"
    )
    
    class Config:
        extra = "forbid"  # Reject unknown fields
        validate_assignment = True  # Validate on field updates

# =============================================================================
# CONSENSUS METADATA MODEL
# =============================================================================

class ConsensusMetadata(BaseModel):
    """Consensus analysis with champion selection and divergence detection"""
    
    consensus_panel: str = ""
    
    champion: str = Field(
        ...,
        description="Champion provider name (highest quality score)"
    )
    
    champion_score: int = Field(
        ...,
        ge=0,
        le=100,
        description="Champion's quality score (MUST exist, cannot be undefined)"
    )
    
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Weighted confidence across all providers"
    )
    
    consensus_text: Optional[str] = Field(
        None,
        description="Synthesized consensus summary (optional)"
    )
    
    agreement_percentage: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Agreement metric based on score variance"
    )
    
    reached: bool = Field(
        ...,
        description="True if consensus threshold met (>60% agreement)"
    )
    
    # =========================================================================
    # DIVERGENCE HIGHLIGHT FIELDS (v1.2.0 - Session 71)
    # =========================================================================
    divergence_highlight: str = Field(
        default="",
        description="Human-readable description of dissenting view for marketing hooks"
    )
    
    dissenting_provider: str = Field(
        default="",
        description="Name of provider with minority view (uppercase, e.g., 'CLAUDE')"
    )
    
    dissent_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Score delta from mean as decimal (0.0 to 1.0)"
    )
    
    # =========================================================================
    # NEW METRICS (v2.0.0 - Session 84/85 Option C)
    # =========================================================================
    
    convergence_count: int = Field(
        default=0,
        ge=0,
        le=5,
        description="Number of AIs that reached same conclusion (0-5)"
    )
    
    convergence_percentage: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Convergence as percentage (convergence_count/5 * 100)"
    )
    
    consensus_confidence: str = Field(
        default="LOW",
        description="Semantic strength: HIGH, MODERATE, LOW, CONTESTED"
    )
    
    @validator('consensus_confidence')
    def validate_confidence_level(cls, v):
        allowed = ['HIGH', 'MODERATE', 'LOW', 'CONTESTED']
        if v not in allowed:
            return 'LOW'
        return v
    
    @validator('champion')
    def champion_not_empty(cls, v):
        if not v or v.strip() == "":
            raise ValueError("champion cannot be empty string")
        return v
    
    class Config:
        extra = "forbid"
        validate_assignment = True

# =============================================================================
# DIVERGENCE REPORT MODELS (v1.1.0 - SEEK-1A)
# =============================================================================

class Outlier(BaseModel):
    """Identifies a provider whose response diverged from consensus"""
    
    provider: str = Field(
        ...,
        description="Provider name that diverged"
    )
    
    reason: str = Field(
        ...,
        description="Why this response was flagged as outlier"
    )
    
    missing_themes: List[str] = Field(
        default_factory=list,
        description="Common themes this provider did not address"
    )
    
    unique_focus: Optional[str] = Field(
        None,
        description="What this provider uniquely focused on"
    )
    
    class Config:
        extra = "forbid"


class DivergenceReport(BaseModel):
    """
    Analyzes agreement and disagreement across LLM responses.
    
    This is the core differentiator for Seekrates AI - surfacing
    not just WHAT the AIs agree on, but WHERE they diverge and WHY.
    """
    
    common_themes: List[str] = Field(
        default_factory=list,
        description="Themes that appear in majority of responses"
    )
    
    outliers: List[Outlier] = Field(
        default_factory=list,
        description="Providers whose responses diverged from consensus"
    )
    
    personality_quotes: Dict[str, str] = Field(
        default_factory=dict,
        description="Notable quotes per provider showing their 'voice'"
    )
    
    article_hook: str = Field(
        "",
        description="One-liner summarizing the divergence for marketing"
    )
    
    theme_coverage: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Which providers covered which themes"
    )
    
    @validator('common_themes')
    def validate_common_themes(cls, v):
        if v is None:
            return []
        return v
    
    class Config:
        extra = "forbid"


# =============================================================================
# ORACLE RISK ANALYSIS MODEL (v2.0.0 - Session 84/85 Option C)
# =============================================================================

class OracleRiskAnalysis(BaseModel):
    """
    Risk analysis output from Oracle tier second synthesis pass.
    Transforms analysis into actionable trust assessment.
    
    This is the core differentiator for Oracle tier - providing not just
    consensus but actionable trust assessment with:
    - Assumptions the recommendation depends on
    - Failure modes to watch for
    - Contrarian analysis with significance rating
    - Conditional recommendation
    - Validation checklist for user action
    """
    
    assumptions: List[str] = Field(
        default_factory=list,
        description="What this recommendation depends on being true (2-4 items)"
    )
    
    failure_modes: List[str] = Field(
        default_factory=list,
        description="Conditions under which this advice would be wrong (2-4 items)"
    )
    
    contrarian_argument: str = Field(
        default="",
        description="The strongest dissenting argument"
    )
    
    contrarian_significance: str = Field(
        default="MINOR",
        description="MATERIAL (affects decision) or MINOR (stylistic)"
    )
    
    contrarian_reasoning: str = Field(
        default="",
        description="Why the contrarian view might matter"
    )
    
    oracle_recommendation: str = Field(
        default="",
        description="Conditional recommendation: 'Proceed if X. Pause if Y.'"
    )
    
    validation_checklist: List[str] = Field(
        default_factory=list,
        description="Specific steps user can take to verify before acting (3-5 items)"
    )
    
    @validator('contrarian_significance')
    def validate_significance(cls, v):
        if v not in ['MATERIAL', 'MINOR']:
            return 'MINOR'
        return v
    
    class Config:
        extra = "forbid"


# =============================================================================
# CONSENSUS RESULT MODEL (TOP-LEVEL)
# =============================================================================

class ConsensusResult(BaseModel):
    """Complete consensus result with all provider responses and metadata"""
    
    consensus: ConsensusMetadata = Field(
        ...,
        description="Consensus metadata with champion (REQUIRED, not Optional)"
    )
    
    providers: List[ProviderResponse] = Field(
        ...,
        min_items=1,
        description="Individual provider responses (at least 1 required)"
    )
    
    correlation_id: str = Field(
        ...,
        description="Unique identifier for this consensus query"
    )
    
    divergence: Optional[DivergenceReport] = Field(
        None,
        description="Analysis of agreement/disagreement (v1.1.0)"
    )
    
    # =========================================================================
    # NEW FIELDS (v2.0.0 - Session 84/85 Option C)
    # =========================================================================
    
    risk_analysis: Optional[OracleRiskAnalysis] = Field(
        None,
        description="Oracle tier risk analysis (None for Seeker/Acolyte)"
    )
    
    tier: str = Field(
        default="seeker",
        description="Tier that processed this query: seeker, acolyte, oracle, sage"
    )
    
    @validator('providers')
    def validate_providers(cls, v):
        if not v:
            raise ValueError("providers list cannot be empty")
        return v
    
    @validator('consensus')
    def validate_consensus(cls, v):
        if v is None:
            raise ValueError("consensus cannot be None")
        return v
    
    class Config:
        extra = "forbid"
        validate_assignment = True

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def validate_consensus_dict(data: dict) -> ConsensusResult:
    """
    Validate dict against ConsensusResult schema
    
    Args:
        data: Dict from consensus engine
        
    Returns:
        Validated ConsensusResult model
        
    Raises:
        ValidationError: If structure invalid
        
    Example:
        >>> result_dict = consensus_engine.generate_expert_panel_response_v4(...)
        >>> validated = validate_consensus_dict(result_dict)
        >>> max_score = validated.consensus.champion_score  # Guaranteed to exist
    """
    return ConsensusResult(**data)


def create_divergence_report(
    common_themes: List[str],
    outliers: List[dict],
    personality_quotes: Dict[str, str],
    article_hook: str,
    theme_coverage: Dict[str, List[str]] = None
) -> DivergenceReport:
    """
    Factory function to create a validated DivergenceReport.
    
    Args:
        common_themes: List of shared concepts across responses
        outliers: List of outlier dicts with provider, reason, etc.
        personality_quotes: Dict of provider -> notable quote
        article_hook: One-liner for marketing
        theme_coverage: Optional dict of theme -> providers
        
    Returns:
        Validated DivergenceReport model
    """
    outlier_models = [Outlier(**o) for o in outliers] if outliers else []
    
    return DivergenceReport(
        common_themes=common_themes or [],
        outliers=outlier_models,
        personality_quotes=personality_quotes or {},
        article_hook=article_hook or "",
        theme_coverage=theme_coverage or {}
    )