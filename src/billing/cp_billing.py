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
# defines_functions: "ensure_cp_credits_table, get_cp_tier_for_api_key,
#   check_cp_credits, increment_credits_used, upsert_cp_credits_on_webhook"
# =============================================================================
# DEPENDENCIES:
# =============================================================================
# =============================================================================
# FIELD CONTRACTS:
# =============================================================================
#   input_sources:
#     - path: "src/api/consensuspress_endpoints.py"
#       type: "function_call"
#     - path: "src/billing/stripe_integration.py"
#       type: "function_call — webhook handlers"
#   output_destinations:
#     - path: ".database/telemetry.db — cp_credits table"
#       type: "SQLite"
# =============================================================================
# CHANGE LOG:
# =============================================================================
# v1.1.0 - 2026-04-19: CCI-SE-235-01 (INDRA-235) — FLAG-226-01 close-out.
#   check_cp_credits() return signature expanded from Tuple[bool,int,str]
#   to Tuple[bool,int,int,int,str]. Adds credits_used and credits_limit
#   to return value for plugin display cache. All three existing return
#   statements updated. Caller (consensuspress_endpoints.py) must unpack
#   5-tuple. Additive only — no behaviour change.
# v1.0.2 - 2026-04-13: BLOCKER-38-CREDITS-02 — operator key seed embed.
#   INSERT OR REPLACE into cp_credits for billing_cycle=2026-04, tier=gold.
#   CONFIRMED in Railway logs. Embed removed. Clean version.
# v1.0.1 - 2026-04-12: CCI-SE-203 (INDRA-203) — BUG-37-TIER-01 fix.
#   DB_PATH resolved via __file__ traversal — guaranteed on Railway regardless of cwd.
#   ensure_cp_credits_table() uses os.path.dirname(DB_PATH) for makedirs.
#   Print statements added for Railway log visibility at startup.
# v1.0.0 - 2026-04-10: CCI-SE-198 (INDRA-198) — Initial creation.
#   cp_credits table. Per-cycle enforcement. Webhook tier sync.
#   Option A: api_key = CONSENSUSPRESS_API_KEY env var (single shared key).
#   Authority: INDRA-198 SE-189B-02, SE-189B-03, SE-189B-04.
# === END OF SCRIPT DNA HEADER ====================================

import os
import sqlite3
import logging
from datetime import datetime, timezone
from typing import Tuple

logger = logging.getLogger(__name__)

_BILLING_DIR = os.path.dirname(os.path.abspath(__file__))  # src/billing/
_SRC_DIR = os.path.dirname(_BILLING_DIR)                    # src/
_PROJECT_ROOT = os.path.dirname(_SRC_DIR)                   # project root
DB_PATH = os.path.join(_PROJECT_ROOT, '.database', 'telemetry.db')

# =============================================================================
# CP TIER CONFIGURATION
# Separate namespace from SE TIER_CONFIG — CP tiers are free/silver/gold.
# SE tiers (seeker/acolyte/oracle/sage) are unchanged.
# Authority: INDRA-198 Section 3, D-36-TIER-NAMES-01.
# =============================================================================
CP_TIER_CONFIG = {
    'free':   {'credits_limit': 3},
    'silver': {'credits_limit': 15},
    'gold':   {'credits_limit': 60},
}

# CP Price ID → tier name mapping.
# Config-driven — Railway env vars. Not hardcoded inline (INDRA-198 Section 5).
def _get_cp_price_tier_map() -> dict:  # HAL-001-DEFERRED
    """Build CP price_id → tier_name map from Railway env vars at call time."""
    mapping = {}
    silver_price = os.getenv('STRIPE_PRICE_CP_SILVER', '')
    gold_price = os.getenv('STRIPE_PRICE_CP_GOLD', '')
    if silver_price:
        mapping[silver_price] = 'silver'
    if gold_price:
        mapping[gold_price] = 'gold'
    return mapping


# =============================================================================
# TABLE INITIALISATION
# =============================================================================

