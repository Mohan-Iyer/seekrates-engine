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
# defines_functions: "ensure_research_db, archive_consensus_result"
# =============================================================================
# DEPENDENCIES:
# =============================================================================
# =============================================================================
# FIELD CONTRACTS:
# =============================================================================
#   input_sources:
#     - path: "src/agents/consensus_contract.py"
#       type: "ConsensusResult"
#     - path: ".database/research.db"
#       type: "SQLite_Database"
#   output_destinations:
#     - path: ".database/research.db"
#       type: "SQLite_Database"
# vX.X.X - 2026-03-25: CCI_SE_ILL3_04 — archive_consensus_result result param
#   typed as RawConsensusDict. project_name corrected.
# === END OF SCRIPT DNA HEADER ====================================

import sqlite3
import hashlib
import json
import os
import traceback
from typing import Dict, Optional, Any
from src.utils.tier_response_formatter import RawConsensusDict

def ensure_research_db(db_dir: str = '.database') -> None:
    """
    Create research.db with query_archive and response_archive tables.
    
    Safe to call multiple times — uses CREATE TABLE IF NOT EXISTS.
    Non-fatal: prints error on failure, never raises.
    
    Args:
        db_dir: Directory for research.db (default '.database')
    """
    try:
        os.makedirs(db_dir, exist_ok=True)
        db_path = os.path.join(db_dir, 'research.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # =====================================================================
        # TABLE: query_archive
        # =====================================================================
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS query_archive (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                query_text TEXT NOT NULL,
                query_hash TEXT,
                query_purpose TEXT NOT NULL DEFAULT 'ad_hoc',
                order_id TEXT,
                query_id TEXT,
                category TEXT,
                user_id TEXT,
                tier TEXT DEFAULT 'free',
                provider_count INTEGER,
                consensus_pct REAL,
                champion_provider TEXT,
                champion_score INTEGER,
                processing_time_ms INTEGER
            )
        """)

        # =====================================================================
        # TABLE: response_archive
        # =====================================================================
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS response_archive (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_archive_id INTEGER NOT NULL REFERENCES query_archive(id),
                provider TEXT NOT NULL,
                response_text TEXT,
                status TEXT NOT NULL,
                score_total INTEGER,
                score_addressing INTEGER,
                score_completeness INTEGER,
                score_structure INTEGER,
                score_factual INTEGER,
                is_refusal BOOLEAN DEFAULT 0,
                refusal_pattern TEXT,
                refusal_penalty INTEGER DEFAULT 0,
                hal_flags JSON,
                response_time_ms INTEGER,
                token_count INTEGER,
                base_confidence REAL,
                was_champion BOOLEAN DEFAULT 0,
                model_version TEXT
            )
        """)

        # =====================================================================
        # INDEXES
        # =====================================================================
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_qa_timestamp ON query_archive(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_qa_purpose ON query_archive(query_purpose)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_qa_order ON query_archive(order_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_qa_champion ON query_archive(champion_provider)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_qa_hash ON query_archive(query_hash)")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ra_query ON response_archive(query_archive_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ra_provider ON response_archive(provider)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ra_champion ON response_archive(was_champion)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ra_refusal ON response_archive(is_refusal)")

        conn.commit()
        conn.close()
        print("[RESEARCH_DB] research.db tables ensured")

    except Exception as e:
        print(f"[RESEARCH_DB] Failed to ensure tables: {e}")


def archive_consensus_result(
    query_text: str,
    user_id: str,
    tier: str,
    result: RawConsensusDict,  # CCI_SE_ILL3_04: RawConsensusDict replaces Dict[str,Any]  # HAL-001-DEFERRED [ARCH_EXCEPTION] EX-SE-021
    query_purpose: str = 'ad_hoc',
    order_id: Optional[str] = None,
    query_id: Optional[str] = None,
    db_dir: str = '.database'
) -> None:
    """
    Archive one consensus result (query + all provider responses) to research.db.
    
    Non-fatal: prints error on failure, never raises. The consensus response
    MUST return to the user regardless of archive success.
    
    Args:
        query_text: Full query text (no truncation)
        user_id: Email or anonymous identifier
        tier: User tier at time of query
        result: Post-model_dump() consensus result dict
        query_purpose: Query classification (default 'ad_hoc')
        order_id: Publisher order ID (default None)
        query_id: Publisher query ID (default None)
        db_dir: Database directory path (default '.database')
    """
    try:
        # =================================================================
        # EXTRACT CONSENSUS METADATA
        # =================================================================
        query_hash = hashlib.sha256(query_text.encode('utf-8')).hexdigest()

        consensus = result.get('consensus', {})
        providers = result.get('providers', [])
        champion = consensus.get('champion', 'unknown')
        champion_score = consensus.get('champion_score', 0)
        agreement_pct = consensus.get('agreement_percentage', 0)

        # =================================================================
        # CONNECT TO RESEARCH DB
        # =================================================================
        db_path = os.path.join(db_dir, 'research.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # =================================================================
        # INSERT QUERY ARCHIVE ROW
        # =================================================================
        cursor.execute("""
            INSERT INTO query_archive (
                query_text, query_hash, query_purpose, order_id, query_id,
                category, user_id, tier, provider_count,
                consensus_pct, champion_provider, champion_score,
                processing_time_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            query_text,
            query_hash,
            query_purpose,
            order_id,
            query_id,
            None,  # category — future use
            user_id,
            tier,
            len(providers),
            agreement_pct,
            champion,
            champion_score,
            0  # processing_time_ms — placeholder
        ))

        query_archive_id = cursor.lastrowid

        # =================================================================
        # INSERT RESPONSE ARCHIVE ROWS (one per provider)
        # =================================================================
        for provider_data in providers:
            qb = provider_data.get('quality_breakdown') or {}
            ri = provider_data.get('refusal_indicators') or {}
            provider_name = provider_data.get('provider', '')

            # Determine champion flag
            was_champ = 1 if (provider_name == champion or
                              provider_name in str(champion)) else 0

            cursor.execute("""
                INSERT INTO response_archive (
                    query_archive_id, provider, response_text, status,
                    score_total, score_addressing, score_completeness,
                    score_structure, score_factual,
                    is_refusal, refusal_pattern, refusal_penalty,
                    hal_flags, response_time_ms, token_count,
                    base_confidence, was_champion, model_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                query_archive_id,
                provider_name,
                provider_data.get('answer', ''),
                provider_data.get('status', 'error'),
                provider_data.get('score', 0),
                qb.get('addressing_question', 0),
                qb.get('completeness', 0),
                qb.get('structure', 0),
                qb.get('factual_indicators', 0),
                1 if provider_data.get('is_refusal', False) else 0,
                ri.get('matched_pattern'),
                qb.get('refusal_penalty', 0),
                json.dumps([]),  # hal_flags — empty array for Phase NOW
                provider_data.get('response_time_ms', 0),
                provider_data.get('token_count', 0),
                provider_data.get('confidence', 0.0),
                was_champ,
                provider_data.get('model_version', '')
            ))

        conn.commit()
        conn.close()
        print(f"[RESEARCH_DB] Archived: {len(providers)} responses for query_archive #{query_archive_id}")

    except Exception as e:
        print(f"[RESEARCH_DB] Archive failed (non-fatal): {e}")
        traceback.print_exc()