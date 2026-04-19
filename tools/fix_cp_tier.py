#!/usr/bin/env python3
"""
fix_cp_tier.py — One-shot seeding script. Railway Custom Start Command use only.
Authority: INDRA-203 / BUG-37-TIER-01.
Seeds cp_credits with tier=gold, credits_limit=60 for current billing cycle.
Restores Custom Start Command to uvicorn after execution.
"""
import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = '/app/.database/telemetry.db'
API_KEY = os.environ.get('CONSENSUSPRESS_API_KEY', '')
BILLING_CYCLE = datetime.now(timezone.utc).strftime('%Y-%m')

print(f"[FIX-CP-TIER] Starting. api_key=***{API_KEY[-6:]}, cycle={BILLING_CYCLE}", flush=True)

if not API_KEY:
    print("[FIX-CP-TIER] ERROR: CONSENSUSPRESS_API_KEY not set. Aborting.", flush=True)
    exit(1)

try:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO cp_credits (api_key, billing_cycle, tier, credits_limit, credits_used)
        VALUES (?, ?, 'gold', 60, 0)
        ON CONFLICT(api_key, billing_cycle) DO UPDATE SET
            tier          = 'gold',
            credits_limit = 60,
            updated_at    = datetime('now')
    """, (API_KEY, BILLING_CYCLE))
    conn.commit()
    print("[FIX-CP-TIER] UPSERT complete.", flush=True)

    cursor.execute("""
        SELECT api_key, billing_cycle, tier, credits_limit, credits_used
        FROM cp_credits
        WHERE api_key = ? AND billing_cycle = ?
    """, (API_KEY, BILLING_CYCLE))
    row = cursor.fetchone()
    conn.close()

    if row:
        print(f"[FIX-CP-TIER] CONFIRMED: api_key=***{row[0][-6:]}, cycle={row[1]}, "
              f"tier={row[2]}, limit={row[3]}, used={row[4]}", flush=True)
    else:
        print("[FIX-CP-TIER] ERROR: Row not found after upsert.", flush=True)

except Exception as e:
    print(f"[FIX-CP-TIER] ERROR: {e}", flush=True)
    exit(1)

print("[FIX-CP-TIER] Done. Restore Custom Start Command to uvicorn now.", flush=True)
