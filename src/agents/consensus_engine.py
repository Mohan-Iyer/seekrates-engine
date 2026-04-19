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
# defines_functions: "extract_common_themes, detect_outliers, extract_personality_quotes, generate_article_hook, build_divergence_report, calculate_consensus, _strip_punctuation, score_answer_quality, determine_best_agent, extract_divergence_highlight, generate_expert_panel_response_v4, generate_expert_panel_response_v3"
# =============================================================================
# DEPENDENCIES:
# =============================================================================
# =============================================================================
# FIELD CONTRACTS:
# =============================================================================
#   input_sources:
#     - path: "src/agents/llm_dispatcher.py"
#       type: "ProviderCallResult"
#     - path: "src/agents/synthesis.py"
#       type: "SynthesisResult"
#     - path: "src/core/consensus_cag.py"
#       type: "ConsensusSummary"
#   output_destinations:
#     - path: "src/api/auth_endpoints.py"
#       type: "ConsensusResult"
#     - path: "src/api/router.py"
#       type: "ConsensusResult"
# =============================================================================
# CHANGE LOG:
# =============================================================================
# v6.0.1 - 2026-03-08: SD-CCI-02 — Pre-synthesis confidence floor check.
# v6.0.0 - 2026-02-26: HAL-001 sprint — 4 Dict[str, Any]/bare Dict violations fixed.
# v5.3.0 - 2026-02-25: Research archive fields added (Session 109).
# v6.0.2 - 2026-03-25: CCI_SE_ILL3_04 — generate_expert_panel_response_v3 return
#   typed as ConsensusResult (mirrors v4 return type).
# === END OF SCRIPT DNA HEADER ====================================

"""
Consensus Engine - Multi-Agent LLM Orchestration

DETAILED SCHEMAS (Reference - Not in DNA Header):

INPUT: ConsensusRequest
{
  "query": str (required),
  "agents": List[str] (optional, default: ['openai', 'claude', 'gemini', 'mistral', 'cohere']),
  "user_id": str (optional),
  "options": Dict[str, Any] (optional)
}

OUTPUT: ConsensusResponse
{
  "status": str ('success'|'partial'|'error'),
  "query": str,
  "results": List[ProviderResult],
  "consensus": ConsensusAnalysis,
  "metadata": ExecutionMetadata
}

ProviderResult:
{
  "provider": str,
  "answer": str,
  "score": int (0-100, quality rating),
  "confidence": float (0.0-1.0, LLM certainty),
  "weighted_confidence": float,
  "is_refusal": bool,
  "answer_quality": Dict[str, Any],
  "status": str,
  "model": str,
  "response_time": str,
  "usage": Dict[str, int],
  "telemetry": Dict[str, Any]
}

ConsensusAnalysis:
{
  "reached": bool,
  "agreement_percentage": float (0-100),
  "threshold": float (default 60.0),
  "champion": str,
  "champion_score": int (0-100),
  "method": str,
  "timestamp": str
}

ExecutionMetadata:
{
  "success_count": int,
  "failure_count": int,
  "elapsed_time": str,
  "total_tokens": int,
  "gps_coordinate": str,
  "version": str
}

HALLUCINATION PREVENTION NOTES:
- score = answer QUALITY (0-100), NOT confidence
- confidence = LLM CERTAINTY (0.0-1.0), independent of quality
- champion = highest quality score with refusals filtered
- agreement_percentage = semantic similarity, NOT success rate
- Always use .get() with defaults for optional fields
"""

# =============================================================================
# IMPORTS
# =============================================================================

import re
import logging
import sys
import uuid
from typing import Tuple, Dict, Any, List, Union, Optional, TypedDict
from .synthesis import synthesize_with_llm, oracle_risk_analysis
from datetime import datetime
from pathlib import Path
import asyncio
import time


# =============================================================================
# HAL-001 SPRINT TYPES (v6.0.0)
# =============================================================================

class ProviderScoreInput(TypedDict, total=False):
    """Input to extract_divergence_highlight — provider result item."""
    score: Union[int, float]


class ConsensusInput(TypedDict, total=False):
    """Input to calculate_consensus — provider result item."""
    status: str
    response: str
    confidence: float


class ConsensusCalcResult(TypedDict):
    """Return of calculate_consensus."""
    consensus_reached: bool
    agreement_percentage: float
    threshold: float
    decision_id: str
    timestamp: str


class AgentInput(TypedDict, total=False):
    """Input list item for determine_best_agent."""
    agent: str
    confidence: float
    response: str
    latency_ms: int


class BestAgentResult(TypedDict, total=False):
    """Return of determine_best_agent."""
    agent: Optional[str]
    reason: str
    score: float
    champion: Optional[str]
    scores: Dict[str, float]


class RefusalIndicators(TypedDict):
    """Nested in QualityAnalysisResult — refusal detection detail."""
    detected: bool
    patterns_found: List[str]
    confidence: float


class QualityBreakdown(TypedDict, total=False):
    """Nested in QualityAnalysisResult — per-dimension scoring breakdown."""
    refusal_detected: bool
    refusal_penalty: int
    final_score: int
    scoring_method: str
    addresses_question: bool
    keyword_overlap: float
    query_keywords: int
    matched_keywords: int
    addressing_score: int
    completeness_type: str
    completeness: float
    completeness_score: int
    structure_score: int
    factual_score: int
    factual_indicators: dict
    has_paragraphs: bool
    has_formatting: bool
    word_count: int
    list_items_found: int
    list_items_requested: int
    error: str


class QualityAnalysisResult(TypedDict):
    """Return of score_answer_quality."""
    score: int
    is_refusal: bool
    quality_breakdown: QualityBreakdown
    refusal_indicators: RefusalIndicators
    provider: str


# =============================================================================
DIVERGENCE_THRESHOLD = 15  # Percentage points deviation to trigger highlight
MIN_PROVIDERS_FOR_DIVERGENCE = 3  # Minimum providers needed to detect outlier

# =============================================================================
# DIVERGENCE REPORT FUNCTIONS (SEEK-1A)
# GPS: fr_02_uc_08_ec_01_tc_002
# Version: 4.2.0
# Purpose: Extract common themes, detect outliers, generate article hooks
# =============================================================================

def extract_common_themes(responses: list, max_themes: int = 5) -> list:
    """
    Extract common themes/concepts that appear across multiple LLM responses.
    Uses simple keyword frequency analysis (no ML dependencies).
    GPS: fr_02_uc_08_ec_01_tc_002
    """
    from collections import Counter
    
    STOPWORDS = {
        'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
        'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
        'should', 'may', 'might', 'must', 'shall', 'can', 'need', 'dare',
        'ought', 'used', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by',
        'from', 'as', 'into', 'through', 'during', 'before', 'after', 'above',
        'below', 'between', 'under', 'again', 'further', 'then', 'once', 'here',
        'there', 'when', 'where', 'why', 'how', 'all', 'each', 'few', 'more',
        'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own',
        'same', 'so', 'than', 'too', 'very', 'just', 'and', 'but', 'if', 'or',
        'because', 'until', 'while', 'although', 'though', 'after', 'before',
        'this', 'that', 'these', 'those', 'what', 'which', 'who', 'whom',
        'i', 'you', 'he', 'she', 'it', 'we', 'they', 'me', 'him', 'her', 'us',
        'them', 'my', 'your', 'his', 'its', 'our', 'their', 'mine', 'yours',
        'hers', 'ours', 'theirs', 'also', 'however', 'therefore', 'thus',
        'hence', 'accordingly', 'consequently', 'moreover', 'furthermore',
        'additionally', 'besides', 'anyway', 'nonetheless', 'nevertheless',
        'instead', 'otherwise', 'regardless', 'response', 'answer', 'question',
        'provide', 'provides', 'provided', 'consider', 'considering', 'based',
        'using', 'use', 'used', 'important', 'note', 'please', 'following',
        'example', 'examples', 'include', 'includes', 'including', 'well',
        'like', 'make', 'makes', 'made', 'get', 'gets', 'got', 'way', 'ways',
        'thing', 'things', 'something', 'anything', 'everything', 'nothing'
    }
    
    all_words = []
    for resp in responses:
        text = resp.get('response', resp.get('answer', ''))
        if not text:
            continue
        text = text.lower()
        text = re.sub(r'[^\w\s]', ' ', text)
        words = text.split()
        filtered = [
            w for w in words 
            if w not in STOPWORDS 
            and len(w) > 3 
            and not w.isdigit()
        ]
        all_words.extend(filtered)
    
    word_counts = Counter(all_words)
    common = [
        word for word, count in word_counts.most_common(max_themes * 2)
        if count > 1
    ]
    
    if len(common) < max_themes:
        for word, count in word_counts.most_common(max_themes):
            if word not in common:
                common.append(word)
            if len(common) >= max_themes:
                break
    
    return common[:max_themes]


