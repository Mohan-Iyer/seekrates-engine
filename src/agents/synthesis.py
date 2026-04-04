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
# defines_classes: "SynthesisResult, OracleRiskResult"
# defines_functions: "synthesize_with_llm, _format_responses, _call_claude_api, _parse_synthesis_response, _extract_bullet_points, _build_consensus_panel_html, _escape_html, _get_fallback_response, oracle_risk_analysis, _oracle_risk_fallback, synthesize_with_llm_sync"
# =============================================================================
# DEPENDENCIES:
# =============================================================================
# =============================================================================
# FIELD CONTRACTS:
# =============================================================================
#   input_sources:
#     - path: "src/agents/consensus_engine.py"
#       type: "provider_responses_Dict"
#     - path: "environment variables ANTHROPIC_API_KEY"
#       type: "OS_Environment"
#   output_destinations:
#     - path: "src/agents/consensus_engine.py"
#       type: "SynthesisResult"
#     - path: "src/agents/consensus_engine.py"
#       type: "OracleRiskResult"
# =============================================================================
# CHANGE LOG:
# =============================================================================
# v3.0.1 - 2026-03-08: SD-CCI-02 — Synthesis timeout pre-flight.
# v3.0.0 - 2026-02-26: HAL-001 sprint — 2 return annotations fixed.
# v2.0.0 - 2026-02-25: Previous production release.
# === END OF SCRIPT DNA HEADER ====================================

import os
import logging
import asyncio
import aiohttp
import re
import json
from typing import Dict, List, TypedDict, Any

logger = logging.getLogger(__name__)


# =============================================================================
# TYPE DEFINITIONS (AFD: Precise Types Only)
# =============================================================================

class SynthesisResult(TypedDict):
    """Return type for synthesize_with_llm - NO type erasure."""
    consensus_reached: bool
    agreement_points: List[str]
    disagreement_points: List[str]
    synthesized_answer: str
    consensus_panel: str
    assessment_level: str
    assessment_explanation: str
    provider_count: int
    # =========================================================================
    # NEW FIELDS (v2.0.0 - Session 84/85 Option C)
    # =========================================================================
    convergence_count: int          # Number of AIs that reached same conclusion (0-5)
    convergence_percentage: int     # Convergence as percentage (0-100)
    consensus_confidence: str       # Semantic strength: HIGH, MODERATE, LOW, CONTESTED
    dissenting_provider: str        # Provider name that dissented (or empty)
    dissent_summary: str            # One-line summary of dissent (or empty)
    dissent_significance: str       # MATERIAL or MINOR (or empty)


# =============================================================================
# CONSTANTS
# =============================================================================

SYNTHESIS_MODEL: str = "claude-sonnet-4-5-20250929"
SYNTHESIS_MAX_TOKENS: int = 2000
SYNTHESIS_TIMEOUT: int = 30
CONFIDENCE_FLOOR: float = 0.55          # avg_confidence threshold for low-confidence mode
SYNTHESIS_LOW_CONFIDENCE_MAX_TOKENS: int = 600   # abbreviated path token limit
SYNTHESIS_LOW_CONFIDENCE_TIMEOUT: int = 15       # abbreviated path timeout (seconds)

SYSTEM_PROMPT: str = """You are a synthesis expert. Your job is to analyze multiple AI responses to the same question and produce a unified analysis.

Be concise, factual, and highlight both agreements and disagreements.
Do not add information not present in the original responses.
Format your response EXACTLY as specified."""

