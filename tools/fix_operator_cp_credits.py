# fix_operator_cp_credits.py
# ONE-SHOT — delete after use
# Purpose: Seed operator key cp_credits row — tier=gold, limit=60
# Pattern: railway.json startCommand swap
# Session: 41 — BLOCKER-208-01

import sqlite3
import os

DB_PATH = "/app/.database/telemetry.db"
CYCLE   = "2026-04"

OP_KEY = os.environ.get("CONSENSUSPRESS_API_KEY", "NOT_SET")
print(f"[FIX-OP-CREDITS] Operator key suffix=***{OP_KEY[-6:]}", flush=True)

conn = sqlite3.connect(DB_PATH)
cur  = conn.cursor()

# BEFORE
cur.execute(
    "SELECT api_key, billing_cycle, tier, credits_limit, credits_used "
    "FROM cp_credits WHERE billing_cycle=?", (CYCLE,)
)
print(f"[FIX-OP-CREDITS] BEFORE: {cur.fetchall()}", flush=True)

# UPSERT
cur.execute(
    "INSERT OR REPLACE INTO cp_credits "
    "(api_key, billing_cycle, tier, credits_limit, credits_used, updated_at) "
    "VALUES (?, ?, 'gold', 60, 0, datetime('now'))",
    (OP_KEY, CYCLE)
)
conn.commit()

# AFTER
cur.execute(
    "SELECT api_key, billing_cycle, tier, credits_limit, credits_used "
    "FROM cp_credits WHERE billing_cycle=?", (CYCLE,)
)
print(f"[FIX-OP-CREDITS] CONFIRMED: {cur.fetchall()}", flush=True)
conn.close()
print("[FIX-OP-CREDITS] COMPLETE", flush=True)
print("Restore startCommand to: python3 src/server/main.py", flush=True)