def detect_outliers(responses: list, common_themes: list, threshold: float = 0.5) -> list:
    """
    Identify responses that significantly diverge from the consensus themes.
    GPS: fr_02_uc_08_ec_01_tc_002
    """
    if not common_themes:
        return []
    
    outliers = []
    
    for resp in responses:
        provider = resp.get('provider', 'unknown')
        text = resp.get('response', resp.get('answer', '')).lower()
        
        present_themes = [t for t in common_themes if t.lower() in text]
        missing_themes = [t for t in common_themes if t.lower() not in text]
        
        coverage_ratio = len(present_themes) / len(common_themes) if common_themes else 1.0
        
        if coverage_ratio < (1.0 - threshold):
            unique_focus = None
            words = set(re.findall(r'\b\w{4,}\b', text.lower()))
            other_words = set()
            for other_resp in responses:
                if other_resp.get('provider') != provider:
                    other_text = other_resp.get('response', other_resp.get('answer', '')).lower()
                    other_words.update(re.findall(r'\b\w{4,}\b', other_text))
            
            unique_words = words - other_words
            if unique_words:
                unique_focus = f"Uniquely discussed: {', '.join(list(unique_words)[:3])}"
            
            if missing_themes:
                reason = f"Did not address: {', '.join(missing_themes[:3])}"
            else:
                reason = "Response structure diverged from others"
            
            outliers.append({
                'provider': provider,
                'reason': reason,
                'missing_themes': missing_themes,
                'unique_focus': unique_focus
            })
    
    return outliers


def extract_personality_quotes(responses: list) -> dict:
    """
    Extract one distinctive quote from each provider.
    GPS: fr_02_uc_08_ec_01_tc_002
    """
    SKIP_PATTERNS = [
        r'^i\'?ll\s', r'^i\s+can\s', r'^i\s+would\s', r'^let\s+me\s',
        r'^sure[,!]?\s', r'^of\s+course', r'^certainly', r'^absolutely',
        r'^here\'?s?\s', r'^great\s+question', r'^good\s+question',
        r'^here\s+are', r'^there\s+are', r'^the\s+following',
    ]
    
    quotes = {}
    
    for resp in responses:
        provider = resp.get('provider', 'unknown')
        text = resp.get('response', resp.get('answer', ''))
        
        if not text:
            quotes[provider] = "(No response)"
            continue
        
        sentences = re.split(r'[.!?]+', text)
        selected_quote = None
        
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 20 or len(sentence) > 200:
                continue
            
            is_generic = False
            for pattern in SKIP_PATTERNS:
                if re.match(pattern, sentence.lower()):
                    is_generic = True
                    break
            
            if is_generic:
                continue
            
            selected_quote = sentence
            break
        
        if not selected_quote and sentences:
            first = sentences[0].strip()
            if len(first) > 200:
                selected_quote = first[:197] + "..."
            elif len(first) > 10:
                selected_quote = first
            else:
                selected_quote = text[:100] + "..."
        
        quotes[provider] = selected_quote or "(No substantive content)"
    
    return quotes


def generate_article_hook(common_themes: list, outliers: list, agreement_pct: float, champion: str) -> str:
    """
    Generate a ready-to-use content angle for articles/social posts.
    GPS: fr_02_uc_08_ec_01_tc_002
    """
    if not common_themes:
        return "AI models provided diverse perspectives on this question."
    
    if agreement_pct >= 80:
        themes_str = ", ".join(common_themes[:3])
        return f"Strong consensus: All AI models agreed that {themes_str} are the key factors. {champion.title()} provided the most comprehensive analysis."
    
    if outliers:
        outlier_names = [o['provider'].title() for o in outliers[:2]]
        outlier_str = " and ".join(outlier_names)
        themes_str = ", ".join(common_themes[:2])
        
        if len(outliers) == 1:
            unique_focus = outliers[0].get('unique_focus', '')
            if unique_focus:
                return f"While most AI models focused on {themes_str}, {outlier_str} offered a different perspective. {unique_focus}"
            else:
                return f"Interesting divergence: {outlier_str} took a unique approach while others focused on {themes_str}."
        else:
            return f"Split opinions: While the consensus centered on {themes_str}, {outlier_str} highlighted different considerations."
    
    themes_str = ", ".join(common_themes[:3])
    return f"AI models identified {themes_str} as key themes, with {champion.title()} providing the top-rated analysis."


def build_divergence_report(responses: list, agreement_pct: float, champion: str) -> dict:
    """
    Build complete divergence report from responses.
    Main entry point for divergence analysis.
    GPS: fr_02_uc_08_ec_01_tc_002
    """
    common_themes = extract_common_themes(responses)
    outliers = detect_outliers(responses, common_themes)
    personality_quotes = extract_personality_quotes(responses)
    article_hook = generate_article_hook(common_themes, outliers, agreement_pct, champion)
    
    theme_coverage = {}
    for theme in common_themes:
        covering_providers = []
        for resp in responses:
            provider = resp.get('provider', 'unknown')
            text = resp.get('response', resp.get('answer', '')).lower()
            if theme.lower() in text:
                covering_providers.append(provider)
        theme_coverage[theme] = covering_providers
    
    return {
        'common_themes': common_themes,
        'outliers': outliers,
        'personality_quotes': personality_quotes,
        'article_hook': article_hook,
        'theme_coverage': theme_coverage
    }

# =============================================================================
# END OF DIVERGENCE FUNCTIONS
# =============================================================================

# =============================================================================
# GPS FOUNDATION RUNTIME GUARD
# =============================================================================
# Runtime guard - disabled for testing
# assert os.getenv("PYTEST_CURRENT_TEST") is None, "Unit test harness leak detected in production"

# =============================================================================
# DYNAMIC PATH RESOLUTION (GPS FOUNDATION COMPLIANT)
# =============================================================================
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

# =============================================================================
# INTERNAL MODULE IMPORTS
# =============================================================================
from src.telemetry.telemetry_logger import log_metric, log_event
from src.agents.llm_dispatcher import call_llm_agent
from src.core.consensus_cag import build_consensus_summary, render_consensus_panel
from .consensus_contract import ConsensusResult, ProviderResponse, ConsensusMetadata, OracleRiskAnalysis