USER_PROMPT_TEMPLATE: str = """# Original Question
{query}

# AI Responses to Analyze
{formatted_responses}

# Your Task
Analyze these {provider_count} AI responses and provide:

1. AGREEMENT POINTS: List 2-4 key points where most/all AIs agree
2. DISAGREEMENT POINTS: List any significant differences (or "None" if unanimous)
3. SYNTHESIZED ANSWER: A unified answer combining the best insights. Structure as 2-4 sections using HTML. Each section: <h3>Theme Title</h3> followed by a <p>paragraph</p>. No markdown, no ** bold **, pure HTML.
4. CONSENSUS ASSESSMENT: Rate agreement as HIGH (90%+), MODERATE (60-89%), or LOW (<60%)
5. CONVERGENCE ANALYSIS: Analyze how many AIs reached the same core conclusion

Format your response EXACTLY as:

## AGREEMENT
- Point 1
- Point 2

## DISAGREEMENT
- Point 1 (or "None identified")

## SYNTHESIS
<h3>[Theme 1]</h3>
<p>[Paragraph 1]</p>

<h3>[Theme 2]</h3>
<p>[Paragraph 2]</p>

<h3>[Theme 3]</h3>
<p>[Paragraph 3]</p>

## ASSESSMENT
[HIGH/MODERATE/LOW]: [Brief explanation]

## CONVERGENCE
CORE_CONCLUSIONS:
- OPENAI: [One sentence core recommendation]
- CLAUDE: [One sentence core recommendation]
- GEMINI: [One sentence core recommendation]
- MISTRAL: [One sentence core recommendation]
- COHERE: [One sentence core recommendation]

CONVERGENCE_COUNT: [Number 1-5 of AIs with same core conclusion]
CONVERGENCE_PERCENTAGE: [0-100]
CONFIDENCE_LEVEL: [HIGH if same conclusion AND similar reasoning, MODERATE if same conclusion but different reasoning, LOW if split conclusions, CONTESTED if fundamental disagreement]
DISSENTING_PROVIDER: [Provider name that disagrees most, or "None"]
DISSENT_SUMMARY: [One sentence summary of dissent, or "None"]
DISSENT_SIGNIFICANCE: [MATERIAL if affects decision, MINOR if stylistic, or "None"]"""

USER_PROMPT_ABBREVIATED: str = """# Original Question
{query}

# AI Responses (low-confidence mode — {provider_count} providers)
{formatted_responses}

# Task
These responses show limited agreement. Provide a BRIEF synthesis only.

Format EXACTLY as:

## AGREEMENT
- [Key agreement point]

## DISAGREEMENT
- [Key disagreement or "None identified"]

## SYNTHESIS
<h3>Summary</h3>
<p>[2-3 sentence summary. Note that AI responses showed limited agreement.]</p>

## ASSESSMENT
LOW: Limited consensus - low-confidence responses

## CONVERGENCE
CORE_CONCLUSIONS:
- {provider_list}
CONVERGENCE_COUNT: [0-5]
CONVERGENCE_PERCENTAGE: [0-100]
CONFIDENCE_LEVEL: LOW
DISSENTING_PROVIDER: [Provider name or None]
DISSENT_SUMMARY: [One sentence or None]
DISSENT_SIGNIFICANCE: [MATERIAL or MINOR or None]"""


# =============================================================================
# MAIN SYNTHESIS FUNCTION
# =============================================================================

