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
# defines_classes: "EmailNotifier, ProviderDataEntry"
# defines_functions: "get_email_notifier, __init__, _send_email, _load_template, _truncate_to_tokens, _extract_providers_data, send_formatted_result, send_otp"
# =============================================================================
# DEPENDENCIES:
# =============================================================================
# =============================================================================
# FIELD CONTRACTS:
# =============================================================================
#   input_sources:
#     - path: "src/utils/tier_response_formatter.py"
#       type: "FormattedResponse"
#     - path: "src/agents/consensus_contract.py"
#       type: "ConsensusResult"
#     - path: "environment variable RESEND_API_KEY"
#       type: "OS_Environment"
#   output_destinations:
#     - path: "Resend API"
#       type: "External_Email_Delivery"
# =============================================================================
# CHANGE LOG:
# =============================================================================
# v4.0.0 - 2026-02-26: HAL-001 sprint — 1 return annotation fixed, 2 deferred.
# v3.0.0 - 2026-02-25: Previous production release.
# v4.1.0 - 2026-03-25: CCI_SE_ILL3_04 — result params typed as RawConsensusDict
#   in _extract_providers_data and send_formatted_result. project_name corrected.
# === END OF SCRIPT DNA HEADER ====================================

import os
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, TypedDict
from jinja2 import Template

from src.utils.tier_response_formatter import (
    format_response_for_tier,
    FormattedResponse,
    should_show_llm_responses,
    get_tier_code
)
from src.utils.tier_response_formatter import RawConsensusDict
# Resend HTTP API
try:
    import resend
    RESEND_AVAILABLE = True
except ImportError:
    RESEND_AVAILABLE = False
    logging.warning("resend package not available - pip install resend")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Singleton instance
_email_notifier_instance = None

print("🔴🔴🔴 EMAIL_NOTIFIER.PY v6.0.4 LOADED (RESEND + TIER + ORACLE RISK + LEGAL) 🔴🔴🔴", flush=True)

# =============================================================================
# HAL-001 TYPED RESULT CLASSES
# =============================================================================

class ProviderDataEntry(TypedDict):
    """Fixed-shape provider data entry returned by _extract_providers_data.
    Shape is invariant across all 4 fallback paths in that method."""
    provider: str
    answer: str
    confidence: float
    score: int


def get_email_notifier():
    """
    Lazy singleton factory for EmailNotifier
    Returns cached instance with Resend API configured
    """
    global _email_notifier_instance
    if _email_notifier_instance is None:
        _email_notifier_instance = EmailNotifier()
    return _email_notifier_instance