def ensure_cp_credits_table() -> None:
    """
    CREATE TABLE IF NOT EXISTS cp_credits per INDRA-198 schema.
    Called on module load. Idempotent. Safe on Railway — fails open on error.
    Schema: UNIQUE(api_key, billing_cycle) — one row per key per YYYY-MM.
    """
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cp_credits (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                api_key         TEXT NOT NULL,
                billing_cycle   TEXT NOT NULL,
                tier            TEXT NOT NULL,
                credits_limit   INTEGER NOT NULL,
                credits_used    INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now')),
                UNIQUE(api_key, billing_cycle)
            )
        """)
        conn.commit()
        conn.close()
        logger.info("[CP-BILLING] cp_credits table ensured")
        print(f"[CP-BILLING] cp_credits table ensured at {DB_PATH}", flush=True)
    except Exception as e:
        logger.error(f"[CP-BILLING] Error ensuring cp_credits table: {e}")
        print(f"[CP-BILLING] ERROR ensuring cp_credits table: {e}", flush=True)


# Run on module load — idempotent
ensure_cp_credits_table()

# =============================================================================
# TIER LOOKUP
# =============================================================================

def get_cp_tier_for_api_key(api_key: str) -> str:
    """
    Determine CP tier for the given api_key.
    Option A (INDRA-198): api_key = CONSENSUSPRESS_API_KEY env var (single shared key).
    Looks up most recent cp_credits row for this api_key to get current tier.
    Falls back to 'free' if no row exists or on any error.

    Args:
        api_key: The CONSENSUSPRESS_API_KEY value from the request.

    Returns:
        str: 'free' | 'silver' | 'gold'
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        # Get the most recently updated row for this api_key across all cycles
        cursor.execute("""
            SELECT tier FROM cp_credits
            WHERE api_key = ?
            ORDER BY updated_at DESC
            LIMIT 1
        """, (api_key,))
        row = cursor.fetchone()
        conn.close()
        if row and row[0] in CP_TIER_CONFIG:
            return row[0]
        return 'free'
    except Exception as e:
        logger.error(f"[CP-BILLING] Error looking up tier for api_key: {e}")
        return 'free'


# =============================================================================
# CREDIT ENFORCEMENT
# =============================================================================

def check_cp_credits(api_key: str) -> Tuple[bool, int, int, int, str]:
    """
    Enforce credit limit for current billing cycle (YYYY-MM UTC).
    Inserts a row if none exists for this api_key + billing_cycle.
    Does NOT increment credits_used — caller must call increment_credits_used()
    after successful consensus response only.

    Args:
        api_key: The CONSENSUSPRESS_API_KEY env var value.

    Returns:
        Tuple[allowed: bool, credits_remaining: int, credits_used: int, credits_limit: int, tier: str]
        allowed=False → caller raises HTTP 402.
        credits_remaining is pre-decrement (caller subtracts 1 on success).
        credits_used and credits_limit reflect row state at check time
        (pre-increment). Plugin display cache uses these for progress UI.
        FLAG-226-01 close-out (CCI-SE-235-01).
    """
    billing_cycle = datetime.now(timezone.utc).strftime('%Y-%m')
    tier = 'free'
    credits_limit = CP_TIER_CONFIG['free']['credits_limit']
    credits_used = 0

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Fetch existing row for this api_key + billing_cycle
        cursor.execute("""
            SELECT tier, credits_limit, credits_used
            FROM cp_credits
            WHERE api_key = ? AND billing_cycle = ?
        """, (api_key, billing_cycle))
        row = cursor.fetchone()

        if row is None:
            # No row for this cycle — determine tier from most recent row
            tier = get_cp_tier_for_api_key(api_key)
            credits_limit = CP_TIER_CONFIG.get(tier, CP_TIER_CONFIG['free'])['credits_limit']
            credits_used = 0
            # Insert new cycle row
            cursor.execute("""
                INSERT INTO cp_credits
                    (api_key, billing_cycle, tier, credits_limit, credits_used)
                VALUES (?, ?, ?, ?, 0)
                ON CONFLICT(api_key, billing_cycle) DO NOTHING
            """, (api_key, billing_cycle, tier, credits_limit))
            conn.commit()
        else:
            tier = row[0] if row[0] in CP_TIER_CONFIG else 'free'
            credits_limit = row[1]
            credits_used = row[2]

        conn.close()

        if credits_used >= credits_limit:
            logger.info(
                f"[CP-BILLING] Credit limit reached: api_key=***{api_key[-6:]}, "
                f"cycle={billing_cycle}, tier={tier}, "
                f"used={credits_used}/{credits_limit}"
            )
            return False, 0, credits_used, credits_limit, tier

        credits_remaining = credits_limit - credits_used
        logger.info(
            f"[CP-BILLING] Credit check passed: cycle={billing_cycle}, tier={tier}, "
            f"used={credits_used}/{credits_limit}, remaining={credits_remaining}"
        )
        return True, credits_remaining, credits_used, credits_limit, tier

    except Exception as e:
        logger.error(f"[CP-BILLING] Error in check_cp_credits: {e}")
        # Fail open — do not block consensus on DB error
        return True, 999, 0, 999, 'free'