async def synthesize_with_llm(
    query: str,
    provider_responses: Dict[str, str],
    timeout_seconds: int = SYNTHESIS_TIMEOUT,
    low_confidence_mode: bool = False
) -> SynthesisResult:
    """
    Synthesize multiple LLM responses using Claude.
    
    Args:
        query: Original user question (str, required)
        provider_responses: Map of provider name to response text (Dict[str, str], required, min 2 entries)
        timeout_seconds: Max time to wait for Claude (int, default 30)
    
    Returns:
        SynthesisResult TypedDict with all fields populated
        
    Raises:
        No exceptions raised - returns fallback on any error
    """
    # Early return if insufficient responses
    if len(provider_responses) < 2:
        logger.warning("Insufficient responses for synthesis (<2)")
        return _get_fallback_response("Insufficient responses for comparison.")
    
    # Format responses for prompt
    formatted_responses: str = _format_responses(provider_responses)
    provider_count: int = len(provider_responses)
    
    # Build prompt — low_confidence_mode uses abbreviated template + reduced limits
    if low_confidence_mode:
        user_prompt: str = USER_PROMPT_ABBREVIATED.format(
            query=query,
            formatted_responses=formatted_responses,
            provider_count=provider_count,
            provider_list="\n- ".join(provider_responses.keys())
        )
        active_max_tokens: int = SYNTHESIS_LOW_CONFIDENCE_MAX_TOKENS
        active_timeout: int = SYNTHESIS_LOW_CONFIDENCE_TIMEOUT
        logger.info(f"Low-confidence mode: max_tokens={active_max_tokens}, timeout={active_timeout}s")
    else:
        user_prompt: str = USER_PROMPT_TEMPLATE.format(
            query=query,
            formatted_responses=formatted_responses,
            provider_count=provider_count
        )
        active_max_tokens: int = SYNTHESIS_MAX_TOKENS
        active_timeout: int = timeout_seconds
    
    # Get API key
    api_key: str | None = os.getenv('ANTHROPIC_API_KEY') or os.getenv('CLAUDE_API_KEY')
    if not api_key:
        logger.error("No Anthropic API key found")
        return _get_fallback_response("Synthesis service unavailable.")
    
    # Make API call
    try:
        response_text: str | None = await _call_claude_api(
            api_key=api_key,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            timeout_seconds=active_timeout,
            max_tokens=active_max_tokens
        )
        
        if not response_text:
            return _get_fallback_response("Empty response from synthesis.")
        
        # Parse response
        result: SynthesisResult = _parse_synthesis_response(response_text, provider_count)
        
        logger.info(f"✅ Synthesis complete: {result['assessment_level']} agreement")
        return result
        
    except asyncio.TimeoutError:
        logger.warning(f"Synthesis timed out after {timeout_seconds}s")
        return _get_fallback_response("Synthesis timed out.")
    
    except Exception as e:
        logger.error(f"Synthesis failed: {e}")
        return _get_fallback_response("Synthesis temporarily unavailable.")


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _format_responses(provider_responses: Dict[str, str]) -> str:
    """Format provider responses for the prompt."""
    formatted: List[str] = []
    for provider, response in provider_responses.items():
        # Truncate very long responses
        truncated: str = response[:2000] + "..." if len(response) > 2000 else response
        formatted.append(f"## {provider.upper()} says:\n{truncated}\n")
    return "\n---\n".join(formatted)


async def _call_claude_api(
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    timeout_seconds: int,
    max_tokens: int = SYNTHESIS_MAX_TOKENS
) -> str | None:
    """Make HTTP call to Claude API. Returns response text or None on error."""
    
    url: str = "https://api.anthropic.com/v1/messages"
    
    headers: Dict[str, str] = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01"
    }
    
    payload: Dict[str, str | int | List[Dict[str, str]]] = {
        "model": SYNTHESIS_MODEL,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [
            {"role": "user", "content": user_prompt}
        ]
    }
    
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, headers=headers, json=payload) as response:
            if response.status != 200:
                error_text: str = await response.text()
                logger.error(f"Claude API error {response.status}: {error_text}")
                return None
            
            data: Dict[str, List[Dict[str, str]]] = await response.json()
            
            # Extract text from response
            content: List[Dict[str, str]] = data.get("content", [])
            if content and len(content) > 0:
                return content[0].get("text", "")
            
            return None


