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
# defines_classes: "ConsensusConstants"
# defines_functions: "None"
# =============================================================================
# DEPENDENCIES:
# =============================================================================
# =============================================================================
# FIELD CONTRACTS:
# =============================================================================
# === END OF SCRIPT DNA HEADER ====================================

class ConsensusConstants:
    """All magic numbers extracted to constants"""
    
    # From consensus_cag.py
    DEFAULT_CONFIDENCE_THRESHOLD = 0.75
    MINIMUM_AGENTS_FOR_CONSENSUS = 2
    SIMILARITY_THRESHOLD = 0.85
    
    # From llm_dispatcher.py
    TIMEOUT_SECONDS = 30
    MAX_RETRY_ATTEMPTS = 3
    DEFAULT_TEMPERATURE = 0.7
    MAX_TOKENS = 4096
    
    # From main.py
    RATE_LIMIT_REQUESTS = 100
    RATE_LIMIT_WINDOW = 60
    PORT = 8000
    HOST = "0.0.0.0"
    
    # Browser test constraints
    MAX_AGENTS_PER_TEST = 5
    MAX_TOKENS_PER_AGENT = 250
    
    # Response formatting
    MAX_RESPONSE_PREVIEW_WORDS = 75
    MAX_RATIONALE_LENGTH = 150
    
    # Cache TTL
    CACHE_TTL_SECONDS = 3600
    REDIS_CONNECTION_TIMEOUT = 5
    
    # Consensus thresholds
    HIGH_CONFIDENCE_TIER = 95
    MEDIUM_CONFIDENCE_TIER = 80
    LOW_CONFIDENCE_TIER = 50
    
    # API rate limits
    OPENAI_RATE_LIMIT = 60
    CLAUDE_RATE_LIMIT = 50
    GEMINI_RATE_LIMIT = 100
    MISTRAL_RATE_LIMIT = 40
    COHERE_RATE_LIMIT = 30
    
    # Model selection
    DEFAULT_OPENAI_MODEL = "gpt-3.5-turbo"
    DEFAULT_CLAUDE_MODEL = "claude-3-haiku-20240307"
    DEFAULT_GEMINI_MODELS = [
        "gemini-1.5-flash",
        "gemini-1.5-flash-latest",
        "gemini-1.0-pro",
        "gemini-pro"
    ]
    DEFAULT_MISTRAL_MODEL = "mistral-tiny"
    DEFAULT_COHERE_MODEL = "command"