#!/usr/bin/env python3
# =============================================================================
# SCRIPT DNA METADATA - GPS FOUNDATION COMPLIANT
# =============================================================================
# created: 2026-04-16
# authority: INDRA-227-REISSUE
# purpose: One-shot cp_credits tier reset — AT test key + 3 pentagon keys
# scope_fence: tools/fix_cp_credits_multi_2026_04.py only
# =============================================================================
# CHANGE LOG:
# v1.1.0 - 2026-04-16: INDRA-227-REISSUE — real keys hardcoded (no placeholders).
#   OP-2 consensus-press-ai.com, OP-3 shiftlog-ai.com, OP-4 proseweaver.com.
#   WRITE log line added to execute_op() per mandatory output pattern.
#   Labels updated to site names.
# v1.0.0 - 2026-04-16: INDRA-227 — initial. Placeholders for pentagon keys.
# =============================================================================

import sqlite3
import datetime
from dataclasses import dataclass

DB_PATH = "/app/.database/telemetry.db"
BILLING_CYCLE = "2026-04"
PREFIX = "[FIX-MULTI]"


@dataclass
class CpCreditOp:
    api_key: str
    billing_cycle: str
    tier: str
    credits_limit: int
    credits_used: int
    action: str   # "UPDATE" | "INSERT_OR_REPLACE"
    label: str


OPERATIONS: list[CpCreditOp] = [
    CpCreditOp(
        api_key="pXW5jAqCPNhJrcnSk2",
        billing_cycle=BILLING_CYCLE,
        tier="gold",
        credits_limit=60,
        credits_used=0,
        action="UPDATE",
        label="OP-1 AT-TEST-KEY",
    ),
    CpCreditOp(
        api_key="cPAI7mXqRvNs3kLwYu",
        billing_cycle=BILLING_CYCLE,
        tier="gold",
        credits_limit=60,
        credits_used=0,
        action="INSERT_OR_REPLACE",
        label="OP-2 consensus-press-ai.com",
    ),
    CpCreditOp(
        api_key="sLfT9bQzHnWe4jMxKp",
        billing_cycle=BILLING_CYCLE,
        tier="gold",
        credits_limit=60,
        credits_used=0,
        action="INSERT_OR_REPLACE",
        label="OP-3 shiftlog-ai.com",
    ),
    CpCreditOp(
        api_key="pWvR2nJcDsYt6kBmXq",
        billing_cycle=BILLING_CYCLE,
        tier="gold",
        credits_limit=60,
        credits_used=0,
        action="INSERT_OR_REPLACE",
        label="OP-4 proseweaver.com",
    ),
]


def print_before(conn: sqlite3.Connection, op: CpCreditOp) -> None:
    try:
        cursor = conn.execute(
            "SELECT api_key, billing_cycle, tier, credits_limit, credits_used "
            "FROM cp_credits WHERE api_key = ? AND billing_cycle = ?",
            (op.api_key, op.billing_cycle),
        )
        row = cursor.fetchone()
        if row:
            print(f"{PREFIX} BEFORE [{op.label}]: "
                  f"tier={row[2]}, credits_limit={row[3]}, credits_used={row[4]}")
        else:
            print(f"{PREFIX} BEFORE [{op.label}]: NO ROW EXISTS")
    except sqlite3.Error as e:
        print(f"{PREFIX} BEFORE [{op.label}]: READ ERROR — {e}")


def execute_op(conn: sqlite3.Connection, op: CpCreditOp) -> None:
    updated_at = datetime.datetime.utcnow().isoformat()
    print(f"{PREFIX} WRITE [{op.label}]: "
          f"tier={op.tier}, credits_limit={op.credits_limit}, "
          f"credits_used={op.credits_used}, billing_cycle={op.billing_cycle}")
    try:
        if op.action == "UPDATE":
            conn.execute(
                "UPDATE cp_credits "
                "SET tier=?, credits_limit=?, credits_used=?, updated_at=? "
                "WHERE api_key=? AND billing_cycle=?",
                (op.tier, op.credits_limit, op.credits_used,
                 updated_at, op.api_key, op.billing_cycle),
            )
        elif op.action == "INSERT_OR_REPLACE":
            conn.execute(
                "INSERT OR REPLACE INTO cp_credits "
                "(api_key, billing_cycle, tier, credits_limit, credits_used, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (op.api_key, op.billing_cycle, op.tier,
                 op.credits_limit, op.credits_used, updated_at),
            )
    except sqlite3.Error as e:
        print(f"{PREFIX} EXECUTE ERROR [{op.label}]: {e}")


def verify_op(conn: sqlite3.Connection, op: CpCreditOp) -> bool:
    try:
        cursor = conn.execute(
            "SELECT api_key, billing_cycle, tier, credits_limit, credits_used "
            "FROM cp_credits WHERE api_key = ? AND billing_cycle = ?",
            (op.api_key, op.billing_cycle),
        )
        row = cursor.fetchone()
        if row and row[2] == op.tier and row[3] == op.credits_limit:
            print(f"{PREFIX} CONFIRMED [{op.label}]: "
                  f"tier={row[2]}, credits_limit={row[3]}, credits_used={row[4]}")
            return True
        else:
            print(f"{PREFIX} FAILED [{op.label}]: "
                  f"expected tier={op.tier} credits_limit={op.credits_limit}, "
                  f"got {row}")
            return False
    except sqlite3.Error as e:
        print(f"{PREFIX} VERIFY ERROR [{op.label}]: {e}")
        return False


def main() -> None:
    print(f"{PREFIX} Starting — INDRA-227-REISSUE")
    print(f"{PREFIX} Run timestamp: {datetime.datetime.utcnow().isoformat()}")
    print(f"{PREFIX} DB: {DB_PATH}")
    print(f"{PREFIX} Billing cycle: {BILLING_CYCLE}")

    confirmed_count: int = 0

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.isolation_level = None  # autocommit

        for op in OPERATIONS:
            print_before(conn, op)
            execute_op(conn, op)
            if verify_op(conn, op):
                confirmed_count += 1

        conn.close()

    except sqlite3.Error as e:
        print(f"{PREFIX} DB CONNECTION ERROR: {e}")

    print(f"{PREFIX} COMPLETE — {confirmed_count}/{len(OPERATIONS)} rows confirmed gold")
    if confirmed_count < len(OPERATIONS):
        print(f"{PREFIX} WARNING — "
              f"{len(OPERATIONS) - confirmed_count} rows NOT confirmed — "
              f"do not restore until INDRA reviews logs")
    print("Restore startCommand to: python3 src/server/main.py")


if __name__ == "__main__":
    main()
