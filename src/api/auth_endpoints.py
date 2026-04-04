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
# defines_functions: "check_tc_acceptance, ensure_consensus_results_table, ensure_billing_tables, get_queries_today, get_user_tier_by_email, check_tier_limits, consensus_endpoint"
# =============================================================================
# DEPENDENCIES:
# =============================================================================
# =============================================================================
# FIELD CONTRACTS:
# =============================================================================
#   input_sources:
#     - path: "src/auth/user_manager.py"
#       type: "UserManager"
#     - path: "src/agents/consensus_engine.py"
#       type: "ConsensusResult"
#     - path: "src/billing/stripe_integration.py"
#       type: "UserTierInfo"
#   output_destinations:
#     - path: "HTTP_Response"
#       type: "JSON"
#     - path: ".database/queries.db"
#       type: "SQLite_Database"
# === END OF SCRIPT DNA HEADER ====================================

print("ðŸ”´ðŸ”´ðŸ”´ AUTH_ENDPOINTS LOADED ðŸ”´ðŸ”´ðŸ”´", flush=True)

from fastapi import APIRouter, Request, HTTPException, Header
from typing import Optional, Dict, Any
import re
from src.auth.user_manager import UserManager
from src.utils.email_notifier import get_email_notifier
from src.agents.consensus_engine import generate_expert_panel_response_v4
from src.agents.consensus_contract import ConsensusResult
from src.telemetry.research_archive import archive_consensus_result, ensure_research_db
from typing import Optional
# from src.auth.otp_service import OTPService  # Module not created yet - inline implementation below
from src.billing.stripe_integration import get_user_tier_by_email, check_tier_limits
import os
import sqlite3
import logging
from datetime import datetime
from fastapi.responses import JSONResponse


# =============================================================================
# T&C ACCEPTANCE CHECK - Added S89-02
# =============================================================================
def check_tc_acceptance(email: str) -> bool:
    """
    Check if user has accepted Terms & Conditions.
    Returns True if accepted, False if not accepted or user doesn't exist.
    Fails OPEN (returns True) on database errors to not block users.
    """
    try:
        db_path = os.path.join(os.environ.get('PROJECT_ROOT', '.'), '.database', 'telemetry.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT tc_accepted_at FROM customers WHERE email = ?",
            (email.lower().strip(),)
        )
        row = cursor.fetchone()
        conn.close()
        
        if row is None:
            return False  # New user, hasn't accepted
        return row[0] is not None  # True if timestamp exists
        
    except Exception as e:
        logging.error(f"[TC-CHECK] Database error: {e}")
        return True  # Fail open - don't block on DB errors

print("[AUTH-ENDPOINTS] Module loaded, router being created")
router = APIRouter()
print(f"[AUTH-ENDPOINTS] APIRouter created, defining endpoints...")
user_manager = UserManager()

# =============================================================================
# ENSURE DATABASE TABLES EXIST ON MODULE LOAD
# =============================================================================

def ensure_consensus_results_table():
    """Ensure consensus_results table exists in telemetry.db."""
    import sqlite3
    import os
    
    try:
        os.makedirs('.database', exist_ok=True)
        conn = sqlite3.connect('.database/telemetry.db')
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS consensus_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                query TEXT NOT NULL,
                champion TEXT,
                score REAL DEFAULT 0,
                agreement_percentage REAL DEFAULT 0,
                providers_count INTEGER DEFAULT 0,
                tier TEXT DEFAULT 'free',
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
        print("[DB] consensus_results table ensured")
    except Exception as e:
        print(f"[DB] Error ensuring consensus_results table: {e}")


