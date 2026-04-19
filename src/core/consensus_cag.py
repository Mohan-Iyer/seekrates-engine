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
# defines_classes: "ProviderResult, ProviderSummary, ConsensusCalc, ConsensusInfo, ArbitrationInfo, TelemetryInfo, VerdictInfo, ConsensusSummary"
# defines_functions: "validate_provider_result, validate_consensus_calc, build_consensus_summary, render_consensus_panel"
# =============================================================================
# DEPENDENCIES:
# =============================================================================
# =============================================================================
# FIELD CONTRACTS:
# =============================================================================
#   input_sources:
#     - path: "src/core/engine.py"
#       type: "ConsensusCalcResult_Dict"
#     - path: "src/agents/consensus_engine.py"
#       type: "provider_results_Dict"
#   output_destinations:
#     - path: "src/core/engine.py"
#       type: "ConsensusSummary"
#     - path: "src/agents/consensus_engine.py"
#       type: "ConsensusSummary"
# === END OF SCRIPT DNA HEADER ====================================

from typing import TypedDict, List, Dict, Optional
from dataclasses import dataclass

# Type definitions - no Any allowed
class ProviderResult(TypedDict):
    status: str
    confidence: float
    latency_ms: int
    response: str

class ProviderSummary(TypedDict):
    name: str
    verdict: str
    confidence: float
    latency_ms: int
    rationale: str
    score: int 

class ConsensusCalc(TypedDict):
    consensus_reached: bool
    agreement_percentage: float
    threshold: float
    decision_id: str
    timestamp: str

class ConsensusInfo(TypedDict):
    label: str
    agreement_pct: float
    threshold_required: float
    threshold_tier: str

class ArbitrationInfo(TypedDict):
    triggered: bool
    reason: str

class TelemetryInfo(TypedDict):
    consensus_achievement_rate: float
    average_confidence_score: float
    decision_id: str
    timestamp: str

class VerdictInfo(TypedDict):
    consensus_reached: bool
    arbitration_triggered: bool
    confidence_score: float
    top_agent: str
    num_agents_considered: int

class ConsensusSummary(TypedDict):
    consensus: ConsensusInfo
    providers: List[ProviderSummary]
    arbitration: ArbitrationInfo
    telemetry: TelemetryInfo
    verdict: VerdictInfo  # Added verdict field

def validate_provider_result(result: dict, provider_name: str) -> ProviderResult:
    """
    Validate and type-check provider result.
    
    Args:
        result: Raw provider result dict
        provider_name: Name of the provider
        
    Returns:
        Validated ProviderResult
        
    Raises:
        ValueError: If required fields are missing
    """
    if not isinstance(result, dict):
        raise ValueError(f"Provider {provider_name} result is not a dict")
    
    # Validate required fields
    if 'status' not in result:
        raise ValueError(f"Provider {provider_name} missing 'status' field")
    
    return ProviderResult(
        status=str(result.get('status', 'unknown')),
        confidence=float(result.get('confidence', 0.5)),
        latency_ms=int(result.get('latency_ms', 0)),
        response=str(result.get('response', ''))
    )


def validate_consensus_calc(calc: dict) -> ConsensusCalc:
    """
    Validate consensus calculation input.
    
    Args:
        calc: Raw consensus calculation dict
        
    Returns:
        Validated ConsensusCalc
        
    Raises:
        ValueError: If critical fields are missing
    """
    if not isinstance(calc, dict):
        raise ValueError("Consensus calc is not a dict")
    
    return ConsensusCalc(
        consensus_reached=bool(calc.get('consensus_reached', False)),
        agreement_percentage=float(calc.get('agreement_percentage', 0.0)),
        threshold=float(calc.get('threshold', 95.0)),
        decision_id=str(calc.get('decision_id', '')),
        timestamp=str(calc.get('timestamp', ''))
    )