def increment_credits_used(api_key: str) -> None:
    """
    Increment credits_used + 1 for api_key + current billing cycle.
    Called ONLY after successful consensus response.
    Fails silently — increment failure must not block the response already sent.

    Args:
        api_key: The CONSENSUSPRESS_API_KEY env var value.
    """
    billing_cycle = datetime.now(timezone.utc).strftime('%Y-%m')
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE cp_credits
            SET credits_used = credits_used + 1,
                updated_at = datetime('now')
            WHERE api_key = ? AND billing_cycle = ?
        """, (api_key, billing_cycle))
        conn.commit()
        conn.close()
        logger.info(
            f"[CP-BILLING] Incremented credits_used: api_key=***{api_key[-6:]}, "
            f"cycle={billing_cycle}"
        )
    except Exception as e:
        logger.error(f"[CP-BILLING] Error incrementing credits_used: {e}")


# =============================================================================
# WEBHOOK TIER SYNC
# =============================================================================

def upsert_cp_credits_on_webhook(api_key: str, new_tier: str) -> None:
    """
    On Stripe webhook subscription event: UPSERT cp_credits for current
    billing_cycle. Sets tier + credits_limit. Does NOT reset credits_used
    mid-cycle — carry forward per INDRA-198 Section 5 change_4.

    On cancellation/deletion: new_tier='free', credits_limit=3.

    Args:
        api_key:  The CONSENSUSPRESS_API_KEY env var value (Option A).
        new_tier: 'free' | 'silver' | 'gold'
    """
    if new_tier not in CP_TIER_CONFIG:
        logger.warning(
            f"[CP-BILLING] upsert_cp_credits_on_webhook: unknown tier '{new_tier}' "
            f"— defaulting to 'free'"
        )
        new_tier = 'free'

    billing_cycle = datetime.now(timezone.utc).strftime('%Y-%m')
    credits_limit = CP_TIER_CONFIG[new_tier]['credits_limit']

    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO cp_credits
                (api_key, billing_cycle, tier, credits_limit, credits_used)
            VALUES (?, ?, ?, ?, 0)
            ON CONFLICT(api_key, billing_cycle) DO UPDATE SET
                tier          = excluded.tier,
                credits_limit = excluded.credits_limit,
                updated_at    = datetime('now')
        """, (api_key, billing_cycle, new_tier, credits_limit))
        conn.commit()
        conn.close()
        logger.info(
            f"[CP-BILLING] Webhook upsert: api_key=***{api_key[-6:]}, "
            f"cycle={billing_cycle}, tier={new_tier}, limit={credits_limit}"
        )
    except Exception as e:
        logger.error(f"[CP-BILLING] Error in upsert_cp_credits_on_webhook: {e}")


def resolve_cp_tier_from_price_id(price_id: str) -> str:
    """
    Map Stripe price_id to CP tier name.
    Config-driven from Railway env vars (INDRA-198 — not hardcoded inline).
    Falls back to 'free' for unknown / deleted / cancelled price_id.

    Args:
        price_id: Stripe price ID from webhook event.

    Returns:
        str: 'free' | 'silver' | 'gold'
    """
    if not price_id:
        return 'free'
    mapping = _get_cp_price_tier_map()
    return mapping.get(price_id, 'free')
