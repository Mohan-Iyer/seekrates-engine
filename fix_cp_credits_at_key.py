#!/usr/bin/env python3
"""
fix_cp_credits_at_key.py — One-shot AT key fix. Railway Custom Start Command use only.
Authority: INDRA-203-REISSUE / BUG-37-TIER-01.
Targets AT test key pXW5jAqCPNhJrcnSk2 specifically.
Creates cp_credits table if not exists, then upserts tier=gold, credits_limit=60.
"""
import sqlite3
from datetime import datetime, timezone

DB_PATH       = '/app/.database/telemetry.db'
AT_API_KEY    = 'pXW5jAqCPNhJrcnSk2'
BILLING_CYCLE = datetime.now(timezone.utc).strftime('%Y-%m')

print(f"[FIX-AT-KEY] Starting. target=***{AT_API_KEY[-6:]}, cycle={BILLING_CYCLE}", flush=True)

try:
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cp_credits (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            api_key        TEXT NOT NULL,
            billing_cycle  TEXT NOT NULL,
            tier           TEXT NOT NULL,
            credits_limit  INTEGER NOT NULL,
            credits_used   INTEGER NOT NULL DEFAULT 0,
            created_at     TEXT DEFAULT (datetime('now')),
            updated_at     TEXT DEFAULT (datetime('now')),
            UNIQUE(api_key, billing_cycle)
        )
    """)
    conn.commit()
    print("[FIX-AT-KEY] Table confirmed.", flush=True)

    cursor.execute("""
        INSERT INTO cp_credits (api_key, billing_cycle, tier, credits_limit, credits_used)
        VALUES (?, ?, 'gold', 60, 0)
        ON CONFLICT(api_key, billing_cycle) DO UPDATE SET
            tier          = 'gold',
            credits_limit = 60,
            updated_at    = datetime('now')
    """, (AT_API_KEY, BILLING_CYCLE))
    conn.commit()
    print("[FIX-AT-KEY] UPSERT complete.", flush=True)

    cursor.execute("""
        SELECT api_key, billing_cycle, tier, credits_limit, credits_used
        FROM cp_credits
        WHERE api_key = ? AND billing_cycle = ?
    """, (AT_API_KEY, BILLING_CYCLE))
    row = cursor.fetchone()
    conn.close()

    if row:
        print(f"[FIX-AT-KEY] CONFIRMED: api_key=***{row[0][-6:]}, cycle={row[1]}, "
              f"tier={row[2]}, limit={row[3]}, used={row[4]}", flush=True)
    else:
        print("[FIX-AT-KEY] ERROR: Row not found after upsert.", flush=True)
        exit(1)

except Exception as e:
    print(f"[FIX-AT-KEY] ERROR: {e}", flush=True)
    exit(1)

print("[FIX-AT-KEY] Done. Restore startCommand to: python3 src/server/main.py", flush=True)