def build_consensus_summary(consensus_calc: dict, provider_results: dict) -> ConsensusSummary:
    """
    Build normalized JSON contract with consensus details.
    
    Args:
        consensus_calc: Raw consensus calculation results
        provider_results: Raw provider responses dict
        
    Returns:
        Typed and validated consensus summary
        
    Raises:
        ValueError: If input validation fails
    """
    # Validate inputs
    calc = validate_consensus_calc(consensus_calc)
    
    # Extract values with type safety
    consensus_reached = calc['consensus_reached']
    agreement_pct = calc['agreement_percentage']
    threshold = calc['threshold']
    
    # Determine threshold tier
    if threshold >= 95:
        threshold_tier = "HIGH"
    elif threshold >= 80:
        threshold_tier = "MEDIUM"
    else:
        threshold_tier = "LOW"
    
    # Build provider details with validation
    providers: List[ProviderSummary] = []
    total_confidence = 0.0
    provider_count = 0
    
    for provider_name, result in provider_results.items():
        try:
            # Validate provider result
            validated_result = validate_provider_result(result, provider_name)
            
            if validated_result['status'] == 'success':
                confidence = validated_result['confidence']
                total_confidence += confidence
                provider_count += 1
                
                # Determine verdict based on confidence
                if confidence > 0.7:
                    verdict = "AGREE"
                elif confidence < 0.3:
                    verdict = "DISAGREE"
                else:
                    verdict = "NEUTRAL"
                
                # Extract rationale safely
                response_text = validated_result['response']
                if len(response_text) > 80:
                    rationale = response_text[:80] + "..."
                else:
                    rationale = response_text
                # Calculate score (0-100 based on confidence)
                score = int(confidence * 100)
                providers.append(ProviderSummary(
                    name=provider_name,
                    verdict=verdict,
                    confidence=round(confidence, 3),
                    latency_ms=validated_result['latency_ms'],
                    rationale=rationale,
                    score=score
                ))
        except ValueError as e:
            # Log validation error but continue
            print(f"Validation error for provider {provider_name}: {e}")
            continue
    
    # Calculate telemetry with type safety
    avg_confidence = (total_confidence / provider_count) if provider_count > 0 else 0.0
    consensus_achievement_rate = 1.0 if consensus_reached else 0.0
    
    # Determine arbitration status
    arbitration_triggered = not consensus_reached and agreement_pct < threshold
    arbitration_reason = ""
    if arbitration_triggered:
        arbitration_reason = f"Agreement {agreement_pct:.1f}% below threshold {threshold:.1f}%"
    
    # Find top agent by confidence
    top_agent = None
    if providers:
        top_agent = max(providers, key=lambda p: p['confidence'])['name']
    
    # Build typed summary with verdict
    summary = ConsensusSummary(
        consensus=ConsensusInfo(
            label="CONSENSUS_REACHED" if consensus_reached else "NO_CONSENSUS",
            agreement_pct=round(agreement_pct, 1),
            threshold_required=round(threshold, 1),
            threshold_tier=threshold_tier
        ),
        providers=providers,
        arbitration=ArbitrationInfo(
            triggered=arbitration_triggered,
            reason=arbitration_reason
        ),
        telemetry=TelemetryInfo(
            consensus_achievement_rate=round(consensus_achievement_rate, 3),
            average_confidence_score=round(avg_confidence, 3),
            decision_id=calc['decision_id'],
            timestamp=calc['timestamp']
        ),
        verdict=VerdictInfo(
            consensus_reached=consensus_reached,
            arbitration_triggered=arbitration_triggered,
            confidence_score=round(avg_confidence, 3),
            top_agent=top_agent or 'none',
            num_agents_considered=len(providers)
        )
    )
    
    return summary


def render_consensus_panel(summary: ConsensusSummary) -> str:
    """
    Render human-readable consensus panel.
    
    Args:
        summary: Typed consensus summary
        
    Returns:
        Formatted text panel
    """
    lines: List[str] = []
    lines.append("=" * 70)
    lines.append("CONSENSUS PANEL")
    lines.append("=" * 70)
    
    # Consensus status - all fields guaranteed by type
    consensus = summary['consensus']
    lines.append(f"Status: {consensus['label']}")
    lines.append(f"Agreement: {consensus['agreement_pct']}% "
                 f"(Threshold: {consensus['threshold_required']}% - "
                 f"{consensus['threshold_tier']})")
    
    # Arbitration status - guaranteed fields
    arbitration = summary['arbitration']
    if arbitration['triggered']:
        lines.append(f"⚠️ Arbitration: TRIGGERED - {arbitration['reason']}")
    else:
        lines.append(f"✅ Arbitration: Not Required")
    
    lines.append("")
    lines.append("Provider Assessments:")
    lines.append("-" * 70)
    
    # Header
    lines.append(f"{'Provider':<12} {'Verdict':<10} {'Confidence':<12} {'Latency':<10} {'Rationale'}")
    lines.append("-" * 70)
    
    # Provider rows - all fields guaranteed
    for provider in summary['providers']:
        lines.append(
            f"{provider['name']:<12} "
            f"{provider['verdict']:<10} "
            f"{provider['confidence']:<12.3f} "
            f"{provider['latency_ms']:<10}ms "
            f"{provider['rationale']}"
        )
    
    lines.append("-" * 70)
    
    # Telemetry - guaranteed fields
    telemetry = summary['telemetry']
    lines.append("Telemetry:")
    lines.append(f"  Consensus Achievement Rate: {telemetry['consensus_achievement_rate']:.3f}")
    lines.append(f"  Average Confidence Score: {telemetry['average_confidence_score']:.3f}")
    lines.append(f"  Decision ID: {telemetry['decision_id']}")
    
    # Add verdict section
    if 'verdict' in summary:
        verdict = summary['verdict']
        lines.append("")
        lines.append("Verdict Summary:")
        lines.append(f"  Consensus Reached: {verdict['consensus_reached']}")
        lines.append(f"  Arbitration Triggered: {verdict['arbitration_triggered']}")
        lines.append(f"  Top Agent: {verdict['top_agent']}")
        lines.append(f"  Confidence Score: {verdict['confidence_score']:.3f}")
        lines.append(f"  Agents Considered: {verdict['num_agents_considered']}")
    
    # PHASE 1 WEIGHTED VOTING: Display weight information if available
    if 'weighted_voting' in summary and summary['weighted_voting'].get('enabled'):
        wv = summary['weighted_voting']
        lines.append("")
        lines.append("⚖️  Weighted Voting (Phase 1):")
        lines.append(f"  Task Type: {wv['task_type'].upper()}")
        lines.append(f"  Classification Confidence: {wv['classification_confidence']:.0%}")
        lines.append(f"  Weights Applied:")
        for provider, weight in wv['weights_applied'].items():
            lines.append(f"    {provider}: {weight:.2f}x")
        if wv.get('explanation'):
            lines.append(f"  Rationale: {wv['explanation']}")
    
    lines.append("=" * 70)
    
    return "\n".join(lines)