def _parse_synthesis_response(response_text: str, provider_count: int) -> SynthesisResult:
    """Parse Claude's structured response into SynthesisResult."""
    
    # Default values
    agreement_points: List[str] = []
    disagreement_points: List[str] = []
    synthesized_answer: str = ""
    assessment_level: str = "MODERATE"
    assessment_explanation: str = ""
    
    # NEW v2.0.0 - Convergence defaults
    convergence_count: int = 0
    convergence_percentage: int = 0
    consensus_confidence: str = "LOW"
    dissenting_provider: str = ""
    dissent_summary: str = ""
    dissent_significance: str = ""
    
    # Extract AGREEMENT section
    agreement_match = re.search(
        r'## AGREEMENT\s*(.*?)(?=## DISAGREEMENT|## SYNTHESIS|$)',
        response_text,
        re.DOTALL | re.IGNORECASE
    )
    if agreement_match:
        agreement_text: str = agreement_match.group(1).strip()
        agreement_points = _extract_bullet_points(agreement_text)
    
    # Extract DISAGREEMENT section
    disagreement_match = re.search(
        r'## DISAGREEMENT\s*(.*?)(?=## SYNTHESIS|## ASSESSMENT|$)',
        response_text,
        re.DOTALL | re.IGNORECASE
    )
    if disagreement_match:
        disagreement_text: str = disagreement_match.group(1).strip()
        disagreement_points = _extract_bullet_points(disagreement_text)
        # Filter out "None" entries
        disagreement_points = [p for p in disagreement_points if "none" not in p.lower()]
    
    # Extract SYNTHESIS section
    synthesis_match = re.search(
        r'## SYNTHESIS\s*(.*?)(?=## ASSESSMENT|$)',
        response_text,
        re.DOTALL | re.IGNORECASE
    )
    if synthesis_match:
        synthesized_answer = synthesis_match.group(1).strip()
    
    # Extract ASSESSMENT section
    assessment_match = re.search(
        r'## ASSESSMENT\s*\n?\s*(HIGH|MODERATE|LOW)[:\s]*(.*)$',
        response_text,
        re.DOTALL | re.IGNORECASE
    )
    if assessment_match:
        assessment_level = assessment_match.group(1).upper()
        assessment_explanation = assessment_match.group(2).strip()[:200]
    
    # =========================================================================
    # NEW v2.0.0 - Extract CONVERGENCE section
    # =========================================================================
    
    # Extract CONVERGENCE_COUNT
    convergence_count_match = re.search(
        r'CONVERGENCE_COUNT:\s*(\d+)',
        response_text,
        re.IGNORECASE
    )
    if convergence_count_match:
        try:
            convergence_count = int(convergence_count_match.group(1))
            convergence_count = max(0, min(5, convergence_count))  # Clamp to 0-5
        except ValueError:
            convergence_count = 0
    
    # Extract CONVERGENCE_PERCENTAGE
    convergence_pct_match = re.search(
        r'CONVERGENCE_PERCENTAGE:\s*(\d+)',
        response_text,
        re.IGNORECASE
    )
    if convergence_pct_match:
        try:
            convergence_percentage = int(convergence_pct_match.group(1))
            convergence_percentage = max(0, min(100, convergence_percentage))  # Clamp to 0-100
        except ValueError:
            convergence_percentage = 0
    
    # Extract CONFIDENCE_LEVEL
    confidence_match = re.search(
        r'CONFIDENCE_LEVEL:\s*(HIGH|MODERATE|LOW|CONTESTED)',
        response_text,
        re.IGNORECASE
    )
    if confidence_match:
        consensus_confidence = confidence_match.group(1).upper()
    else:
        # Fallback: derive from assessment_level
        consensus_confidence = assessment_level if assessment_level != "UNKNOWN" else "LOW"
    
    # Extract DISSENTING_PROVIDER
    dissent_provider_match = re.search(
        r'DISSENTING_PROVIDER:\s*([^\n]+)',
        response_text,
        re.IGNORECASE
    )
    if dissent_provider_match:
        dissenting_provider = dissent_provider_match.group(1).strip()
        if dissenting_provider.lower() == "none":
            dissenting_provider = ""
    
    # Extract DISSENT_SUMMARY
    dissent_summary_match = re.search(
        r'DISSENT_SUMMARY:\s*([^\n]+)',
        response_text,
        re.IGNORECASE
    )
    if dissent_summary_match:
        dissent_summary = dissent_summary_match.group(1).strip()
        if dissent_summary.lower() == "none":
            dissent_summary = ""
    
    # Extract DISSENT_SIGNIFICANCE
    dissent_sig_match = re.search(
        r'DISSENT_SIGNIFICANCE:\s*(MATERIAL|MINOR|None)',
        response_text,
        re.IGNORECASE
    )
    if dissent_sig_match:
        dissent_significance = dissent_sig_match.group(1).upper()
        if dissent_significance == "NONE":
            dissent_significance = ""
    
    # If convergence_count is 0 but we have responses, estimate from assessment
    if convergence_count == 0 and provider_count > 0:
        if assessment_level == "HIGH":
            convergence_count = provider_count
            convergence_percentage = 100
        elif assessment_level == "MODERATE":
            convergence_count = max(3, provider_count - 1)
            convergence_percentage = int((convergence_count / provider_count) * 100)
        elif assessment_level == "LOW":
            convergence_count = max(1, provider_count // 2)
            convergence_percentage = int((convergence_count / provider_count) * 100)
    
    # Determine consensus_reached
    consensus_reached: bool = assessment_level in ["HIGH", "MODERATE"]
    
    # Build HTML consensus panel
    consensus_panel: str = _build_consensus_panel_html(
        agreement_points=agreement_points,
        disagreement_points=disagreement_points,
        synthesized_answer=synthesized_answer,
        assessment_level=assessment_level,
        provider_count=provider_count
    )
    
    return SynthesisResult(
        consensus_reached=consensus_reached,
        agreement_points=agreement_points,
        disagreement_points=disagreement_points,
        synthesized_answer=synthesized_answer,
        consensus_panel=consensus_panel,
        assessment_level=assessment_level,
        assessment_explanation=assessment_explanation,
        provider_count=provider_count,
        # NEW v2.0.0 - Convergence fields
        convergence_count=convergence_count,
        convergence_percentage=convergence_percentage,
        consensus_confidence=consensus_confidence,
        dissenting_provider=dissenting_provider,
        dissent_summary=dissent_summary,
        dissent_significance=dissent_significance
    )


def _extract_bullet_points(text: str) -> List[str]:
    """Extract bullet points from text."""
    points: List[str] = []
    for line in text.split('\n'):
        line = line.strip()
        # Match lines starting with -, *, or numbers
        if re.match(r'^[-*•]\s+', line):
            point: str = re.sub(r'^[-*•]\s+', '', line).strip()
            if point:
                points.append(point)
        elif re.match(r'^\d+[.)]\s+', line):
            point = re.sub(r'^\d+[.)]\s+', '', line).strip()
            if point:
                points.append(point)
    return points


def _build_consensus_panel_html(
    agreement_points: List[str],
    disagreement_points: List[str],
    synthesized_answer: str,
    assessment_level: str,
    provider_count: int
) -> str:
    """
    Build HTML fragment for email and frontend display.
    
    Uses inline styles for email compatibility (many email clients strip <style> tags).
    Brand Kit Colors:
    - Indigo: #0B1E3A
    - Teal: #1CB5E0
    - Charcoal: #101820
    - Silver Mist: #F2F4F7
    - White: #FFFFFF
    """
    
    # Badge styling based on assessment level (Brand Kit compliant)
    badge_styles: Dict[str, str] = {
        "HIGH": "background: #FFFFFF; color: #0B1E3A; border: 2px solid #1CB5E0;",
        "MODERATE": "background: #FFFFFF; color: #0B1E3A; border: 2px solid #1CB5E0;",
        "LOW": "background: #FFFFFF; color: #0B1E3A; border: 2px solid #999;",
        "UNKNOWN": "background: #FFFFFF; color: #0B1E3A; border: 2px solid #999;"
    }
    badge_style: str = badge_styles.get(assessment_level, badge_styles["UNKNOWN"])
    
    # Build agreement list with inline styles
    agreement_html: str
    if agreement_points:
        items: str = "".join(
            f'<li style="color: #0B1E3A; margin-bottom: 10px; line-height: 1.6;">{_escape_html(p)}</li>'
            for p in agreement_points
        )
        agreement_html = f'<ul style="margin: 0; padding-left: 20px;">{items}</ul>'
    else:
        agreement_html = '<p style="color: #666; font-style: italic; margin: 0;">No clear agreement points identified.</p>'
    
    # Build disagreement list with inline styles
    disagreement_html: str
    if disagreement_points:
        items = "".join(
            f'<li style="color: #0B1E3A; margin-bottom: 10px; line-height: 1.6;">{_escape_html(p)}</li>'
            for p in disagreement_points
        )
        disagreement_html = f'<ul style="margin: 0; padding-left: 20px;">{items}</ul>'
    else:
        disagreement_html = '<p style="color: #666; font-style: italic; margin: 0;">All providers substantially agree.</p>'
    # Build synthesis text with styling (Teal accent)
    synthesis_html: str
    if synthesized_answer:
        synthesis_html = f'''<div style="background: rgba(28, 181, 224, 0.15); padding: 18px; border-radius: 8px; border-left: 3px solid #1CB5E0; color: #0B1E3A; line-height: 1.7;">
    {synthesized_answer}
</div>'''
    else:
        synthesis_html = '<p style="color: #666; font-style: italic;">No synthesis available.</p>'
    
    # Assemble full panel with inline styles for email compatibility
    html: str = f'''<div style="margin: 20px 0;">
    <h4 style="font-family: 'Poppins', sans-serif; color: #0B1E3A; margin: 0 0 12px 0; font-size: 13px; text-transform: uppercase; letter-spacing: 1px; font-weight: 600;">✅ Points of Agreement</h4>
    {agreement_html}
</div>

<div style="margin: 20px 0;">
    <h4 style="font-family: 'Poppins', sans-serif; color: #0B1E3A; margin: 0 0 12px 0; font-size: 13px; text-transform: uppercase; letter-spacing: 1px; font-weight: 600;">⚠️ Points of Divergence</h4>
    {disagreement_html}
</div>

<div style="margin: 20px 0;">
    <h4 style="font-family: 'Poppins', sans-serif; color: #0B1E3A; margin: 0 0 12px 0; font-size: 13px; text-transform: uppercase; letter-spacing: 1px; font-weight: 600;">📝 Synthesized Answer</h4>
    {synthesis_html}
</div>

<div style="margin-top: 18px;">
    <span style="{badge_style} display: inline-block; padding: 8px 16px; border-radius: 25px; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">{assessment_level} Agreement</span>
    <span style="color: #666; font-size: 12px; margin-left: 12px;">Based on {provider_count} AI responses</span>
</div>'''
    
    return html


def _escape_html(text: str) -> str:
    """Basic HTML escaping."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;"))


def _get_fallback_response(message: str) -> SynthesisResult:
    """Return fallback response when synthesis fails."""
    return SynthesisResult(
        consensus_reached=False,
        agreement_points=[],
        disagreement_points=[],
        synthesized_answer=message,
        consensus_panel=f"<p>{_escape_html(message)}</p>",
        assessment_level="UNKNOWN",
        assessment_explanation="",
        provider_count=0,
        # NEW v2.0.0 - Convergence fields (defaults)
        convergence_count=0,
        convergence_percentage=0,
        consensus_confidence="LOW",
        dissenting_provider="",
        dissent_summary="",
        dissent_significance=""
    )


# =============================================================================
# ORACLE RISK PASS (v2.0.0 - Session 85 Option C)
# =============================================================================

class OracleRiskResult(TypedDict):
    """Return type for oracle_risk_analysis - NO type erasure."""
    assumptions: List[str]
    failure_modes: List[str]
    contrarian_argument: str
    contrarian_significance: str  # MATERIAL or MINOR
    contrarian_reasoning: str
    oracle_recommendation: str
    validation_checklist: List[str]


ORACLE_RISK_PROMPT: str = """You are an Oracle Risk Analyst. Your job is to identify assumptions, failure modes, and provide contrarian analysis.

Given:
- Original query: {query}
- Number of AIs that agreed: {convergence_percentage}%
- Synthesis conclusion: {synthesis_text}
- Dissenting AI: {dissenting_provider}
- Dissent summary: {dissent_summary}

Analyze and respond with ONLY this JSON (no markdown, no explanation):

{{
  "assumptions": ["List 3-5 key assumptions the synthesis depends on"],
  "failure_modes": ["List 3-5 scenarios where this advice could fail"],
  "contrarian_argument": "The strongest argument AGAINST the consensus",
  "contrarian_significance": "MATERIAL or MINOR",
  "contrarian_reasoning": "Why the contrarian view matters (or doesn't)",
  "oracle_recommendation": "Given all risks, should user: PROCEED | PROCEED_WITH_CAUTION | INVESTIGATE_FURTHER | PAUSE",
  "validation_checklist": ["3-5 things the user should verify before acting"]
}}
"""


async def oracle_risk_analysis(
    query: str,
    provider_responses: Dict[str, str],
    synthesis_text: str,
    convergence_percentage: int,
    dissenting_provider: str = "",
    dissent_summary: str = ""
) -> OracleRiskResult:
    """
    Oracle Risk Pass - Second Claude synthesis call.
    
    Transforms analysis into actionable trust assessment.
    Called ONLY for Oracle and Sage tiers.
    
    Args:
        query: Original user question
        provider_responses: Map of provider name to response text
        synthesis_text: The synthesized answer from first pass
        convergence_percentage: How many AIs agreed (0-100)
        dissenting_provider: Provider that disagreed (if any)
        dissent_summary: Summary of dissent (if any)
    
    Returns:
        OracleRiskResult dict with assumptions, failure_modes, etc.
    """
    
    # Get API key
    api_key: str | None = os.getenv('ANTHROPIC_API_KEY') or os.getenv('CLAUDE_API_KEY')
    if not api_key:
        logger.error("No Anthropic API key found for Oracle Risk Pass")
        return _oracle_risk_fallback()
    
    # Build prompt
    prompt = ORACLE_RISK_PROMPT.format(
        query=query,
        convergence_percentage=convergence_percentage,
        synthesis_text=synthesis_text[:1500],  # Truncate if too long
        dissenting_provider=dissenting_provider or "None",
        dissent_summary=dissent_summary or "No significant dissent"
    )
    
    try:
        response_text: str | None = await _call_claude_api(
            api_key=api_key,
            system_prompt="You are an Oracle Risk Analyst. Respond with JSON only.",
            user_prompt=prompt,
            timeout_seconds=30  # Shorter timeout for second pass
        )
        
        if not response_text:
            logger.warning("Empty response from Oracle Risk Pass")
            return _oracle_risk_fallback()
        
        # Parse JSON from response (handle potential markdown wrapping)
        json_text = response_text.strip()
        
        # Remove markdown code blocks if present
        if json_text.startswith("```"):
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', json_text, re.DOTALL)
            if json_match:
                json_text = json_match.group(1)
        
        result = json.loads(json_text)
        
        # Validate and return
        return OracleRiskResult(
            assumptions=result.get('assumptions', [])[:5],
            failure_modes=result.get('failure_modes', [])[:5],
            contrarian_argument=result.get('contrarian_argument', ''),
            contrarian_significance=result.get('contrarian_significance', 'MINOR').upper(),
            contrarian_reasoning=result.get('contrarian_reasoning', ''),
            oracle_recommendation=result.get('oracle_recommendation', 'PROCEED_WITH_CAUTION'),
            validation_checklist=result.get('validation_checklist', [])[:5]
        )
        
    except json.JSONDecodeError as e:
        logger.warning(f"Oracle Risk Pass JSON parse error: {e}")
        return _oracle_risk_fallback()
    except asyncio.TimeoutError:
        logger.warning("Oracle Risk Pass timed out")
        return _oracle_risk_fallback()
    except Exception as e:
        logger.error(f"Oracle Risk Pass failed: {e}")
        return _oracle_risk_fallback()


def _oracle_risk_fallback() -> OracleRiskResult:
    """Fallback when Oracle Risk Pass fails."""
    return OracleRiskResult(
        assumptions=['Unable to extract assumptions - review synthesis carefully'],
        failure_modes=['Unable to extract failure modes - consider edge cases'],
        contrarian_argument='Risk analysis temporarily unavailable',
        contrarian_significance='MINOR',
        contrarian_reasoning='Please review individual AI responses for dissenting views',
        oracle_recommendation='PROCEED_WITH_CAUTION',
        validation_checklist=['Review individual AI responses', 'Identify key assumptions', 'Consider alternatives']
    )


# =============================================================================
# SYNCHRONOUS WRAPPER
# =============================================================================

def synthesize_with_llm_sync(
    query: str,
    provider_responses: Dict[str, str],
    timeout_seconds: int = SYNTHESIS_TIMEOUT
) -> SynthesisResult:
    """Synchronous wrapper for synthesize_with_llm."""
    return asyncio.run(synthesize_with_llm(query, provider_responses, timeout_seconds))


# =============================================================================
# END OF MODULE
# =============================================================================