# =============================================================================
# LOGGING SETUP
# =============================================================================
logger = logging.getLogger(__name__)

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def calculate_consensus(provider_results: Dict[str, ConsensusInput]) -> ConsensusCalcResult:
    """
    Calculate consensus metrics from provider results.
    
    IMPORTANT: This calculates SUCCESS RATE, not agreement percentage!
    For actual agreement, see the score variance calculation in
    generate_expert_panel_response_v4().
    
    Args:
        provider_results: Dict of provider responses
    
    Returns:
        Dict with consensus metrics (success rate, threshold, metadata)
    
    Note: This function is DEPRECATED in favor of direct calculation in v4.
          Kept for backward compatibility only.
    """
    import uuid
    from datetime import datetime
    
    # Count successful responses
    success_count = sum(1 for r in provider_results.values() 
                       if r.get('status') == 'success')
    total_count = len(provider_results)
    
    return {
        'consensus_reached': success_count >= 3,
        'agreement_percentage': (success_count / total_count * 100) if total_count else 0,  # This is SUCCESS RATE, not agreement!
        'threshold': 60.0,
        'decision_id': str(uuid.uuid4()),
        'timestamp': datetime.now().isoformat()
    }


# =============================================================================
# ANSWER QUALITY SCORING (v4.1 - FIXES SCORING BUG)
# =============================================================================
# GPS: fr_02_uc_08_ec_01_tc_001 (quality scoring enhancement)
# Purpose: Score answer quality instead of using weighted confidence
# Status: PRODUCTION (v4.1+)
# Critical: This function is the FIX for the scoring bug in v4.0!
# =============================================================================

# BUG-107-01: Strip punctuation from word for clean keyword matching
_PUNCTUATION_RE = re.compile(r'[^\w]')

def _strip_punctuation(word: str) -> str:
    """Strip all non-word characters from a string.
    
    BUG-107-01: query_words and answer_words retained punctuation,
    causing 'personhood?' != 'personhood' match failures.
    
    Uses re (already imported at line 337).
    
    Args:
        word: Raw word possibly containing punctuation
    Returns:
        Word with all non-alphanumeric/underscore characters removed
        
    GPS: fr_02_uc_08_ec_01_tc_002
    Phase: v5.2.0 (BUG-107-01 Punctuation Fix)
    """
    return _PUNCTUATION_RE.sub('', word)


