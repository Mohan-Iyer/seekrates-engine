# fix_operator_tier.py
# ONE-TIME USE — delete after confirmed in Railway logs
# Sets operator API key to tier=gold, credits_limit=60 in telemetry.db

# fix_operator_tier.py — ONE-TIME USE — delete after confirmed
import sqlite3
import os

db_path = '/app/.database/telemetry.db'

print(f"[FIX-TIER] Connecting to: {db_path}")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Create table if not exists — matches cp_billing.py schema
cursor.execute("""
    CREATE TABLE IF NOT EXISTS cp_credits (
        api_key TEXT NOT NULL,
        cycle TEXT NOT NULL,
        tier TEXT NOT NULL DEFAULT 'free',
        credits_used INTEGER NOT NULL DEFAULT 0,
        credits_limit INTEGER NOT NULL DEFAULT 3,
        PRIMARY KEY (api_key, cycle)
    )
""")
conn.commit()
print("[FIX-TIER] Table cp_credits confirmed.")

# Get operator API key from env
api_key = os.environ.get('CONSENSUSPRESS_API_KEY', '')
if not api_key:
    print("[FIX-TIER] ERROR: CONSENSUSPRESS_API_KEY not set in env")
    conn.close()
    exit(1)

cycle = '2026-04'
print(f"[FIX-TIER] api_key=***{api_key[-6:]}, cycle={cycle}")

# Upsert — insert or update to gold
cursor.execute("""
    INSERT INTO cp_credits (api_key, cycle, tier, credits_used, credits_limit)
    VALUES (?, ?, 'gold', 0, 60)
    ON CONFLICT(api_key, cycle) DO UPDATE SET
        tier='gold',
        credits_limit=60
""", (api_key, cycle))
conn.commit()

# Verify
cursor.execute(
    "SELECT api_key, tier, credits_limit, credits_used FROM cp_credits WHERE api_key=?",
    (api_key,)
)
rows = cursor.fetchall()
print(f"[FIX-TIER] Result: {rows}")
print("[FIX-TIER] COMPLETE — tier=gold, credits_limit=60 confirmed.")
conn.close()