def ensure_billing_tables():
    """Ensure customers and subscriptions tables exist."""
    import sqlite3
    import os
    
    try:
        os.makedirs('.database', exist_ok=True)
        conn = sqlite3.connect('.database/telemetry.db')
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                stripe_customer_id TEXT,
                tier TEXT DEFAULT 'SEK',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Safe migration: add use_case column if missing
        try:
            cursor.execute("ALTER TABLE customers ADD COLUMN use_case TEXT")
        except Exception:
            pass  # Column already exists
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                stripe_subscription_id TEXT,
                tier TEXT DEFAULT 'SEK',
                status TEXT DEFAULT 'active',
                current_period_start DATETIME,
                current_period_end DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (customer_id) REFERENCES customers(id)
            )
        """)
        
        conn.commit()
        conn.close()
        print("[DB] Billing tables (customers, subscriptions) ensured")
        
    except Exception as e:
        print(f"[DB] Error ensuring billing tables: {e}")


# Call both on module load
ensure_consensus_results_table()
ensure_billing_tables()
ensure_research_db()

def get_queries_today(user_identifier: str) -> int:
    """
    Get count of queries submitted today by this user.
    Queries consensus_results table in telemetry.db.
    
    Args:
        user_identifier: email address or user_id
        
    Returns:
        Number of queries submitted today (int)
    """
    import sqlite3
    from datetime import datetime, timezone
    
    try:
        conn = sqlite3.connect('.database/telemetry.db')
        cursor = conn.cursor()
        
        # Get today's date in UTC
        today = datetime.now(timezone.utc).date().isoformat()
        
        # Count queries from today for this user
        cursor.execute("""
            SELECT COUNT(*) 
            FROM consensus_results 
            WHERE user_id = ? 
            AND date(timestamp) = ?
        """, (user_identifier, today))
        
        count = cursor.fetchone()[0]
        conn.close()
        
        return count
        
    except Exception as e:
        print(f"[RATE_LIMIT] Error counting queries: {e}")
        # Fail open - allow query if we can't check (don't block user due to our bug)
        return 0


# =============================================================================
# TIER LOOKUP WRAPPER — CCI-SE-CP-01 (INDRA-163)
# Deferred local import isolates stripe_integration load failure from
# module-level startup. CP router registers unconditionally.
# =============================================================================
def get_user_tier_by_email(email: str) -> dict:  # HAL-001-DEFERRED
    """
    Wrapper: delegate tier lookup to stripe_integration.
    Returns tier dict with tier_name, tier_code, queries_per_day,
    queries_per_month, max_tokens.
    Fails safe — returns Seeker tier defaults on any error.
    Never raises.
    """
    try:
        from src.billing.stripe_integration import (
            get_user_tier_by_email as _get_user_tier_by_email,
        )
        return _get_user_tier_by_email(email)
    except Exception as e:
        logging.error(
            f"[TIER-LOOKUP] Failed for {email}: {e} — defaulting to Seeker"
        )
        return {
            "tier_name": "seeker",
            "tier_code": "SEK",
            "queries_per_day": 3,
            "queries_per_month": 90,
            "max_tokens": 500,
        }


def check_tier_limits(email: str, queries_today: int) -> tuple:
    """
    Wrapper: delegate tier limit check to stripe_integration.
    Returns (allowed: bool, message: str).
    Fails open — returns (True, '') on any error to avoid
    blocking users due to internal billing failures.
    Never raises.
    """
    try:
        from src.billing.stripe_integration import (
            check_tier_limits as _check_tier_limits,
        )
        return _check_tier_limits(email, queries_today)
    except Exception as e:
        logging.error(
            f"[TIER-LIMITS] Failed for {email}: {e} — failing open"
        )
        return (True, "")


@router.post("/consensus")
async def consensus_endpoint(request: Request, authorization: Optional[str] = Header(None)):
    """Consensus with optional auth - sends email with tier-based truncation"""
    print(f"[AUTH-DEBUG] Authorization header: {authorization}", flush=True) 
    print(f"[AUTH-DEBUG] Headers: {dict(request.headers)}", flush=True)       
    
    # Parse body ONCE at the top
    data = await request.json()
    
    user_id = None
    user_email = None
    
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        user_data = user_manager.validate_session(token)
        if user_data:
            user_id = user_data.get('user_id')
            user_email = user_data.get('email')
    
    # Fallback: get email from request body
    if not user_email:
        user_email = data.get('email')
        print(f"[AUTH-DEBUG] Fallback email from body: {user_email}")
    
    query = data.get('query')  # Now uses same 'data' variable

    if not query:
        raise HTTPException(status_code=400, detail="Query required")
    
    # Get user's tier from DB
    if user_email:
        tier = get_user_tier_by_email(user_email)
        
        # Check tier limits (daily for seeker, monthly for paid)
        queries_today = get_queries_today(user_email)
        allowed, message = check_tier_limits(user_email, queries_today)
        
        if not allowed:
            raise HTTPException(status_code=429, detail=message)
    
    # Generate consensus - âœ… FIXED: Using V4 (concurrent async)
    selected_agents = data.get('agents', ['openai', 'claude', 'gemini', 'mistral', 'cohere'])
    
    # Ensure tier is set even if user_email is None
    if not user_email:
        tier = {'tier_name': 'seeker', 'max_tokens': 500}
    
    # Generate consensus with tier-aware processing (v5.0.0)
    result = await generate_expert_panel_response_v4(
        query=query,
        providers=selected_agents,
        tier=tier.get('tier_name', 'seeker')  # v5.0.0 - Pass tier for tier-aware processing
    )
    result_dict = result.model_dump()
    # Convert Pydantic to dict - ADD THIS LINE AFTER THE FUNCTION CALL
    result = result.model_dump() if hasattr(result, 'model_dump') else result


    # DEFENSIVE: Handle None or invalid result
    if result is None:
        print(f"[CRITICAL] Consensus engine returned None")
        raise HTTPException(status_code=500, detail="Consensus engine failure - returned None")

    if not isinstance(result, dict):
        print(f"[CRITICAL] Consensus returned non-dict: {type(result)}")
        raise HTTPException(status_code=500, detail="Invalid consensus response type")
    
    # =====================================================================
    # CHAMPION SUPPRESSION: Hide when consensus is weak (< 60%)
    # Must run BEFORE email send so email reflects suppression
    # =====================================================================
    consensus_data = result.get('consensus', {})
    convergence_pct = consensus_data.get('convergence_percentage', 0)
    confidence_level = consensus_data.get('consensus_confidence', 'LOW')
    
    if confidence_level in ('LOW', 'CONTESTED') or convergence_pct < 60:
        # Suppress champion - insufficient agreement to identify reliable champion
        # Mutate result directly so email receives suppressed data
        result['consensus'] = dict(consensus_data)
        result['consensus']['champion'] = None
        result['consensus']['champion_score'] = None
        result['consensus']['champion_suppressed'] = True
        result['consensus']['champion_suppressed_reason'] = "Insufficient agreement to identify reliable champion"
        print(f"[CONSENSUS] Champion suppressed: confidence={confidence_level}, convergence={convergence_pct}%")
    
    # Send email if user is authenticated
    email_status = {'sent': False, 'error': None}

    # NOTE: tier was already set above (line 856 or fallback)
    try:
        notifier = get_email_notifier()
        notifier.send_formatted_result(
            user_email=user_email,
            query=query,
            result=result,
            tier_name=tier.get('tier_name', 'seeker')
        )
        email_status['sent'] = True
        print(f"[AUTH] Email sent successfully to {user_email}")
    except Exception as e:
        email_status['error'] = str(e)
        print(f"[AUTH] Email send failed: {str(e)}")
    
    # Extract consensus data
    responses_list = result.get('responses', [])
    participating_agents = [
        r.get('provider', r.get('agent', 'Unknown'))
        for r in responses_list
    ]
        
    # Handle consensus_panel - extract from consensus.consensus_panel
    consensus_panel_data = result.get('consensus', {}).get('consensus_panel', '')
    if isinstance(consensus_panel_data, dict):
        consensus_panel_html = consensus_panel_data.get('html', str(consensus_panel_data))
    else:
        consensus_panel_html = str(consensus_panel_data)
    
    # =====================================================================
    # OPTION C v5.0.0: Seeker Hard Cutoff - Synthesis Only
    # =====================================================================
    tier_name = tier.get('tier_name', 'seeker').lower()
    
    if tier_name == 'seeker':
        # SEEKER: Synthesis only - hard cutoff
        return {
            'status': 'success',
            'message': 'Query processed! Results emailed to you.',
            'email': user_email,
            'tier': tier_name,
            'correlation_id': result.get('correlation_id', 'unknown'),
            'email_notification': email_status,
            'consensus': {
                'consensus_panel': consensus_panel_html,
                'reached': result.get('consensus', {}).get('reached', False),
                'convergence_count': result.get('consensus', {}).get('convergence_count', 0),
                'convergence_percentage': result.get('consensus', {}).get('convergence_percentage', 0),
                'consensus_confidence': result.get('consensus', {}).get('consensus_confidence', 'LOW'),
            },
            'consensus_panel': consensus_panel_html,
            'agent_count': len(participating_agents),
            'responses': [],
            'participating_agents': [],
            'divergence': {},
            'upgrade_cta': {
                'message': 'Want to see what each AI said? Upgrade to Acolyte for full transparency.',
                'url': 'https://seekrates-ai.com/pricing/'
            }
        }
    
    # ACOLYTE / ORACLE / SAGE: Full transparency
    return {
        'status': 'success',
        'message': 'Query processed! Results emailed to you.',
        'email': user_email,
        'tier': tier_name,
        'correlation_id': result.get('correlation_id', 'unknown'),
        'email_notification': email_status,
        'consensus': result.get('consensus', {}),  # Already has suppressed champion if applicable
        'consensus_panel': consensus_panel_html,
        'participating_agents': participating_agents,
        'agent_count': len(participating_agents),
        'responses': responses_list,
        'divergence': result.get('divergence', {
            'common_themes': [],
            'outliers': [],
            'personality_quotes': {},
            'article_hook': '',
            'theme_coverage': {}
        }),
        'risk_analysis': result.get('risk_analysis')
    }