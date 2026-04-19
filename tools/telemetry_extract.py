# FILE: seekrates_engine_production/tools/telemetry_extract.py
# ACTION: CREATE (new file)
# VERSION: 1.0.0

# created: 2026-04-14
# authority: INDRA-212
# purpose: One-shot telemetry extraction — per-provider response timing data
# scope_fence: tools/telemetry_extract.py only

import sqlite3
import os
import csv
import io
import datetime
from typing import List, Dict


RESEARCH_DB = "/app/.database/research.db"
TELEMETRY_DB = "/app/.database/telemetry.db"


def probe_schema(conn: sqlite3.Connection, db_label: str) -> List[str]:
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        print(f"[TELEMETRY-EXTRACT] {db_label} tables: {tables}")
        return tables
    except sqlite3.Error as e:
        print(f"[TELEMETRY-EXTRACT] {db_label} schema probe error: {e}")
        return []


def map_row(row: sqlite3.Row, columns: List[str]) -> Dict[str, str]:
    col_lower = [c.lower() for c in columns]

    def find(candidates: List[str]) -> str:
        for candidate in candidates:
            if candidate in col_lower:
                val = row[col_lower.index(candidate)]
                return str(val) if val is not None else ""
        return ""

    champion_raw = find(["champion", "is_champion", "winner"])
    if champion_raw.lower() in ("1", "true", "yes"):
        champion = "y"
    elif champion_raw.lower() in ("0", "false", "no"):
        champion = "n"
    else:
        champion = champion_raw

    return {
        "provider_name": find(["provider", "provider_name"]),
        "response_time": find(["response_time", "duration", "elapsed"]),
        "query_timestamp": find(["created_at", "timestamp", "queried_at"]),
        "confidence": find(["confidence", "score"]),
        "champion": champion,
    }


def extract_from_table(
    conn: sqlite3.Connection,
    table: str,
    db_label: str,
) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    try:
        cursor = conn.execute(f"SELECT * FROM {table} LIMIT 200")
        columns = [desc[0] for desc in cursor.description]
        for row in cursor.fetchall():
            rows.append(map_row(row, columns))
    except sqlite3.Error as e:
        print(f"[TELEMETRY-EXTRACT] {db_label} query error on {table}: {e}")
    return rows


def extract_research_db() -> List[Dict[str, str]]:
    if not os.path.exists(RESEARCH_DB):
        print("[TELEMETRY-EXTRACT] research.db NOT FOUND — no Volume mounted or path absent")
        return []
    try:
        conn = sqlite3.connect(RESEARCH_DB)
        tables = probe_schema(conn, "research.db")
        if not tables:
            print("[TELEMETRY-EXTRACT] research.db EXISTS but contains no tables")
            conn.close()
            return []
        candidates = [
            t for t in tables
            if any(k in t.lower() for k in ["response", "timing", "provider", "consensus"])
        ]
        if not candidates:
            print(f"[TELEMETRY-EXTRACT] research.db: no timing/provider tables found in {tables}")
            conn.close()
            return []
        rows: List[Dict[str, str]] = []
        for table in candidates:
            rows.extend(extract_from_table(conn, table, "research.db"))
        conn.close()
        return rows
    except sqlite3.Error as e:
        print(f"[TELEMETRY-EXTRACT] research.db connection error: {e}")
        return []


def extract_telemetry_db() -> List[Dict[str, str]]:
    if not os.path.exists(TELEMETRY_DB):
        print("[TELEMETRY-EXTRACT] telemetry.db NOT FOUND")
        return []
    try:
        conn = sqlite3.connect(TELEMETRY_DB)
        tables = probe_schema(conn, "telemetry.db")
        if not tables:
            print("[TELEMETRY-EXTRACT] telemetry.db EXISTS but contains no tables")
            conn.close()
            return []
        rows: List[Dict[str, str]] = []
        # Priority: consensus_results first per INDRA-212
        priority = [t for t in tables if t == "consensus_results"]
        others = [
            t for t in tables
            if t != "consensus_results"
            and any(k in t.lower() for k in ["response", "timing", "provider", "consensus"])
        ]
        for table in priority + others:
            rows.extend(extract_from_table(conn, table, "telemetry.db"))
        conn.close()
        return rows
    except sqlite3.Error as e:
        print(f"[TELEMETRY-EXTRACT] telemetry.db connection error: {e}")
        return []


def print_csv(rows: List[Dict[str, str]], source_label: str) -> None:
    if not rows:
        print(f"[TELEMETRY-EXTRACT] {source_label}: 0 rows extracted")
        return
    fieldnames = ["provider_name", "response_time", "query_timestamp", "confidence", "champion"]
    print(f"[TELEMETRY-EXTRACT] {source_label}: printing {len(rows)} rows")
    print(f"# SOURCE: {source_label}")
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    for line in buffer.getvalue().splitlines():
        print(f"[CSV] {line}")


def main() -> None:
    print("[TELEMETRY-EXTRACT] Starting — INDRA-212/213")
    print(f"[TELEMETRY-EXTRACT] Run timestamp: {datetime.datetime.utcnow().isoformat()}")

    research_rows = extract_research_db()
    telemetry_rows = extract_telemetry_db()

    print_csv(research_rows, "research.db")
    print_csv(telemetry_rows, "telemetry.db")

    total = len(research_rows) + len(telemetry_rows)
    print(f"[TELEMETRY-EXTRACT] COMPLETE — total rows: {total}")
    print("[TELEMETRY-EXTRACT] Restore startCommand to: python3 src/server/main.py")


if __name__ == "__main__":
    main()