def score_answer_quality(
    query: str,
    answer: str,
    provider: str,
    base_confidence: float
) -> QualityAnalysisResult:
    """
    Score answer quality based on multiple dimensions (NOT LLM confidence!).
    
    This function implements the fix for the v4.0 scoring bug where we
    incorrectly used weighted_confidence * 100 as the score. Now we
    properly evaluate answer quality using a multi-dimensional rubric.
    
    v5.1.0 (BUG-105-01): Renamed param confidenceâ†’base_confidence,
    added soft refusal patterns, fixed return key names for contract compat,
    deleted duplicate shadow function that was overriding this one.
    
    v5.2.0 (BUG-107-01): Added _strip_punctuation() helper. Both query_words
    and answer_words now strip punctuation before matching, fixing silent score
    deflation on punctuated queries. Stopword filter and length filter now
    operate on cleaned words.
    
    Scoring Rubric (100 pts total):
    ================================
    - 40 pts: Addresses the question (keyword overlap analysis)
    - 30 pts: Completeness (has requested elements like "3 reasons")
    - 20 pts: Structure and clarity (paragraphs, formatting)
    - 10 pts: Factual indicators (citations, examples, specifics)
    
    Penalties:
    ==========
    - -50 pts: Refusal to answer (e.g., "I cannot provide...")
    - Refusals get max 20 pts regardless of confidence
    
    Args:
        query: User's question
        answer: Provider's response text
        provider: Provider name (for logging)
        base_confidence: LLM's self-reported confidence (0.0-1.0)
    
    Returns:
        {
            'score': int (0-100),           # Answer quality score
            'is_refusal': bool,             # True if refused to answer
            'quality_breakdown': dict,      # Detailed scoring breakdown
            'refusal_indicators': dict,     # Refusal detection details
            'provider': str                 # Provider name
        }
    
    Example:
        >>> score_answer_quality(
        ...     query="State three reasons why X",
        ...     answer="1. First\\n2. Second\\n3. Third",
        ...     provider="openai",
        ...     base_confidence=0.8
        ... )
        {'score': 90, 'is_refusal': False, 'quality_breakdown': {...}, ...}
    
    GPS: fr_02_uc_08_ec_01_tc_001
    Phase: v5.1.0 (BUG-105-01 Refusal Gate Fix)
    """
    
    score = 0
    breakdown = {}
    
    # =========================================================================
    # STEP 1: DETECT REFUSALS (CRITICAL!)
    # =========================================================================
    # This prevents confident refusals from scoring higher than answers,
    # which was the core bug in v4.0 that caused Claude (refusal) to beat
    # Mistral (comprehensive answer).
    
    refusal_patterns = [
        # Hard refusals
        "i don't feel comfortable",
        "i cannot",
        "i apologize, but",
        "i'm not able to",
        "i can't provide",
        "i shouldn't",
        "i'm sorry, but",
        "i must decline",
        "i prefer not to",
        "that would be inappropriate",
        # Soft/speculative refusals (BUG-105-01 v5.1.0)
        "it would be speculative",
        "rather than making predictions",
        "rather than making specific",
        "i'd want to be thoughtful",
        "it's important to note that predicting",
        "difficult to predict with certainty",
        "impossible to predict",
        "no one can predict",
        "beyond the scope of prediction",
        "i'd hesitate to",
        "it's not possible to definitively",
        "i wouldn't want to speculate"
    ]
    
    answer_lower = answer.lower()
    is_refusal = any(pattern in answer_lower for pattern in refusal_patterns)
    
    if is_refusal:
        # Heavy penalty for refusals
        breakdown['refusal_detected'] = True
        breakdown['refusal_penalty'] = -50
        
        # Give minimal points for polite refusal (5-20 pts max)
        # Even a confident refusal gets low score
        score = max(5, int(base_confidence * 20))
        
        breakdown['final_score'] = score
        breakdown['scoring_method'] = 'refusal_penalty'
        
        # Collect which patterns matched
        patterns_found = [p for p in refusal_patterns if p in answer_lower]
        
        logger.debug(f"ðŸš« {provider} REFUSED to answer - Score: {score}/100")
        
        return {
            'score': score,
            'is_refusal': True,
            'quality_breakdown': breakdown,
            'refusal_indicators': {
                'detected': True,
                'patterns_found': patterns_found,
                'confidence': 0.95 if len(patterns_found) >= 2 else 0.65
            },
            'provider': provider
        }
    
    # =========================================================================
    # STEP 2: CHECK IF QUESTION WAS ADDRESSED (40 pts)
    # =========================================================================
    # Analyze keyword overlap between query and answer.
    # If answer doesn't contain keywords from query, it's probably off-topic.
    
    # Remove stopwords
    stopwords = {'a', 'an', 'the', 'is', 'are', 'was', 'were', 'in', 'on', 'at', 
                 'to', 'for', 'of', 'and', 'or', 'but', 'what', 'why', 'how', 
                 'when', 'where', 'who', 'which', 'that', 'this', 'these', 'those'}
    
    # Extract meaningful keywords from query
    # BUG-107-01: Strip punctuation BEFORE lowercase, stopword check, and length filter
    query_words = set(
        cleaned for w in query.split()
        if (cleaned := _strip_punctuation(w).lower())  # walrus: strip then lower
        and cleaned not in stopwords                     # stopword check on CLEAN word
        and len(cleaned) > 2                             # length check on CLEAN word
    )
    # BUG-107-01: Strip punctuation from answer words too
    answer_words = set(
        cleaned for w in answer_lower.split()
        if (cleaned := _strip_punctuation(w))  # already lowercase (answer_lower)
    )
    
    # Calculate keyword overlap percentage
    if query_words:
        keyword_overlap = len(query_words & answer_words) / len(query_words)
    else:
        keyword_overlap = 0.5  # Default if no meaningful query words
    
    # Threshold: 30% overlap means question was addressed
    addresses_question = keyword_overlap > 0.3
    
    breakdown['addresses_question'] = addresses_question
    breakdown['keyword_overlap'] = round(keyword_overlap, 2)
    breakdown['query_keywords'] = len(query_words)
    breakdown['matched_keywords'] = len(query_words & answer_words)
    
    if addresses_question:
        addressing_score = 40
    else:
        addressing_score = int(keyword_overlap * 40)  # Partial credit
    
    score += addressing_score
    breakdown['addressing_score'] = addressing_score
    
    # =========================================================================
    # STEP 3: CHECK COMPLETENESS (30 pts)
    # =========================================================================
    # If query asks for "three reasons", check if answer provides them.
    # This catches incomplete answers that might sound confident but
    # don't actually fulfill the request.
    
    # Detect if query requests a list
    list_indicators = ['list', 'reasons', 'ways', 'steps', 'points', 'factors', 
                      'examples', 'methods', 'strategies', 'approaches']
    
    requests_list = any(word in query.lower() for word in list_indicators)
    
    if requests_list:
        # Count numbered items (1., 2., 3., etc.)
        numbered_pattern = r'(?:^|\n)\s*\d+[\.)]\s'
        numbered_count = len(re.findall(numbered_pattern, answer))
        
        # Count bulleted items (-, *, Ã¢â‚¬Â¢, etc.)
        bulleted_pattern = r'(?:^|\n)\s*[-*Ã¢â‚¬Â¢]\s'
        bulleted_count = len(re.findall(bulleted_pattern, answer))
        
        # Take the higher count
        list_count = max(numbered_count, bulleted_count)
        
        # Extract requested number from query (e.g., "three reasons" Ã¢â€ â€™ 3)
        number_match = re.search(r'(\d+)\s+(?:reasons|ways|steps|points|examples|factors)', 
                                query.lower())
        requested_count = int(number_match.group(1)) if number_match else 3  # Default to 3
        
        # Calculate completeness
        if requested_count > 0:
            completeness = min(list_count / requested_count, 1.0)
        else:
            completeness = 1.0 if list_count > 0 else 0.5
        
        breakdown['completeness_type'] = 'list_based'
        breakdown['list_items_found'] = list_count
        breakdown['list_items_requested'] = requested_count
        breakdown['completeness'] = round(completeness, 2)
        
        completeness_score = int(completeness * 30)
        
    else:
        # For non-list queries, use answer length as proxy
        # 150 words = complete answer
        word_count = len(answer.split())
        completeness = min(word_count / 150, 1.0)
        
        breakdown['completeness_type'] = 'length_based'
        breakdown['word_count'] = word_count
        breakdown['completeness'] = round(completeness, 2)
        
        completeness_score = int(completeness * 30)
    
    score += completeness_score
    breakdown['completeness_score'] = completeness_score
    
    # =========================================================================
    # STEP 4: CHECK STRUCTURE AND CLARITY (20 pts)
    # =========================================================================
    # Well-formatted responses score higher.
    # Paragraphs and formatting indicate thoughtful structure.
    
    structure_score = 0
    
    # Check for paragraphs (good structure)
    has_paragraphs = '\n\n' in answer or answer.count('\n') > 2
    if has_paragraphs:
        structure_score += 10
        breakdown['has_paragraphs'] = True
    
    # Check for formatting (lists, bullets, emphasis)
    has_formatting = any(char in answer for char in ['*', '-', 'Ã¢â‚¬Â¢', '1.', '2.', '3.', '**', '__'])
    if has_formatting:
        structure_score += 10
        breakdown['has_formatting'] = True
    
    score += structure_score
    breakdown['structure_score'] = structure_score
    
    # =========================================================================
    # STEP 5: CHECK FOR FACTUAL INDICATORS (10 pts)
    # =========================================================================
    # Presence of citations, examples, and specifics indicates quality.
    # Dates, names, and numbers suggest research-backed answers.
    
    factual_score = 0
    factual_indicators = {}
    
    # Dates (e.g., 2023, 1999)
    has_dates = bool(re.search(r'\b(19|20)\d{2}\b', answer))
    if has_dates:
        factual_score += 3
        factual_indicators['dates'] = True
    
    # Proper names (e.g., "John Smith", "Mata v. Avianca")
    has_names = bool(re.search(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b', answer))
    if has_names:
        factual_score += 4
        factual_indicators['names'] = True
    
    # Numbers/statistics (e.g., "50%", "$1000", "10 million")
    has_numbers = bool(re.search(r'\b\d+%|\$\d+|\d+\s+(?:percent|million|billion|thousand)', answer))
    if has_numbers:
        factual_score += 3
        factual_indicators['numbers'] = True
    
    score += factual_score
    breakdown['factual_score'] = factual_score
    breakdown['factual_indicators'] = factual_indicators
    
    # =========================================================================
    # FINAL SCORE CALCULATION
    # =========================================================================
    
    # Cap at 100 (shouldn't exceed but just in case)
    score = min(score, 100)
    
    # Floor at 0
    score = max(score, 0)
    
    breakdown['final_score'] = score
    breakdown['scoring_method'] = 'quality_rubric_v1'
    
    # Log for debugging
    logger.debug(f"Ã°Å¸â€œÅ  {provider} Quality Score: {score}/100")
    logger.debug(f"   - Addressing: {addressing_score}/40")
    logger.debug(f"   - Completeness: {completeness_score}/30")
    logger.debug(f"   - Structure: {structure_score}/20")
    logger.debug(f"   - Factual: {factual_score}/10")
    
    return {
        'score': score,
        'is_refusal': False,
        'quality_breakdown': breakdown,
        'refusal_indicators': {
            'detected': False,
            'patterns_found': [],
            'confidence': 0.0
        },
        'provider': provider
    }


# =============================================================================
# LEGACY FUNCTIONS (Kept for backward compatibility)
# =============================================================================
# These functions are from v3.0 and are NOT used in v4.1, but kept in case
# of rollback or for reference.

def determine_best_agent(successful_responses: List[AgentInput]) -> BestAgentResult:
    """
    LEGACY FUNCTION - NOT USED IN V4.1!
    
    Determine the best agent based on weighted scoring.
    
    This function was used in v3.0 but has been superseded by the inline
    champion selection in generate_expert_panel_response_v4() which uses
    quality scores instead of this confidence-based approach.
    
    Kept for backward compatibility and potential rollback scenarios.
    
    Original Scoring weights (DEPRECATED):
    - 40% confidence (0-1 scaled to 0-100)
    - 30% response quality (word count capped at 300) Ã¢â€ Â BUG! Word count Ã¢â€°  quality
    - 30% latency (lower is better)
    """
    
    if not successful_responses:
        return {'agent': None, 'reason': 'no responses', 'score': 0, 'champion': None}
    
    if len(successful_responses) == 1:
        agent = successful_responses[0]['agent']
        confidence = successful_responses[0].get('confidence', 0.5)
        response_text = successful_responses[0].get('response', '')
        word_count = len(response_text.split()) if response_text else 0
        latency_ms = successful_responses[0].get('latency_ms', 2000)
        
        # Old scoring formula (kept for reference)
        confidence_score = confidence * 100 * 0.4
        quality_score = min(word_count / 3, 100) * 0.3  # Ã¢â€ Â This is the bug! Word count Ã¢â€°  quality
        latency_score = max(0, (1 - latency_ms/4000) * 100) * 0.3
        
        total_score = confidence_score + quality_score + latency_score
        
        if total_score >= 50:
            return {
                'agent': agent, 
                'reason': 'sole successful respondent',
                'score': round(total_score, 1),
                'champion': agent,
                'scores': {agent: round(total_score, 1)}
            }
        else:
            return {
                'agent': None,
                'reason': 'below threshold',
                'score': round(total_score, 1),
                'champion': None,
                'scores': {agent: round(total_score, 1)}
            }
    
    # Multiple agents - calculate scores
    best_agent = None
    best_score = 0
    all_scores = {}
    
    for response in successful_responses:
        agent = response['agent']
        
        # Weighted scoring calculation (OLD METHOD - DEPRECATED)
        confidence = response.get('confidence', 0.5)
        confidence_score = confidence * 100 * 0.4  # 40% weight
        
        response_text = response.get('response', '')
        word_count = len(response_text.split()) if response_text else 0
        quality_score = min(word_count / 3, 100) * 0.3  # 30% weight Ã¢â€ Â BUG!
        
        latency_ms = response.get('latency_ms', 2000)
        latency_score = max(0, (1 - latency_ms/4000) * 100) * 0.3  # 30% weight
        
        total = confidence_score + quality_score + latency_score
        all_scores[agent] = round(total, 1)
        
        if total > best_score:
            best_score = total
            best_agent = agent
    
    if best_score >= 50:
        return {
            'agent': best_agent,
            'reason': f'Highest score: {best_score:.1f}',
            'score': round(best_score, 1),
            'champion': best_agent,
            'scores': all_scores
        }
    else:
        return {
            'agent': None,
            'reason': 'all below threshold',
            'score': round(best_score, 1),
            'champion': None,
            'scores': all_scores
        }
def extract_divergence_highlight(
    provider_results: Dict[str, ProviderScoreInput],
    consensus_score: float
) -> Tuple[str, str, float]:
    """
    Extract dissenting view if significant divergence exists.
    
    Analyzes provider scores to identify outliers that deviate significantly
    from the mean. Used for marketing hooks in the "100 Days of Foresight" campaign.
    
    Args:
        provider_results: Dict mapping provider names to their results.
                         Each result should have 'score' key (0-100).
        consensus_score: Overall agreement percentage (0-100).
    
    Returns:
        Tuple of:
            - divergence_highlight: Human-readable description or empty string
            - dissenting_provider: Provider name (uppercase) or empty string
            - dissent_confidence: Score delta as decimal (0.0-1.0) or 0.0
    
    Example:
        >>> results = {'openai': {'score': 80}, 'claude': {'score': 45}, 'gemini': {'score': 78}}
        >>> highlight, provider, confidence = extract_divergence_highlight(results, 72.0)
        >>> print(highlight)
        "CLAUDE shows significant divergence from consensus"
        >>> print(provider)
        "CLAUDE"
        >>> print(confidence)
        0.35
    
    GPS: fr_02_uc_08_ec_01_tc_001
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Guard: Not enough providers for meaningful divergence detection
    if not provider_results or len(provider_results) < MIN_PROVIDERS_FOR_DIVERGENCE:
        logger.debug(f"[DIVERGENCE] Skipping - only {len(provider_results) if provider_results else 0} providers (need {MIN_PROVIDERS_FOR_DIVERGENCE})")
        return ("", "", 0.0)
    
    # Extract scores from provider results
    scores: Dict[str, float] = {}
    for provider_name, result in provider_results.items():
        if isinstance(result, dict):
            score = result.get('score', 0)
            if isinstance(score, (int, float)) and score > 0:
                scores[provider_name.upper()] = float(score)
    
    # Guard: Not enough valid scores
    if len(scores) < MIN_PROVIDERS_FOR_DIVERGENCE:
        logger.debug(f"[DIVERGENCE] Skipping - only {len(scores)} valid scores")
        return ("", "", 0.0)
    
    # Calculate mean score
    score_values = list(scores.values())
    mean_score = sum(score_values) / len(score_values)
    
    # Find provider with largest deviation from mean
    max_deviation = 0.0
    dissenting_provider = ""
    dissenting_score = 0.0
    
    for provider_name, score in scores.items():
        deviation = abs(score - mean_score)
        if deviation > max_deviation:
            max_deviation = deviation
            dissenting_provider = provider_name
            dissenting_score = score
    
    # Check if deviation exceeds threshold
    if max_deviation < DIVERGENCE_THRESHOLD:
        logger.debug(f"[DIVERGENCE] No significant divergence - max deviation {max_deviation:.1f} < threshold {DIVERGENCE_THRESHOLD}")
        return ("", "", 0.0)
    
    # Calculate dissent confidence as normalized delta (0.0 to 1.0)
    # Max possible deviation is ~50 points (0 vs 100 with mean at 50)
    dissent_confidence = min(1.0, max_deviation / 100.0)
    
    # Build divergence highlight message
    direction = "below" if dissenting_score < mean_score else "above"
    divergence_highlight = f"{dissenting_provider} shows significant divergence ({max_deviation:.0f} points {direction} consensus)"
    
    logger.info(f"[DIVERGENCE] Detected: {dissenting_provider} at {dissenting_score:.0f} vs mean {mean_score:.0f} (delta: {max_deviation:.0f})")
    
    return (divergence_highlight, dissenting_provider, dissent_confidence)


# =============================================================================
# MAIN CONSENSUS ENGINE (v4.1 - PRODUCTION)
# =============================================================================

async def generate_expert_panel_response_v4(
    query: str, 
    user_id: str = None, 
    agents: List[str] = None,
    providers: List[str] = None,
    tier: str = "acolyte"  # NEW v5.0.0 - Tier-aware processing (Option C)
) -> ConsensusResult:
    """
    Generate multi-agent consensus response (async version).
    
    Args:
        query (str): User's question
        user_id (str): User identifier for telemetry
        agents (List[str]): DEPRECATED - use providers instead
        providers (List[str]): List of LLM providers to query
        tier (str): User tier for tier-aware processing (seeker, acolyte, oracle, sage)
    
    Returns:
        ConsensusResult: Consensus response with results from all providers
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[DEBUG-ENTRY] generate_expert_panel_response_v4 called with query: {query[:50]}, tier: {tier}")
    # Handle backward compatibility - ADD THIS BLOCK
    if providers is None and agents is not None:
        providers = agents  # Use agents if providers not specified
    elif providers is None:
        providers = ['openai', 'claude', 'gemini', 'mistral', 'cohere']  # Default removed deepseek 2025_12_30
    
    # Rest of the v4 function continues here...
    # (All your existing v4 code stays the same, just uses 'providers' variable)
    """
    Generate consensus from multiple AI providers with quality-based scoring.
    
    This is the MAIN FUNCTION that orchestrates parallel consensus generation.
    It's the core business logic that users pay for.
    
    Key Features (v4.1):
    ====================
    - Ã¢Å“â€¦ Async parallel execution (9s avg vs 40s sequential)
    - Ã¢Å“â€¦ Quality-based scoring (NOT confidence-based) Ã¢â€ Â FIX for v4.0 bug
    - Ã¢Å“â€¦ Refusal detection and penalty Ã¢â€ Â FIX for v4.0 bug
    - Ã¢Å“â€¦ Task-specific weighted voting (e.g., Claude 1.5x for creative)
    - Ã¢Å“â€¦ Graceful degradation (3/5 agents sufficient)
    - Ã¢Å“â€¦ Comprehensive error handling and retry logic
    
    Execution Flow:
    ==============
    1. Query classification Ã¢â€ â€™ task_type (e.g., "code", "creative", "reasoning")
    2. Get task-specific provider weights (e.g., {openai: 1.2, claude: 1.0})
    3. Create concurrent tasks for all providers (asyncio.gather)
    4. Execute with 30s timeout and 3 retry attempts
    5. Standardize responses across different provider APIs
    6. Calculate QUALITY scores (NOT confidence * 100!) Ã¢â€ Â KEY FIX
    7. Detect consensus based on score variance (NOT success rate!) Ã¢â€ Â KEY FIX
    8. Select champion (highest quality, refusals filtered) Ã¢â€ Â KEY FIX
    9. Return structured output (ConsensusResponse schema)
    
    Args:
        query: User's question to be answered
        user_id: For telemetry tracking (default: "default")
        agents: Optional provider override (default: all 5 providers)
    
    Returns:
        ConsensusResponse dict with structure defined in schema_contract
    
    Example:
        >>> result = await generate_expert_panel_response_v4(
        ...     query="State three reasons why X",
        ...     user_id="user_123"
        ... )
        >>> print(result['consensus']['champion'])
        'mistral'  # The provider with best quality answer
        >>> print(result['results'][0]['score'])
        92  # Quality score (NOT confidence!)
    
    GPS: fr_02_uc_08_ec_01_tc_001
    Version: v4.1 (Quality Scoring Fix)
    Status: PRODUCTION
    """
    
    start_time = time.time()
    
    # =========================================================================
    # STEP 1: SETUP AND VALIDATION
    # =========================================================================
    
    # Default providers (all 5)
    if agents is None:
        providers = ['openai', 'claude', 'gemini', 'mistral', 'cohere']
    else:
        providers = agents
    
    logger.info(f"Ã°Å¸Å¡â‚¬ Starting consensus generation for query: {query[:50]}...")
    logger.info(f"Ã°Å¸â€œâ€¹ Providers: {providers}")
    
    # Generate decision ID for tracking
    decision_id = str(uuid.uuid4())
    
    # =========================================================================
    # STEP 2: TASK CLASSIFICATION & WEIGHTED VOTING
    # =========================================================================
    # Classify query to determine which providers are "experts" for this task.
    
    # Call all providers concurrently
    provider_results = {}
    structured_results = []
    success_count = 0
    failure_count = 0
    total_tokens = 0
    # Note: This uses asyncio.gather() which is why we need async function
    try:
        # Create tasks for all providers
        tasks = []
        for provider in providers:
            # Don't execute here - asyncio.gather will execute all in parallel
            task = asyncio.create_task(
                asyncio.to_thread(call_llm_agent, provider, query)
            )
            tasks.append(task)
            
        # Execute all tasks in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        logger.info(f"Ã¢Å“â€¦ Parallel execution complete")
        
    except Exception as e:
        logger.error(f"Ã¢ÂÅ’ Parallel execution failed: {e}")
        # Return error response
        return {
            'status': 'error',
            'query': query,
            'results': [],
            'consensus': {
                'reached': False,
                'champion': 'Unknown',
                'agreement_percentage': 0.0
            },
            'metadata': {
                'success_count': 0,
                'failure_count': len(providers),
                'elapsed_time': f"{time.time() - start_time:.1f}s",
                'error': str(e)
            }
        }
    
    # =========================================================================
    # STEP 4: PROCESS RESULTS & CALCULATE QUALITY SCORES
    # =========================================================================
    # This is where we FIX the v4.0 bug!
    # OLD (v4.0): score = weighted_confidence * 100
    # NEW (v4.1): score = score_answer_quality(query, answer, ...)
    
    for i, (provider, result) in enumerate(zip(providers, results)):
        
        logger.info(f"Ã°Å¸â€œÂ¦ [{i+1}/{len(providers)}] Processing {provider}...")
        
        if isinstance(result, Exception):
            # Exception during execution
            logger.error(f"Ã¢ÂÅ’ {provider} failed with exception: {result}")
            
            provider_results[provider] = {
                'status': 'error',
                'response': '',
                'confidence': 0.0,
                'latency_ms': 0
            }
            failure_count += 1
            
        elif isinstance(result, dict):
            # Successful or failed result
            success = result.get('status') == 'success'
            answer = result.get('answer', '') if success else ''
            
            # Get base confidence from LLM
            base_confidence = result.get('confidence', 0.5 if success else 0.0)
            
            # Equal weights (weighted_voting removed Session 53)
            weight = 1.0
            weighted_confidence = base_confidence * weight if success else 0.0
            
            # =====================================================================
            # Ã¢Â­Â KEY FIX: Calculate QUALITY score instead of using confidence!
            # =====================================================================
            
            if success:
                # NEW (v4.1): Calculate quality score based on answer content
                quality_analysis = score_answer_quality(
                    query=query,
                    answer=answer,
                    provider=provider,
                    base_confidence=base_confidence  # Ã¢Å“â€¦ CORRECT parameter name
                )
                quality_score = quality_analysis['score']
                is_refusal = quality_analysis['is_refusal']
                quality_breakdown = quality_analysis['quality_breakdown']  # Ã¢Å“â€¦ CORRECT KEY
                
                logger.info(f"   Ã°Å¸â€œÅ  {provider}: quality={quality_score}/100, "
                          f"confidence={base_confidence:.2f}, "
                          f"refusal={is_refusal}")
                
            else:
                # Failed response - no quality to assess
                quality_score = 0
                is_refusal = False
                quality_breakdown = {'error': 'Provider failed to respond'}
            
            # Store results for this provider
            provider_results[provider] = {
                'status': result.get('status', 'error'),
                'response': answer,
                'confidence': weighted_confidence,
                'base_confidence': base_confidence,
                'weight': weight,
                'latency_ms': result.get('telemetry', {}).get('latency_ms', 0)
            }
            
            # Build structured result for response
            # v5.1.0: Use quality_score from single call above â€” duplicate removed (BUG-105-01)
            old_score = int(weighted_confidence * 100) if success else 0

            # Build structured result with quality scoring (v5.1.0)
            structured_result = {
                'provider': provider,
                'status': 'success' if success else 'error',
                'answer': answer,
                'error': result.get('error') if not success else None,
                'response_time': f"{result.get('telemetry', {}).get('latency_ms', 0)/1000:.1f}s",
                'usage': result.get('usage', {}) if success else None,
                'telemetry': result.get('telemetry', {}),
                'weight': weight,
                'base_confidence': base_confidence,
                'weighted_confidence': weighted_confidence,
            
                # v5.1.0: Single quality score from first call
                'score': quality_score,
            
                # Retained for backward compat / debugging
                'score_v1': old_score,
                'score_v2': quality_score,
                'quality_breakdown': quality_breakdown,
            
                'confidence': weighted_confidence if success else 0.0,
            
                # v5.1.0: Refusal flag for champion filter
                'is_refusal': is_refusal
            }
        
            if success:
                success_count += 1
                usage = result.get('usage', {})
                if isinstance(usage, dict):
                    total_tokens += usage.get('total_tokens', 0)
            else:
                failure_count += 1
            
            structured_results.append(structured_result)
                
        else:
            # Unexpected result type
            logger.error(f"Ã¢ÂÅ’ {provider} returned unexpected type: {type(result)}")
            provider_results[provider] = {
                'status': 'error',
                'response': '',
                'confidence': 0.0,
                'latency_ms': 0
            }
            failure_count += 1    
    
    # =========================================================================
    # STEP 5: CONSENSUS CALCULATION
    # =========================================================================
    # Calculate agreement based on score variance (NOT success rate!).
    # This is another KEY FIX from v4.0.
    
    if success_count >= 2:
        # Get all successful results
        # Phase 2: Check both old and new status locations
        success_results = [r for r in structured_results 
                        if r.get('status') == 'success' or 
                            r.get('telemetry', {}).get('status') == 'success']

        logger.info(f"Ã¢Å“â€¦ Found {len(success_results)} successful responses out of {len(structured_results)}")
        
        logger.info(f"Ã¢Å“â€¦ {success_count} successful responses, calculating consensus...")
        
        # =====================================================================
        # Ã¢Â­Â KEY FIX: Find champion based on QUALITY, not confidence!
        # =====================================================================
        
        # v5.1.0: Filter refusals before champion selection (BUG-105-01 fix)
        valid_answers = [r for r in success_results 
                         if not r.get('is_refusal', False) and r.get('score', 0) >= 30]
        
        if valid_answers:
            # Champion = highest quality score (refusals filtered)
            champion_result = max(valid_answers, key=lambda x: x.get('score', 0) + x.get('confidence', 0) * 10)
            champion_provider = champion_result.get('provider', 'Unknown')
            champion_score = champion_result.get('score', 0)
            
            logger.info(f"Ã°Å¸Ââ€  Champion: {champion_provider} (score: {champion_score}/100)")
            logger.info(f"   Valid answers: {len(valid_answers)}/{len(success_results)}")
            
        else:
            # All responses either refused or low quality
            logger.warning(f"Ã¢Å¡ Ã¯Â¸Â No valid answers (all refused or low quality)")
            
            if success_results:
                # Pick best of bad options
                champion_result = max(success_results, key=lambda x: x.get('score', 0) + x.get('confidence', 0) * 10)
                champion_provider = f"{champion_result.get('provider', 'Unknown')} (low quality)"
                champion_score = champion_result.get('score', 0)
            else:
                champion_provider = 'None'
                champion_score = 0
        
        # =====================================================================
        # OPTION C v5.0.0: Use synthesis convergence metrics instead of score variance
        # =====================================================================
        # The old score-variance approach measured quality score similarity, not semantic agreement.
        # Example bug: 5 AIs give different answers but similar scores -> "98% agreement" (wrong!)
        # 
        # NEW: synthesis.py extracts convergence_count and convergence_percentage from 
        # actual semantic analysis of the core conclusions.
        # =====================================================================
        
        # Default values - will be overwritten by synthesis results
        agreement_pct = 0.0
        convergence_count = 0
        convergence_percentage = 0
        consensus_confidence = "LOW"
        dissenting_provider_from_synthesis = ""
        dissent_summary = ""
        dissent_significance = ""
        
        # Consensus reached threshold remains at 60%
        consensus_reached = False
        
    else:
        # Less than 2 successful responses - no consensus possible
        consensus_reached = False
        agreement_pct = 0.0
        champion_provider = 'Unknown'
        champion_score = 0
        success_results = []  
        convergence_count = 0
        convergence_percentage = 0
        consensus_confidence = "LOW"
        dissenting_provider_from_synthesis = ""
        dissent_summary = ""
        dissent_significance = ""
        
        logger.warning(f"Ã¢Å¡ Ã¯Â¸Â Insufficient responses for consensus ({success_count}/5)")
    
    # Build consensus dictionary
    consensus_dict = {
        'reached': consensus_reached,
        'agreement_percentage': agreement_pct,  # Ã¢â€ Â Score variance (NOT success rate!)
        'threshold': 60.0,
        'champion': champion_provider,  # Ã¢â€ Â Best QUALITY (NOT highest confidence!)
        'champion_score': champion_score,  # Ã¢â€ Â NEW: Include champion score
        'method': 'score_variance_analysis',
        'timestamp': datetime.now().isoformat()
    }
    # =========================================================================
    # STEP 5.5: LLM-BASED SYNTHESIS (Gordian Knot Solution)
    # =========================================================================
    # Pass all provider responses to Claude for true semantic comparison
    
    consensus_panel_html = ""
    consensus_summary_text = ""
    
    if success_count >= 2:
        # Build provider response dict for synthesis
        provider_responses = {
            r['provider']: r['answer'] 
            for r in success_results 
            if r.get('answer') and not r.get('is_refusal')
        }
        
        if len(provider_responses) >= 2:
            try:
                # Call LLM synthesis
                synthesis_result = await synthesize_with_llm(
                    query=query,
                    provider_responses=provider_responses
                )
                
                consensus_summary_text = synthesis_result.get('synthesized_answer', '')
                consensus_panel_html = synthesis_result.get('consensus_panel', '')
                
                # =====================================================================
                # OPTION C v5.0.0: Extract convergence metrics from synthesis
                # =====================================================================
                convergence_count = synthesis_result.get('convergence_count', 0)
                convergence_percentage = synthesis_result.get('convergence_percentage', 0)
                consensus_confidence = synthesis_result.get('consensus_confidence', 'LOW')
                dissenting_provider_from_synthesis = synthesis_result.get('dissenting_provider', '')
                dissent_summary = synthesis_result.get('dissent_summary', '')
                dissent_significance = synthesis_result.get('dissent_significance', '')
                
                # Use convergence_percentage for agreement_pct (replaces score-variance)
                agreement_pct = float(convergence_percentage)
                
                # Consensus reached if convergence >= 60%
                consensus_reached = convergence_percentage >= 60
                
                logger.info(f"ðŸ“Š Convergence: {convergence_count}/5 ({convergence_percentage}%) - {consensus_confidence}")
                if dissenting_provider_from_synthesis:
                    logger.info(f"ðŸ” Dissent: {dissenting_provider_from_synthesis} ({dissent_significance})")
                
                # Log synthesis result
                logger.info(f"âœ… Synthesis complete: {synthesis_result.get('assessment_level', 'UNKNOWN')} agreement")
                
            except Exception as e:
                logger.warning(f"âš ï¸ Synthesis failed, using fallback: {e}")
                consensus_summary_text = f"Based on {success_count} AI models, see individual responses above."
                consensus_panel_html = "<p>Synthesis temporarily unavailable.</p>"
        else:
            consensus_summary_text = "Insufficient valid responses for synthesis."
            consensus_panel_html = "<p>Not enough AI responses for comparison.</p>"
    else:
        consensus_summary_text = "Insufficient responses for synthesis."
        consensus_panel_html = "<p>Not enough AI responses for comparison.</p>"

    # Print to terminal
    print("\n" + "=" * 80)
    print("ðŸ““ CONSENSUS SUMMARY")
    print("=" * 80)
    print(consensus_summary_text[:500] + "..." if len(consensus_summary_text) > 500 else consensus_summary_text)
    print("=" * 80 + "\n")
    
    # NOTE: synthesis already called above (lines 1447-1453)
    # consensus_panel_html and consensus_summary_text contain the results

    # Build consensus dictionary with convergence metrics (Option C v5.0.0)
    consensus_dict = {
        'reached': consensus_reached,
        'agreement_percentage': agreement_pct,
        'threshold': 60.0,
        'champion': champion_provider,
        'champion_score': champion_score,
        'consensus_text': consensus_summary_text,
        'consensus_panel': consensus_panel_html,
        # NEW v5.0.0 - Convergence metrics (replacing score_variance_analysis)
        'method': 'semantic_convergence',
        'convergence_count': convergence_count,
        'convergence_percentage': convergence_percentage,
        'consensus_confidence': consensus_confidence,
        'dissenting_provider': dissenting_provider_from_synthesis,
        'dissent_summary': dissent_summary,
        'dissent_significance': dissent_significance,
        'timestamp': datetime.now().isoformat()
    }

    # =========================================================================
    # STEP 5.6: ORACLE RISK PASS (Oracle/Sage tiers only) - v5.0.0
    # =========================================================================
    
    risk_analysis_result = None
    
    # Only run Oracle Risk Pass for oracle and sage tiers
    if tier in ('oracle', 'sage') and success_count >= 2:
        try:
            logger.info("ðŸ”® Running Oracle Risk Pass...")
            
            risk_analysis_result = await oracle_risk_analysis(
                query=query,
                provider_responses={r['provider']: r['answer'] for r in success_results if r.get('answer')},
                synthesis_text=consensus_summary_text,
                convergence_percentage=convergence_percentage,
                dissenting_provider=dissenting_provider_from_synthesis,
                dissent_summary=dissent_summary
            )
            
            logger.info(f"âœ… Oracle Risk Pass complete: {len(risk_analysis_result.get('assumptions', []))} assumptions, {len(risk_analysis_result.get('validation_checklist', []))} checklist items")
            logger.info(f"ðŸŽ¯ Oracle recommendation: {risk_analysis_result.get('oracle_recommendation', 'N/A')}")
            
        except Exception as e:
            logger.error(f"âš ï¸ Oracle Risk Pass failed: {e}")
            risk_analysis_result = None

    # =========================================================================
    # STEP 6: BUILD FINAL RESPONSE
    # =========================================================================
    
    elapsed_time = time.time() - start_time
    
    # Determine overall statusc
    if success_count >= 3:
        status = 'success'
    elif success_count > 0:
        status = 'partial'
    else:
        status = 'error'
    
    logger.info(f"Ã¢Å“â€¦ Consensus complete in {elapsed_time:.1f}s")
    logger.info(f"Ã°Å¸â€œÅ  Status: {status}, Success: {success_count}, Failed: {failure_count}")
    logger.info(f"Ã°Å¸Ââ€  Champion: {champion_provider} ({champion_score} pts)")
    logger.info(f"ðŸ¤ Convergence: {convergence_count}/{success_count} ({agreement_pct:.1f}%) - {consensus_confidence}")
    print("[DEBUG-1] After agreement log", flush=True)
    
    # Build final response
    response = {
        'status': status,
        'query': query,
        'results': structured_results,
        'providers': structured_results,
        'consensus': consensus_dict,
        'metadata': {
            'success_count': success_count,
            'failure_count': failure_count,
            'elapsed_time': f"{elapsed_time:.1f}s",
            'total_tokens': total_tokens,
            'gps_coordinate': 'fr_02_uc_08_ec_01_tc_001',
            'version': 'v4.1_quality_scoring'
        }
    }
    print("[DEBUG-2] After response dict built", flush=True)
    logger.info(f"[DEBUG] About to build divergence. success_count={success_count}")
    # =========================================================================
    # STEP 6.5: BUILD DIVERGENCE REPORT (v4.2.0 - SEEK-1A)
    # =========================================================================
    try:
        if success_count >= 2:
            divergence_report = build_divergence_report(
                responses=success_results,
                agreement_pct=agreement_pct,
                champion=champion_provider
            )
            response['divergence'] = divergence_report
            logger.info(f"ðŸ“Š Divergence: {len(divergence_report['common_themes'])} themes, {len(divergence_report['outliers'])} outliers")
        else:
            response['divergence'] = {
                'common_themes': [],
                'outliers': [],
                'personality_quotes': {},
                'article_hook': 'Insufficient responses for divergence analysis.',
                'theme_coverage': {}
            }
    except Exception as e:
        logger.warning(f"âš ï¸ Divergence report failed: {e}")
        response['divergence'] = {
            'common_themes': [],
            'outliers': [],
            'personality_quotes': {},
            'article_hook': 'Divergence analysis unavailable.',
            'theme_coverage': {}
        }

    
    # Transform to Pydantic models
    provider_models = [
        ProviderResponse(
            provider=p['provider'],
            answer=p['answer'],
            confidence=p['confidence'],
            score=p['score'],
            # v5.3.0 — Research archive fields (Session 109)
            quality_breakdown=p.get('quality_breakdown'),
            is_refusal=p.get('is_refusal', False),
            refusal_indicators=p.get('refusal_indicators'),
            response_time_ms=int(p.get('telemetry', {}).get('latency_ms', 0)),
            token_count=p.get('usage', {}).get('total_tokens', 0) if isinstance(p.get('usage'), dict) else 0,
            llm_version=p.get('telemetry', {}).get('model', ''),
            status=p.get('status', 'error')
        )
        for p in structured_results
    ]
    
    # Extract divergence highlight for marketing hooks
    # Convert list to dict for extract_divergence_highlight
    provider_results_dict = {r.get('provider', ''): r for r in structured_results}
    divergence_highlight, dissenting_provider, dissent_confidence = extract_divergence_highlight(
        provider_results=provider_results_dict,
        consensus_score=consensus_dict.get('agreement_percentage', 0)
    )
    
    consensus_model = ConsensusMetadata(
        champion=consensus_dict['champion'],
        champion_score=consensus_dict['champion_score'],
        confidence=consensus_dict.get('confidence', 0.5),
        agreement_percentage=consensus_dict['agreement_percentage'],
        reached=consensus_dict['reached'],
        consensus_text=consensus_dict.get('consensus_text'),
        consensus_panel=consensus_dict.get('consensus_panel', ''),
        divergence_highlight=divergence_highlight,
        # Prefer synthesis dissenting_provider if available, else use extract_divergence_highlight
        dissenting_provider=consensus_dict.get('dissenting_provider') or dissenting_provider,
        dissent_confidence=dissent_confidence,
        # NEW v5.0.0 - Convergence metrics (Option C)
        convergence_count=consensus_dict.get('convergence_count', 0),
        convergence_percentage=consensus_dict.get('convergence_percentage', 0),
        consensus_confidence=consensus_dict.get('consensus_confidence', 'LOW')
    )
    
    # =========================================================================
    # Build OracleRiskAnalysis model if we have results (v5.0.0)
    # =========================================================================
    risk_analysis_model = None
    if risk_analysis_result:
        try:
            risk_analysis_model = OracleRiskAnalysis(
                assumptions=risk_analysis_result.get('assumptions', []),
                failure_modes=risk_analysis_result.get('failure_modes', []),
                contrarian_argument=risk_analysis_result.get('contrarian_argument', ''),
                contrarian_significance=risk_analysis_result.get('contrarian_significance', 'MINOR'),
                contrarian_reasoning=risk_analysis_result.get('contrarian_reasoning', ''),
                oracle_recommendation=risk_analysis_result.get('oracle_recommendation', 'PROCEED_WITH_CAUTION'),
                validation_checklist=risk_analysis_result.get('validation_checklist', [])
            )
            logger.info(f"âœ… OracleRiskAnalysis model built successfully")
        except Exception as e:
            logger.error(f"âš ï¸ Failed to build OracleRiskAnalysis model: {e}")
            risk_analysis_model = None
    
    return ConsensusResult(
        consensus=consensus_model,
        providers=provider_models,
        correlation_id=response['metadata'].get('correlation_id', str(uuid.uuid4())),
        divergence=response.get('divergence'),
        # v5.0.0 - Tier-aware processing (Option C)
        tier=tier,
        risk_analysis=risk_analysis_model  # Populated for Oracle/Sage tiers
    )


# =============================================================================
# SYNCHRONOUS WRAPPER (For backward compatibility)
# =============================================================================
# HAL-001-DEFERRED [TYPE-C] — Backward compat wrapper. Return typed in v4 caller chain.
def generate_expert_panel_response_v3(query: str, user_id: str = "default", agents: List[str] = None) -> ConsensusResult:  # CCI_SE_ILL3_04: ConsensusResult replaces Dict[str,Any]
    """
    Synchronous wrapper for generate_expert_panel_response_v4().
    
    DEPRECATED: This is kept for backward compatibility only.
    New code should use the async version directly.
    
    Args:
        query: User's question
        user_id: For telemetry tracking
        agents: Optional provider override
    
    Returns:
        ConsensusResponse dict (same as v4)
    
    Note: Creates new event loop - not recommended for production use.
          Use async version in production.
    """
    
    logger.warning("Ã¢Å¡ Ã¯Â¸Â Using deprecated sync wrapper - consider using async version")
    
    # Create new event loop for sync context
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        result = loop.run_until_complete(
            generate_expert_panel_response_v4(query, user_id, agents)
        )
        return result
    finally:
        loop.close()


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = [
    'generate_expert_panel_response_v4',  # Main async function
    'generate_expert_panel_response_v3',  # Sync wrapper (deprecated)
    'score_answer_quality',                # Quality scoring function
    'calculate_consensus',                 # Utility function
    'determine_best_agent'                 # Legacy function
]

# =============================================================================
# END OF FILE
# =============================================================================