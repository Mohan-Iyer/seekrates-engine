# diag_cp_credits.py
# ONE-SHOT DIAGNOSTIC — delete after use
# Purpose: Dump cp_credits table for billing_cycle 2026-04
# Authority: INDRA-209 / TASK 1
# DB: SQLite — /app/.database/telemetry.db

import sqlite3

DB_PATH = "/app/.database/telemetry.db"

conn = sqlite3.connect(DB_PATH)
cur  = conn.cursor()

# Confirm table exists
cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cur.fetchall()
print(f"[DIAG-CP-CREDITS] Tables: {tables}", flush=True)

# Dump ALL cp_credits rows for 2026-04
try:
    cur.execute(
        "SELECT api_key, billing_cycle, tier, credits_limit, credits_used "
        "FROM cp_credits WHERE billing_cycle='2026-04';"
    )
    rows = cur.fetchall()
    print(f"[DIAG-CP-CREDITS] Rows: {rows}", flush=True)
except Exception as e:
    print(f"[DIAG-CP-CREDITS] ERROR: {e}", flush=True)

conn.close()
print("[DIAG-CP-CREDITS] Done. Restore startCommand to: python3 src/server/main.py", flush=True)