class EmailNotifier:
    """
    Email notifier using Resend HTTP API with tier-based response truncation
    
    Features:
    - Resend HTTP API (Railway Hobby plan compatible - no SMTP ports needed)
    - Tier-based truncation (free=500, premium=2000, unlimited=8000 tokens)
    - Template caching for performance
    - Defensive extraction of consensus metadata
    - OTP delivery for user registration
    
    Environment Variables:
        RESEND_API_KEY: Required - API key from resend.com
        RESEND_SENDER_EMAIL: Optional - defaults to noreply@seekrates-ai.com
    """
    
    def __init__(self):
        """Initialize with Resend HTTP API"""
        # Common settings
        self.sender_name = 'Seekrates AI'
        self._template_cache = {}
        self.email_method = 'Resend (not configured)'  # Default - prevents AttributeError
        
        # Resend Configuration
        self.api_key = os.getenv('RESEND_API_KEY')
        self.sender_email = os.getenv('RESEND_SENDER_EMAIL', 'noreply@seekrates-ai.com')
        
        if not self.api_key:
            logger.error("❌ RESEND_API_KEY not set - email sending will fail")
            self.email_method = 'Resend (API key missing)'
        elif not RESEND_AVAILABLE:
            logger.error("❌ resend package not installed - pip install resend")
            self.email_method = 'Resend (package missing)'
        else:
            resend.api_key = self.api_key
            self.email_method = 'Resend'
            logger.info(f"✅ EmailNotifier initialized with Resend: {self.sender_email}")
    
    def _send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None
    ) -> bool:
        """Send email via Resend HTTP API"""
        if not self.api_key:
            logger.error("❌ Cannot send email: RESEND_API_KEY not configured")
            return False
        
        if not RESEND_AVAILABLE:
            logger.error("❌ Cannot send email: resend package not installed")
            return False
        
        try:
            params: resend.Emails.SendParams = {
                "from": f"{self.sender_name} <{self.sender_email}>",
                "to": [to_email],
                "subject": subject,
                "html": html_content,
                "headers": {
                    "Content-Type": "text/html; charset=utf-8"
                }
            }
            
            if text_content:
                params["text"] = text_content
            
            print(f"[RESEND] Calling resend.Emails.send, payload size: {len(params.get('html', ''))}", flush=True)
            response = resend.Emails.send(params)
            print(f"[RESEND] Response: {response}", flush=True)
            
            # Response contains 'id' on success
            email_id = response.get('id', 'unknown') if isinstance(response, dict) else str(response)
            logger.info(f"✅ [Resend] Email sent successfully to {to_email} (ID: {email_id})")
            return True
            
        except Exception as e:
            logger.error(f"❌ [Resend] Failed to send email: {e}", exc_info=True)
            return False
    
    def _load_template(self, template_name: str) -> Optional[Template]:
        """Load and cache Jinja2 template"""
        if template_name in self._template_cache:
            return self._template_cache[template_name]
        
        possible_paths = [
            Path('static') / template_name,
            Path('templates') / template_name,
            Path(__file__).parent.parent.parent / 'static' / template_name,
            Path(__file__).parent.parent.parent / 'templates' / template_name
        ]
        
        for template_path in possible_paths:
            if template_path.exists():
                try:
                    with open(template_path, 'r', encoding='utf-8') as f:
                        template_content = f.read()
                    template = Template(template_content)
                    self._template_cache[template_name] = template
                    logger.info(f"Template loaded and cached: {template_name}")
                    return template
                except Exception as e:
                    logger.error(f"Error loading template {template_path}: {e}")
                    continue
        
        logger.error(f"Template not found: {template_name}")
        return None
    
    def _truncate_to_tokens(self, text: str, max_tokens: int) -> str:
        """
        Truncate text to approximately max_tokens (4 chars ≈ 1 token)
        Preserves sentence boundaries
        """
        max_chars = max_tokens * 4
        
        if len(text) <= max_chars:
            return text
        
        truncated = text[:max_chars]
        
        # Find last sentence boundary
        for delimiter in ['. ', '! ', '? ', '\n']:
            last_sentence = truncated.rfind(delimiter)
            if last_sentence > max_chars * 0.8:
                return truncated[:last_sentence + 1]
        
        last_space = truncated.rfind(' ')
        if last_space > 0:
            truncated = truncated[:last_space]
        
        # Format truncation notice (plain text for email body)
        notice = f"\n\n[Response truncated to tier limit]"
        return truncated + notice
    
    def _extract_providers_data(self, result: RawConsensusDict) -> List[ProviderDataEntry]:  # CCI_SE_ILL3_04: RawConsensusDict replaces Dict[str,Any]  # HAL-001-DEFERRED [ARCH_EXCEPTION] EX-SE-018
                                                                                              # cross-module boundary. Deferred to shared contracts sprint.
        """
        Extract provider data from consensus result
        Handles multiple result formats defensively
        """
        if result is None:
            logger.error("Result is None")
            return []
        
        providers_data = []
        
        # Try structured_results (V4 format)
        structured_results = result.get('structured_results', [])
        if structured_results:
            for item in structured_results:
                if isinstance(item, dict):
                    providers_data.append({
                        'provider': item.get('provider', 'Unknown'),
                        'answer': item.get('answer', ''),
                        'confidence': item.get('confidence', 0.0),
                        'score': item.get('score', 0)
                    })
            if providers_data:
                logger.info(f"✅ Extracted {len(providers_data)} providers from structured_results")
                return providers_data
        
        # Fallback: Try results key
        results_list = result.get('results', [])
        if results_list:
            for item in results_list:
                if isinstance(item, dict):
                    providers_data.append({
                        'provider': item.get('provider', 'Unknown'),
                        'answer': item.get('answer', ''),
                        'confidence': item.get('confidence', 0.0),
                        'score': item.get('score', 0)
                    })
            if providers_data:
                logger.info(f"✅ Extracted {len(providers_data)} providers from results")
                return providers_data
        
        # Fallback: Try providers key
        providers_list = result.get('providers', [])
        if providers_list:
            for item in providers_list:
                if isinstance(item, dict):
                    providers_data.append({
                        'provider': item.get('provider', 'Unknown'),
                        'answer': item.get('answer', ''),
                        'confidence': item.get('confidence', 0.0),
                        'score': item.get('score', 0)
                    })
            if providers_data:
                logger.info(f"✅ Extracted {len(providers_data)} providers from providers")
                return providers_data
        
        # Fallback: Try responses key (common format)
        responses_list = result.get('responses', [])
        if responses_list:
            for item in responses_list:
                if isinstance(item, dict):
                    providers_data.append({
                        'provider': item.get('provider', item.get('agent', 'Unknown')),
                        'answer': item.get('response', item.get('text', item.get('content', ''))),
                        'confidence': item.get('confidence', 0.0),
                        'score': item.get('score', 0)
                    })
            if providers_data:
                logger.info(f"✅ Extracted {len(providers_data)} providers from responses")
                return providers_data
        
        logger.error("No provider data found in result")
        return []
    
    def send_formatted_result(
        self,
        user_email: str,
        query: str,
        result: RawConsensusDict,  # CCI_SE_ILL3_04: RawConsensusDict replaces Dict[str,Any]  # HAL-001-DEFERRED [ARCH_EXCEPTION] EX-SE-019
        tier_name: str = 'free'
    ) -> bool:
        print("🔵🔵🔵 SEND_FORMATTED_RESULT CALLED 🔵🔵🔵", flush=True)
        """
        Send formatted consensus result email with tier-based truncation
        
        v5.0.0 CHANGES:
        - Integrated tier_response_formatter for Seeker/Acolyte/Oracle/Sage
        - Seeker: LLM responses HIDDEN, upgrade prompt shown
        - Acolyte: LLM responses truncated to 500 chars
        - Oracle/Sage: Full responses
        
        v3.2.0 CHANGES:
        - Brand kit compliant (Indigo→Teal gradient, Poppins/Manrope fonts)
        - Synthesis panel displayed FIRST (never truncated)
        - Individual responses displayed SECOND (tier-truncated)
        
        Brand Kit Colors:
        - Indigo: #0B1E3A
        - Teal: #1CB5E0
        - Charcoal: #101820
        - Silver Mist: #F2F4F7
        - White: #FFFFFF
        
        Args:
            user_email: Recipient email address
            query: Original user query
            result: Consensus engine result dict (now includes consensus_panel)
            tier_name: User's tier (free/seeker/acolyte/oracle/sage/premium/unlimited)
        
        Returns:
            True if sent successfully
        """
        try:
            print("[EMAIL-DEBUG-ENTRY] send_formatted_result ENTERED", flush=True)
            logger.info(f"📧 Preparing email for {tier_name.upper()} tier user: {user_email}")
            
            # Defensive: Handle None result
            if result is None:
                logger.error("Result is None - cannot send email")
                return False
            
            # ================================================================
            # v5.0.0: TIER-BASED FORMATTING
            # ================================================================
            formatted = format_response_for_tier(result, tier_name)
            show_llm_responses = formatted.show_llm_responses
            tier_upgrade_prompt = formatted.upgrade_prompt
            tier_code = formatted.tier_code
            print(f"[EMAIL-TIER] Code: {tier_code}, Show LLM: {show_llm_responses}, Upgrade: {bool(tier_upgrade_prompt)}", flush=True)
            
            # Extract provider data
            providers_data = self._extract_providers_data(result)
            print(f"[EMAIL-DEBUG-PROVIDERS] providers_data count: {len(providers_data) if providers_data else 0}", flush=True)
            # DIAGNOSTIC: Log payload sizes
            total_response_chars = sum(len(str(p.get('answer', ''))) for p in providers_data)
            print(f"[EMAIL-SIZE] Total response chars: {total_response_chars}", flush=True)
            print(f"[EMAIL-SIZE] Query length: {len(query)}", flush=True)

            if not providers_data:
                logger.error("No provider data - cannot send email")
                return False
            
            # Extract consensus summary
            consensus = result.get('consensus', {})
            consensus_reached = consensus.get('reached', False)
            agreement_pct = consensus.get('agreement_percentage', 0)
            champion_provider = consensus.get('champion', 'Unknown')
            champion_score = consensus.get('champion_score', 0)
            
            # NEW: Extract consensus_panel (from synthesis.py)
            consensus_panel = consensus.get('consensus_panel', '')
            divergence_highlight = consensus.get('divergence_highlight', '')
            dissenting_provider = consensus.get('dissenting_provider', '')
            dissent_confidence = consensus.get('dissent_confidence', 0.0)
            print(f"[EMAIL-DEBUG-DIVERGENCE] divergence_highlight: {divergence_highlight[:50] if divergence_highlight else 'empty'}", flush=True)
            print(f"[EMAIL-DEBUG-PANEL] consensus_panel length: {len(consensus_panel)}", flush=True)
            
            # =================================================================
            # v6.0.0: ORACLE RISK PASS DATA EXTRACTION
            # =================================================================
            # NOTE: risk_analysis is at TOP LEVEL of result, not inside consensus
            risk_analysis = result.get('risk_analysis', {})
            has_risk_analysis = bool(risk_analysis) and tier_name.lower() in ('oracle', 'sage')
            
            if has_risk_analysis:
                risk_assumptions = risk_analysis.get('assumptions', [])
                risk_failure_modes = risk_analysis.get('failure_modes', [])
                risk_contrarian = risk_analysis.get('contrarian_argument', '')
                risk_contrarian_significance = risk_analysis.get('contrarian_significance', 'MINOR')
                risk_contrarian_reasoning = risk_analysis.get('contrarian_reasoning', '')
                risk_recommendation = risk_analysis.get('oracle_recommendation', '')
                risk_checklist = risk_analysis.get('validation_checklist', [])
                print(f"[EMAIL-ORACLE] Risk analysis found: {len(risk_assumptions)} assumptions, {len(risk_checklist)} checklist items", flush=True)
            else:
                risk_assumptions = []
                risk_failure_modes = []
                risk_contrarian = ''
                risk_contrarian_significance = 'MINOR'
                risk_contrarian_reasoning = ''
                risk_recommendation = ''
                risk_checklist = []
                print(f"[EMAIL-ORACLE] No risk analysis (tier={tier_name})", flush=True)
            
            # Tier-based token limits (v5.0.0 - expanded for new tiers)
            tier_limits = {
                'free': 500,
                'seeker': 500,
                'acolyte': 500,      # Truncated display
                'oracle': 8000,      # Full display
                'sage': 8000,        # Full display
                'premium': 2000,     # Legacy
                'unlimited': 8000    # Legacy
            }
            max_tokens = tier_limits.get(tier_name.lower(), 500)
            
            # Calculate metrics
            if providers_data:
                confidences = [r.get('confidence', 0) for r in providers_data]
                avg_confidence = sum(confidences) / len(confidences) * 100 if confidences else 0
                QUALITY_THRESHOLD = 40  # Matches synthesis threshold
                scores = [r.get('score', 0) for r in providers_data if r.get('score', 0) > 0]
                max_score = max(scores, default=0)
                champion_agent = champion_provider
                # v6.0.6: Count quality responses (score >= 40) for honest consensus display
                valid_response_count = len([s for s in scores if s >= QUALITY_THRESHOLD])
                total_response_count = len(providers_data)
            else:
                avg_confidence = 0
                champion_agent = 'None'
                max_score = 0
            
            any_truncated = False
            
            # Email subject - ASCII safe (emojis unreliable in email subjects)
            subject = f"Query Results: {query[:50]}{'...' if len(query) > 50 else ''}"
            
            # =================================================================
            # BUILD HTML EMAIL - BRAND KIT COMPLIANT
            # =================================================================
            html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&family=Manrope:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        /* ===== BRAND KIT COLORS ===== */
        :root {{
            --indigo: #0B1E3A;
            --teal: #1CB5E0;
            --charcoal: #101820;
            --silver-mist: #F2F4F7;
            --white: #FFFFFF;
            --gradient: linear-gradient(90deg, #0B1E3A 0%, #1CB5E0 100%);
        }}
        
        body {{
            font-family: 'Manrope', 'Segoe UI', Arial, sans-serif;
            line-height: 1.6;
            color: #101820;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background-color: #F2F4F7;
        }}
        
        .container {{
            background: #FFFFFF;
            padding: 0;
            border-radius: 16px;
            box-shadow: 0 4px 20px rgba(11, 30, 58, 0.1);
            overflow: hidden;
        }}
        
        .header {{
            background: linear-gradient(90deg, #0B1E3A 0%, #1CB5E0 100%);
            color: white;
            padding: 30px 40px;
            text-align: center;
        }}
        
        .header h1 {{
            font-family: 'Poppins', sans-serif;
            font-weight: 700;
            font-size: 28px;
            margin: 0;
            letter-spacing: -0.5px;
        }}
        
        .header .tagline {{
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 3px;
            opacity: 0.9;
            margin-top: 8px;
        }}
        
        .header .tier-badge {{
            display: inline-block;
            background: rgba(255,255,255,0.2);
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 11px;
            margin-top: 12px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        
        .content {{
            padding: 30px 40px;
        }}
        
        .query-box {{
            background: #F2F4F7;
            border-left: 4px solid #1CB5E0;
            padding: 20px;
            margin-bottom: 25px;
            border-radius: 0 8px 8px 0;
        }}
        
        .query-box h3 {{
            font-family: 'Poppins', sans-serif;
            color: #0B1E3A;
            margin: 0 0 10px 0;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        
        .query-box p {{
            margin: 0;
            font-size: 16px;
            color: #101820;
        }}
        
        .metrics {{
            display: flex;
            gap: 15px;
            margin-bottom: 25px;
            flex-wrap: wrap;
        }}
        
        .metric-card {{
            flex: 1;
            min-width: 100px;
            background: #FFFFFF; 
            color: #0B1E3A; 
            border: 2px solid #0B1E3A;
            padding: 20px;
            border-radius: 12px;
            text-align: center;
        }}
        
        .metric-value {{
            font-family: 'Poppins', sans-serif;
            font-size: 28px;
            font-weight: 700;
        }}
        
        .metric-label {{
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 1px;
            opacity: 0.8;
            margin-top: 5px;
        }}
        
        .consensus-status {{
            padding: 20px;
            border-radius: 12px;
            margin-bottom: 25px;
            text-align: center;
        }}
        
        .consensus-status.reached {{
            background: #FFFFFF; 
            border: 2px solid #28a745;
        }}
        
        .consensus-status.not-reached {{
            background: #FFFFFF; 
            border: 2px solid #ffc107;
        }}
        
        .consensus-status h3 {{
            font-family: 'Poppins', sans-serif;
            margin: 0;
            font-size: 18px;
        }}
        
        .synthesis-section {{
            background: #FFFFFF; 
            color: #0B1E3A; 
            border: 2px solid #1CB5E0;
            padding: 25px;
            border-radius: 12px;
            margin-bottom: 25px;
        }}
        
        .synthesis-section h2 {{
            font-family: 'Poppins', sans-serif;
            margin: 0 0 15px 0;
            font-size: 18px;
            color: #1CB5E0;
        }}
        
        .synthesis-section p,
        .synthesis-section span,
        .synthesis-section div {{
            color: #0B1E3A !important;
        }}
        
        /* ===== ORACLE RISK PASS STYLES (v6.0.0) ===== */
        .oracle-risk-container {{
            margin: 25px 0;
            padding: 0;
        }}
        
        .oracle-risk-header {{
            background: linear-gradient(90deg, #0B1E3A 0%, #1CB5E0 100%);
            color: white;
            padding: 15px 20px;
            border-radius: 12px 12px 0 0;
            font-family: 'Poppins', sans-serif;
            font-size: 16px;
            font-weight: 600;
        }}
        
        .risk-section {{
            background: #FFFFFF;
            border: 2px solid #e0e0e0;
            border-top: none;
            padding: 20px;
        }}
        
        .risk-section:last-child {{
            border-radius: 0 0 12px 12px;
        }}
        
        .risk-section h4 {{
            font-family: 'Poppins', sans-serif;
            color: #0B1E3A;
            margin: 0 0 12px 0;
            font-size: 14px;
        }}
        
        .risk-section ul {{
            margin: 0;
            padding-left: 20px;
            color: #101820;
        }}
        
        .risk-section li {{
            margin-bottom: 8px;
            line-height: 1.5;
        }}
        
        .risk-section.assumptions {{
            border-left: 4px solid #ffc107;
        }}
        
        .risk-section.failure-modes {{
            border-left: 4px solid #dc3545;
        }}
        
        .risk-section.contrarian {{
            border-left: 4px solid #6c757d;
        }}
        
        .risk-section.contrarian.material {{
            border-left: 4px solid #dc3545;
            background: #fff5f5;
        }}
        
        .oracle-recommendation {{
            background: linear-gradient(135deg, #e8f5e9 0%, #c8e6c9 100%);
            border: 2px solid #28a745;
            border-radius: 12px;
            padding: 20px;
            margin: 20px 0;
            text-align: center;
        }}
        
        .oracle-recommendation h4 {{
            font-family: 'Poppins', sans-serif;
            color: #28a745;
            margin: 0 0 10px 0;
            font-size: 16px;
        }}
        
        .oracle-recommendation p {{
            font-size: 15px;
            color: #0B1E3A;
            margin: 0;
            font-weight: 500;
            line-height: 1.6;
        }}
        
        .validation-checklist {{
            background: #f8f9fa;
            border: 2px solid #1CB5E0;
            border-radius: 12px;
            padding: 20px;
            margin: 20px 0;
        }}
        
        .validation-checklist h4 {{
            font-family: 'Poppins', sans-serif;
            color: #1CB5E0;
            margin: 0 0 15px 0;
            font-size: 14px;
        }}
        
        .validation-checklist ul {{
            list-style: none;
            padding: 0;
            margin: 0;
        }}
        
        .validation-checklist li {{
            padding: 8px 0 8px 28px;
            position: relative;
            color: #101820;
            border-bottom: 1px solid #e0e0e0;
        }}
        
        .validation-checklist li:last-child {{
            border-bottom: none;
        }}
        
        .validation-checklist li::before {{
            content: "☐";
            position: absolute;
            left: 0;
            color: #1CB5E0;
            font-size: 16px;
        }}

        .responses-section {{
            margin-top: 30px;
        }}
        
        .responses-section h2 {{
            font-family: 'Poppins', sans-serif;
            color: #0B1E3A;
            font-size: 18px;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #F2F4F7;
        }}
        
        .response-box {{
            background: #FFFFFF; 
            border: 2px solid #0B1E3A;
            padding: 20px;
            margin-bottom: 15px;
            border-radius: 12px;
            border-left: 4px solid #0B1E3A;
        }}
        
        .response-box.champion {{
            border-left-color: #1CB5E0;
            background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%);
        }}
        
        .provider-name {{
            font-family: 'Poppins', sans-serif;
            font-weight: 600;
            color: #0B1E3A;
            font-size: 14px;
            margin-bottom: 8px;
        }}
        
        .champion-badge {{
            background: #FFFFFF; 
            border: 2px solid #1CB5E0;
            color: #0B1E3A;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 10px;
            margin-left: 8px;
        }}
        
        .truncated-badge {{
            background: #ffc107;
            color: #101820;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 10px;
            margin-left: 8px;
        }}
        
        .score-line {{
            font-size: 12px;
            color: #666;
            margin-bottom: 10px;
        }}
        
        .response-text {{
            font-size: 14px;
            line-height: 1.7;
            color: #101820;
            white-space: pre-wrap;
        }}
        
        .upgrade-cta {{
            background: #FFFFFF; 
            color: #0B1E3A; 
            border: 2px solid #1CB5E0;
            padding: 25px;
            border-radius: 12px;
            text-align: center;
            margin-top: 25px;
        }}
        
        .upgrade-cta h3 {{
            font-family: 'Poppins', sans-serif;
            margin: 0 0 10px 0;
        }}
        
        .upgrade-cta p {{
            margin: 0 0 15px 0;
            opacity: 0.9;
        }}
        
        .upgrade-cta a {{
            display: inline-block;
            background: white;
            color: #0B1E3A;
            padding: 10px 25px;
            border-radius: 8px;
            text-decoration: none;
            font-weight: 600;
            font-family: 'Poppins', sans-serif;
        }}
        
        .footer {{
            background: #F2F4F7;
            padding: 25px 40px;
            text-align: center;
            border-top: 1px solid #e0e0e0;
        }}
        
        .footer .brand {{
            font-family: 'Poppins', sans-serif;
            font-weight: 600;
            color: #0B1E3A;
            font-size: 14px;
        }}
        
        .footer .tagline {{
            color: #1CB5E0;
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 2px;
            margin-top: 8px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Header with Gradient -->
        <div class="header" style="background: #DFF4FA;">
            <h1 style="color: #0B1E3A;">Seekrates AI</h1>
            <div class="tagline" style="color: #0B1E3A;">WHERE AIs AGREE</div>
            <div class="tier-badge" style="color: #000000;">{tier_name.upper()} tier</div>
        </div>
        
        <div class="content">
            <!-- Query -->
            <div class="query-box">
                <h3>Your Query</h3>
                <p>{query}</p>
            </div>
            
            <!-- Metrics -->
            <div class="metrics">
                <div class="metric-card">
                    <div class="metric-value">{len(providers_data)}</div>
                    <div class="metric-label">Agents</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">{avg_confidence:.0f}%</div>
                    <div class="metric-label">Avg Confidence</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">{max_score}</div>
                    <div class="metric-label">Champion Score</div>
                </div>
            </div>
            
            <!-- Consensus Status -->
            <div class="consensus-status {'reached' if consensus_reached else 'not-reached'}">
                <h3>
                    {'✅ Consensus Reached' if consensus_reached else '⚠️ No Consensus'} ({valid_response_count}/{total_response_count} AIs agree)
                </h3>
                <p style="margin: 10px 0 0 0; font-size: 14px; color: #0B1E3A;">
                    Champion: <strong>{champion_agent.upper() if champion_agent else 'NONE'}</strong>
                </p>
            </div>
"""
            
            # =================================================================
            # SYNTHESIS SECTION - NEVER TRUNCATED (THE VALUE PROP)
            # =================================================================
            if consensus_panel and consensus_panel.strip() and '<' in consensus_panel:
                html_body += f"""
            <!-- Synthesis Panel -->
            <div class="synthesis-section">
                <h2>🤝 Consensus Analysis</h2>
                {consensus_panel}
            </div>
"""
            else:
                html_body += """
            <!-- Synthesis Panel -->
            <div class="synthesis-section">
                <h2>🤝 Consensus Analysis</h2>
                <p style="color: #0B1E3A; font-style: italic;">
                    Synthesis analysis not available for this query.
                </p>
            </div>
"""
                     
            # =================================================================
            # ORACLE RISK PASS SECTIONS (v6.0.0 - Oracle/Sage tiers only)
            # =================================================================
            if has_risk_analysis:
                # Build assumptions list
                assumptions_html = ""
                if risk_assumptions:
                    items = "".join([f"<li>{a}</li>" for a in risk_assumptions])
                    assumptions_html = f"""
                <div class="risk-section assumptions">
                    <h4>⚠️ ï¸ Key Assumptions</h4>
                    <p style="margin: 0 0 10px 0; font-size: 13px; color: #666;">This recommendation depends on:</p>
                    <ul>{items}</ul>
                </div>"""
                
                # Build failure modes list
                failure_html = ""
                if risk_failure_modes:
                    items = "".join([f"<li>{f}</li>" for f in risk_failure_modes])
                    failure_html = f"""
                <div class="risk-section failure-modes">
                    <h4>🔴 Failure Modes</h4>
                    <p style="margin: 0 0 10px 0; font-size: 13px; color: #666;">This advice could be wrong if:</p>
                    <ul>{items}</ul>
                </div>"""
                
                # Build contrarian section
                contrarian_html = ""
                if risk_contrarian:
                    significance_class = "material" if risk_contrarian_significance == "MATERIAL" else ""
                    significance_badge = f'<span style="background: {"#dc3545" if risk_contrarian_significance == "MATERIAL" else "#6c757d"}; color: white; padding: 2px 8px; border-radius: 4px; font-size: 11px; margin-left: 8px;">{risk_contrarian_significance}</span>'
                    contrarian_html = f"""
                <div class="risk-section contrarian {significance_class}">
                    <h4>�� Contrarian View {significance_badge}</h4>
                    <p style="margin: 0 0 8px 0; font-size: 14px; color: #333; font-style: italic;">"{risk_contrarian}"</p>
                    {f'<p style="margin: 0; font-size: 13px; color: #666;">{risk_contrarian_reasoning}</p>' if risk_contrarian_reasoning else ''}
                </div>"""
                
                # Combine risk sections with header
                html_body += f"""
            <!-- Oracle Risk Pass (v6.0.0) -->
            <div class="oracle-risk-container">
                <div class="oracle-risk-header">
                    🔮 Oracle Risk Analysis
                </div>
                {assumptions_html}
                {failure_html}
                {contrarian_html}
            </div>
"""
                
                # Oracle Recommendation badge
                if risk_recommendation:
                    html_body += f"""
            <!-- Oracle Recommendation -->
            <div class="oracle-recommendation">
                <h4>🎯 Oracle Recommendation</h4>
                <p>{risk_recommendation}</p>
            </div>
"""
                
                # Validation Checklist
                if risk_checklist:
                    checklist_items = "".join([f"<li>{item}</li>" for item in risk_checklist])
                    html_body += f"""
            <!-- Validation Checklist -->
            <div class="validation-checklist">
                <h4>✅ Before You Act</h4>
                <ul>{checklist_items}</ul>
            </div>
"""
            
            # =================================================================
            # DIVERGENCE HIGHLIGHT SECTION (v1.2.0 - Session 71)
            # =================================================================
            divergence_html = ""
            if divergence_highlight:
                divergence_html = f"""
            <!-- Divergence Highlight -->
            <div style="background: #fff3cd; border-left: 4px solid #ffc107; padding: 20px; margin: 25px 0; border-radius: 0 12px 12px 0;">
                <h4 style="font-family: 'Poppins', sans-serif; color: #856404; margin: 0 0 12px 0; font-size: 16px;">
                    🔎 Dissenting View
                </h4>
                <p style="margin: 0 0 8px 0; font-size: 14px; color: #333;">
                    <strong style="color: #0B1E3A;">{dissenting_provider}</strong> disagrees with the consensus:
                </p>
                <p style="margin: 0; font-style: italic; color: #555; font-size: 14px; line-height: 1.5;">
                    "{divergence_highlight}"
                </p>
                <p style="margin: 12px 0 0 0; font-size: 12px; color: #856404;">
                    Confidence delta: {dissent_confidence:.0%}
                </p>
            </div>
"""

            # =================================================================
            # INDIVIDUAL RESPONSES - CONDITIONAL BY TIER (v5.0.0)
            # =================================================================
            if show_llm_responses:
                html_body += f"""
            <!-- Individual Responses -->
            {divergence_html}
            <div class="responses-section">
                <h2>🔎‹ Individual Agent Responses</h2>
"""
                
                for response_data in providers_data:
                    provider = response_data.get('provider', 'Unknown')
                    answer = response_data.get('answer', 'No response')
                    score = response_data.get('score', 0)
                    confidence = response_data.get('confidence', 0)
                    
                    # Apply tier-aware truncation
                    original_length = len(answer)
                    answer = self._truncate_to_tokens(answer, max_tokens)
                    was_truncated = len(answer) < original_length
                    
                    if was_truncated:
                        any_truncated = True
                    
                    is_champion = (provider == champion_agent)
                    
                    html_body += f"""
                <div class="response-box {'champion' if is_champion else ''}">
                    <div class="provider-name">
                        {provider.upper()}
                        {'<span class="champion-badge">🏆 CHAMPION</span>' if is_champion else ''}
                        {'<span class="truncated-badge">✂ TRUNCATED</span>' if was_truncated else ''}
                    </div>
                    <div class="score-line">
                        <strong>Score:</strong> {score} pts | <strong>Confidence:</strong> {confidence:.0%}
                    </div>
                    <div class="response-text">{answer}</div>
                </div>
"""
                
                html_body += """
            </div>
"""
            else:
                # Seeker tier: Show divergence but hide individual responses
                html_body += divergence_html
            
            # =================================================================
            # UPGRADE CTA (v5.0.0 - tier-based prompt from formatter)
            # =================================================================
            if tier_upgrade_prompt:
                html_body += f"""
            <!-- Upgrade CTA -->
            <div class="upgrade-cta">
                <h3>💡 {tier_upgrade_prompt}</h3>
                <a href="https://app.seekrates-ai.com/pricing">View Plans →</a>
            </div>
"""
            elif any_truncated and tier_name.lower() in ('free', 'seeker'):
                # Fallback for edge cases
                html_body += """
            <!-- Upgrade CTA -->
            <div class="upgrade-cta">
                <h3>🔎ˆ Upgrade to See More</h3>
                <p>Get full AI responses and detailed analysis.</p>
                <a href="https://app.seekrates-ai.com/pricing">View Plans →</a>
            </div>
"""
            
            html_body += """
        </div>
        
        <!-- Footer -->
        <div class="footer">
            <p class="brand">Seekrates AI</p>
            <p class="tagline">WHERE AIs AGREE</p>
            <p style="margin-top: 12px;">Making better decisions through AI consensus</p>
            <p style="font-size: 10px; color: #999; margin-top: 8px;">This is an automated email. Please do not reply.</p>
            <p style="font-size: 9px; color: #9CA3AF; margin-top: 16px; line-height: 1.4;">
                GPT-4 is a trademark of OpenAI. Claude is a trademark of Anthropic. 
                Gemini is a trademark of Google. Mistral and Cohere are trademarks of 
                their respective owners. Seekrates AI is an independent platform and is 
                not affiliated with, endorsed by, or sponsored by any AI provider. 
                Consensus scores are proprietary Seekrates metrics and do not reflect 
                official performance ratings.
            </p>
        </div>
    </div>
</body>
</html>
"""
            
            # =================================================================
            # BUILD TEXT BODY (v6.0.7 - enables seekrates_publisher parsing)
            # =================================================================
            # Strip HTML from consensus_panel for text version
            import re as re_module
            clean_synthesis = re_module.sub(r'<[^>]+>', '', consensus_panel) if consensus_panel else ''
            clean_synthesis = clean_synthesis.strip()
            
            text_body = f"""SEEKRATES AI - CONSENSUS RESULTS
{'=' * 50}

YOUR QUERY
{query}

{'=' * 50}
SYNTHESIS
{clean_synthesis if clean_synthesis else 'No synthesis available.'}

{'=' * 50}
AGREEMENT: {valid_response_count}/{total_response_count} AIs agree
CHAMPION: {champion_agent.upper() if champion_agent else 'None'}
CONFIDENCE: {avg_confidence:.0f}%
"""
            
            # Add provider responses for Acolyte+ tiers (v6.0.7)
            if show_llm_responses and providers_data:
                text_body += f"""
{'=' * 50}
📎 INDIVIDUAL AGENT RESPONSES
{'=' * 50}
"""
                for response_data in providers_data:
                    provider = response_data.get('provider', 'Unknown')
                    answer = response_data.get('answer', 'No response')
                    score = response_data.get('score', 0)
                    confidence = response_data.get('confidence', 0)
                    is_champion = (provider.lower() == champion_agent.lower() if champion_agent else False)
                    
                    champion_marker = " 🏆 CHAMPION" if is_champion else ""
                    text_body += f"""
{provider.upper()}{champion_marker}
Score: {score} pts | Confidence: {confidence:.0%}
{'-' * 40}
{answer}

"""
            
            text_body += f"""
{'=' * 50}
Seekrates AI - Where AIs Agree
https://seekrates-ai.com
"""
            
            print(f"[EMAIL-SIZE] Text body length: {len(text_body)}", flush=True)
            
            # Send email via Resend
            print(f"[EMAIL-SIZE] HTML body length: {len(html_body)}", flush=True)
            print(f"[EMAIL-STEP] About to call _send_email", flush=True)
            result = self._send_email(
                to_email=user_email,
                subject=subject,
                html_content=html_body,
                text_content=text_body
            )
            print(f"[EMAIL-STEP] _send_email returned: {result}", flush=True)
            return result
            
        except Exception as e:
            logger.error(f"❌ Failed to send formatted result email: {e}", exc_info=True)
            return False
    
    def send_otp(self, user_email: str, otp_code: str) -> bool:
        """
        Send OTP verification email
        
        Args:
            user_email: Recipient email
            otp_code: 6-digit verification code
        
        Returns:
            True if sent successfully
        """
        subject = "Verify Your Email - Seekrates AI"
        
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: Arial, sans-serif; text-align: center; padding: 50px; }}
        .otp-box {{ background: #FFFFFF; color: #0B1E3A; border: 3px solid #1CB5E0; padding: 20px; border-radius: 10px; display: inline-block; margin: 20px; }}
        .otp-code {{ font-size: 48px; font-weight: bold; letter-spacing: 10px; }}
    </style>
</head>
<body>
    <h1>Verify Your Email</h1>
    <p>Enter this code to complete your registration:</p>
    <div class="otp-box">
        <div class="otp-code">{otp_code}</div>
    </div>
    <p>This code expires in 10 minutes.</p>
    <p style="color: #666; font-size: 12px;">If you didn't request this code, please ignore this email.</p>
</body>
</html>
"""
        
        return self._send_email(
            to_email=user_email,
            subject=subject,
            html_content=html_content
        )