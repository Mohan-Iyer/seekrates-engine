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
# defines_classes: "ProviderCallResult, AgentSuccessEntry, AgentFailureEntry, MultiAgentResult, ProviderSchemaFailure, OpenAICompatibleChoice, OpenAICompatibleRawResponse, ClaudeContentBlock, ClaudeRawResponse, GeminiContentPart, GeminiContent, GeminiCandidate, GeminiRawResponse, CohereContentBlock, CohereMessage, CohereV2RawResponse"
# defines_functions: "_load_safety_prime, _load_three_laws, _prepend_three_laws, _prepend_safety_prime, _filter_claude_preamble, get_api_key, dispatch_openai, dispatch_claude_api, dispatch_gemini, dispatch_mistral, dispatch_cohere, dispatch_deepseek, with_retry, call_llm_agent, call_multiple_agents"
# =============================================================================
# DEPENDENCIES:
# =============================================================================
# =============================================================================
# FIELD CONTRACTS:
# =============================================================================
#   input_sources:
#     - path: "config/system.yaml"
#       type: "YAML_Config"
#     - path: "docs/flow_control/three_laws_enforcement.yaml"
#       type: "YAML_Config"
#     - path: "environment variables"
#       type: "OS_Environment"
#   output_destinations:
#     - path: "src/agents/consensus_engine.py"
#       type: "ProviderCallResult"
#     - path: "src/agents/consensus_engine.py"
#       type: "MultiAgentResult"
# =============================================================================
# CHANGE LOG:
# =============================================================================
# v3.7.1 - 2026-03-24: logger.error -> print fix (6 schema_drift handlers)
# v3.7.0 - 2026-03-24: CCI_SE_ILL1_TYPEA_01 — ILL-1 TYPE-A repair.
#                       4 Pydantic raw response models added (OpenAICompatibleRawResponse,
#                       ClaudeRawResponse, GeminiRawResponse, CohereV2RawResponse).
#                       ProviderSchemaFailure TypedDict added.
#                       All 6 dispatch functions wired at HTTP boundary.
#                       template_version uplifted 0007 -> 0008 (CCI_SE_ILL2_01).
#                       project_name corrected to seekrates_engine.
# v3.6.0 - 2026-02-28: Previous production release.
# === END OF SCRIPT DNA HEADER ====================================

import os
import json
import time
import requests
import requests.exceptions
import asyncio
import re
# import redis
import concurrent.futures
from datetime import datetime
from pathlib import Path
from typing import TypedDict, Dict, Optional, List
import sys
import yaml
from pydantic import BaseModel, ValidationError

# =============================================================================
# TYPE CONTRACTS (ILL-1 GUARDRAIL — CCI-116-01)
# =============================================================================

class ProviderCallResult(TypedDict, total=False):
    """Return type for all single-provider dispatch functions, with_retry, call_llm_agent.
    total=False: confidence, latency_ms, error_type, model present on success paths only.
    """
    status: str            # always: 'success' | 'error' | 'mock'
    provider: str          # always: provider name
    response: str          # always: raw response text, '' on error
    answer: str            # always: processed answer, '' on error
    error: Optional[str]   # always: None on success/mock, message on error
    confidence: float      # success paths only
    latency_ms: int        # success paths only
    error_type: str        # some error paths (with_retry)
    model: str             # dispatch_deepseek success only


class AgentSuccessEntry(TypedDict, total=False):
    """Shape of items in MultiAgentResult.successful_responses."""
    provider: str
    answer: str
    status: str
    usage: Dict[str, int]   # Dict[str, int] — concrete types, not a HAL-001 violation
    response_time: str


class AgentFailureEntry(TypedDict, total=False):
    """Shape of items in MultiAgentResult.failed_responses."""
    provider: str
    error: str
    status: str


class MultiAgentResult(TypedDict, total=False):
    """Return type for call_multiple_agents."""
    agents_total: int
    agents_responded: int
    successful_responses: List[AgentSuccessEntry]
    failed_responses: List[AgentFailureEntry]
    agent_status: Dict[str, str]   # Dict[str, str] — concrete types, not a HAL-001 violation
    execution_time: float


class ProviderSchemaFailure(TypedDict):
    """Return type when Pydantic validation fails at raw response boundary.
    ILL-1 TYPE-A guardrail — CCI_SE_ILL1_TYPEA_01.
    """
    status: str       # always: 'error'
    provider: str     # provider name
    response: str     # always: ''
    answer: str       # always: ''
    error: str        # schema_drift description from ValidationError
    error_type: str   # always: 'schema_drift'

# =============================================================================
# EXTERNAL API RAW RESPONSE MODELS (ILL-1 TYPE-A — D-SE-ILL1-TYPEA-01)
# =============================================================================

class OpenAICompatibleMessage(BaseModel):
    """Message object within an OpenAI-compatible choice."""
    content: str
    role: str = "assistant"

    class Config:
        extra = "allow"


class OpenAICompatibleChoice(BaseModel):
    """Single choice from OpenAI-compatible response."""
    message: OpenAICompatibleMessage

    class Config:
        extra = "allow"  # finish_reason, index etc. present but not required


class OpenAICompatibleRawResponse(BaseModel):
    """Raw HTTP response from OpenAI, Mistral, DeepSeek APIs.
    All three use identical OpenAI chat completions response structure.
    """
    choices: List[OpenAICompatibleChoice]

    class Config:
        extra = "allow"  # usage, model, id fields present but not required


class ClaudeContentBlock(BaseModel):
    """Single content block from Claude API response."""
    type: str
    text: str

    class Config:
        extra = "allow"


class ClaudeRawResponse(BaseModel):
    """Raw HTTP response from Anthropic Claude API."""
    content: List[ClaudeContentBlock]

    class Config:
        extra = "allow"  # id, model, role, stop_reason, usage present


class GeminiContentPart(BaseModel):
    """Single part within a Gemini content block."""
    text: str = ""

    class Config:
        extra = "allow"


class GeminiContent(BaseModel):
    """Content block within a Gemini candidate."""
    parts: List[GeminiContentPart] = []

    class Config:
        extra = "allow"


class GeminiCandidate(BaseModel):
    """Single candidate from Gemini API response."""
    content: GeminiContent = GeminiContent()
    finishReason: str = "STOP"

    class Config:
        extra = "allow"


class GeminiRawResponse(BaseModel):
    """Raw HTTP response from Google Gemini API."""
    candidates: List[GeminiCandidate] = []

    class Config:
        extra = "allow"  # promptFeedback, usageMetadata present


class CohereContentBlock(BaseModel):
    """Single content block in Cohere v2 message."""
    type: str = "text"
    text: str = ""

    class Config:
        extra = "allow"


class CohereMessage(BaseModel):
    """Message object in Cohere v2 response."""
    content: List[CohereContentBlock] = []

    class Config:
        extra = "allow"


class CohereV2RawResponse(BaseModel):
    """Raw HTTP response from Cohere v2 /chat API."""
    message: CohereMessage = CohereMessage()

    class Config:
        extra = "allow"  # id, finish_reason, usage present

# =============================================================================

# Load system configuration
project_root = Path(__file__).resolve().parents[2]
with open(project_root / 'config/system.yaml') as f:
    SYSTEM_CONFIG = yaml.safe_load(f)

# Governance: NO SDK Rule Enforcement
FORBIDDEN_SDKS = ["openai", "anthropic", "google.generativeai", "mistralai", "cohere"]
for sdk in FORBIDDEN_SDKS:
    if sdk in sys.modules:
        raise ImportError(f"🚨 LLM SDK '{sdk}' forbidden by governance. Use HTTP only.")

# Add project root to path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))
import config
from src.config import USE_MOCK_MODE

# =============================================================================
# SAFETY PRIME INJECTION - HARM REDUCTION FRAMEWORK
# =============================================================================

def _load_safety_prime() -> str:
    """Load SAFETY_PRIME constraints from S3 (production) or local fallback (dev)"""
    import requests

    # S3 URL (production)
    s3_url = "https://seekrates-prime.s3.ap-southeast-2.amazonaws.com/SAFETY_PRIME.yaml"

    try:
        print("[SAFETY] Fetching SAFETY_PRIME from S3...")
        response = requests.get(s3_url, timeout=5)
        response.raise_for_status()

        data = yaml.safe_load(response.text) or {}
        block = data.get("safety_prime_prompt", "").rstrip()

        if not block:
            raise ValueError("SAFETY_PRIME.yaml missing 'safety_prime_prompt' key")

        print("[SAFETY] ✅ SAFETY_PRIME loaded from S3")
        return block + " "

    except requests.exceptions.RequestException as s3_error:
        print(f"[SAFETY] ⚠️ S3 fetch failed: {s3_error}")
        print("[SAFETY] Falling back to local file (dev mode)...")

        # Fallback to local file (dev environment)
        safety_path = Path("SAFETY_PRIME.yaml")
        if not safety_path.exists():
            safety_path = project_root / "SAFETY_PRIME.yaml"

        if not safety_path.exists():
            # Emergency fallback
            if os.getenv("ENV") == "dev":
                print("[SAFETY] Using emergency DEV fallback SAFETY_PRIME")
                return """[MANDATORY SAFETY CONSTRAINTS]
1. Do not provide information that could harm humans
2. Protect human wellbeing including mental health
3. Be truthful about your limitations as a text generator

[SYSTEM NOTICE]
This response will be compared against other AI models.
All content will be logged.

Query: """
            raise FileNotFoundError(f"CRITICAL: SAFETY_PRIME unavailable from S3 and local file missing at {safety_path}")

        # Load from local file
        with open(safety_path, "r") as f:
            data = yaml.safe_load(f) or {}

        block = data.get("safety_prime_prompt", "").rstrip()
        if not block:
            raise ValueError("SAFETY_PRIME.yaml missing 'safety_prime_prompt' key")

        print("[SAFETY] ✅ SAFETY_PRIME loaded from local file (dev mode)")
        return block + " "

    except Exception as e:
        print(f"[SAFETY] ❌ Unexpected error loading SAFETY_PRIME: {e}")
        raise

def _load_three_laws() -> str:
    """Load Three Laws constraints from governance file"""
    laws_path = Path("docs/flow_control/three_laws_enforcement.yaml")
    if not laws_path.exists():
        laws_path = project_root / "docs/flow_control/three_laws_enforcement.yaml"

    if not laws_path.exists():
        # Fallback to SAFETY_PRIME if Three Laws not yet deployed
        return _load_safety_prime()

    with open(laws_path, "r") as f:
        data = yaml.safe_load(f) or {}

    block = data.get("three_laws_prompt", "").rstrip()
    if not block:
        raise ValueError("three_laws_enforcement.yaml missing 'three_laws_prompt'")

    print("[SAFETY_PRIME] SAFETY_PRIME.yaml loaded")
    return block + " "

_THREE_LAWS = _load_three_laws()

def _prepend_three_laws(user_query: str) -> str:
    """Prepend Three Laws constraints to user query"""
    return f"{_THREE_LAWS}{user_query}"

def _prepend_safety_prime(user_query: str) -> str:
    """Prepend safety constraints to user query"""
    return f"{_SAFETY_PRIME}{user_query}"

def _filter_claude_preamble(response: str) -> str:
    """
    Strip Claude's acknowledgment of system instructions from response.
    Belt+suspenders defense - works even if prompt-level fix fails.

    GPS: fr_02_uc_08_ec_01_tc_094
    Session: 94 (2026-01-19)

    Patterns removed:
    - "Thank you for the detailed instructions..."
    - "I understand my role..."
    - "I understand the importance of providing..."
    """
    if not response:
        return response

    preamble_patterns = [
        r'^Thank you for the detailed instructions[^.]*\.\s*I understand[^.]*\.\s*(?:Here is my response:\s*)?',
        r'^I understand my role[^.]*\.\s*',
        r'^I understand the importance of providing[^.]*\.\s*(?:Here is my response:\s*)?',
        r'^Thank you for the[^.]*guidelines[^.]*\.\s*',
    ]

    filtered = response
    for pattern in preamble_patterns:
        filtered = re.sub(pattern, '', filtered, flags=re.IGNORECASE | re.DOTALL)

    # Log if filter was applied
    if filtered != response:
        print("[FILTER] Claude preamble stripped by belt+suspenders filter")

    return filtered.strip()

# =============================================================================
# API KEY MANAGEMENT
# =============================================================================

def get_api_key(agent: str) -> Optional[str]:
    """Get API key for the specified agent from environment variables"""
    key_mapping = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "cohere": "COHERE_API_KEY",
        # "deepseek": "DEEPSEEK_API_KEY"
    }

    # Handle Claude/Anthropic aliases
    if agent.lower() == "claude":
        # Try CLAUDE_API_KEY first, then ANTHROPIC_API_KEY
        key = os.environ.get("CLAUDE_API_KEY")
        if key:
            return key
        return os.environ.get("ANTHROPIC_API_KEY")

    env_var = key_mapping.get(agent.lower())
    if not env_var:
        return None

    return os.environ.get(env_var)

# =============================================================================
# HTTP-ONLY DISPATCH FUNCTIONS - NO SDKs
# =============================================================================

def dispatch_openai(agent: str, prompt: str) -> ProviderCallResult:
    """Dispatch to OpenAI API via HTTP with safety-injected prompt"""

    if USE_MOCK_MODE:
        return {
            'status': 'mock',
            'provider': 'openai',
            'response': '[MOCK] OpenAI response per config.USE_MOCK_MODE',
            'answer': '[MOCK] OpenAI response per config.USE_MOCK_MODE',
            'error': None
        }

    api_key = get_api_key("openai")
    if not api_key:
        return {
            'status': 'error',
            'provider': 'openai',
            'response': '',
            'answer': '',
            'error': 'OPENAI_API_KEY not configured'
        }

    try:
        provider_config = SYSTEM_CONFIG['agents']['providers']['openai']
        url = provider_config['endpoint']
        model = provider_config['model']
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8"
        }
        payload = {
            "model": model,
            "max_tokens": 1000,
            "messages": [
                {"role": "system", "content": _THREE_LAWS.rstrip()},
                {"role": "user", "content": prompt}
            ]
        }
        start_time = time.time()
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        end_time = time.time()
        latency_ms = int((end_time - start_time) * 1000)

        # ILL-1 TYPE-A boundary — validate raw response before field access
        try:
            raw = OpenAICompatibleRawResponse(**response.json())
        except ValidationError as exc:
            print(f"[OPENAI] schema_drift: {exc}")
            return ProviderSchemaFailure(
                status='error',
                provider='openai',
                response='',
                answer='',
                error=f'schema_drift: {exc}',
                error_type='schema_drift'
            )

        answer_text = raw.choices[0].message.content

        # Calculate confidence
        word_count = len(answer_text.split())
        quality_score = min(word_count / 100, 1.0)
        speed_score = max(0, 1 - (latency_ms / 5000))
        confidence = (quality_score * 0.6) + (speed_score * 0.4)

        return {
            'status': 'success',
            'provider': 'openai',
            'response': answer_text,
            'answer': answer_text,
            'confidence': round(confidence, 2),
            'latency_ms': latency_ms,
            'error': None
        }
    except requests.exceptions.RequestException as e:
        return {
            'status': 'error',
            'provider': 'openai',
            'response': '',
            'answer': '',
            'error': str(e)
        }
    except (KeyError, IndexError) as e:
        return {
            'status': 'error',
            'provider': 'openai',
            'response': '',
            'answer': '',
            'error': f'Unexpected response format: {str(e)}'
        }

def dispatch_claude_api(agent: str, prompt: str) -> ProviderCallResult:
    """Dispatch to Claude API via HTTP with safety-injected prompt"""

    if USE_MOCK_MODE:
        return {
            'status': 'mock',
            'provider': 'claude',
            'response': '[MOCK] Claude response per config.USE_MOCK_MODE',
            'answer': '[MOCK] Claude response per config.USE_MOCK_MODE',
            'error': None
        }

    api_key = get_api_key("claude")
    if not api_key:
        return {
            'status': 'error',
            'provider': 'claude',
            'response': '',
            'answer': '',
            'error': 'CLAUDE_API_KEY/ANTHROPIC_API_KEY not configured'
        }

    try:
        start_time = time.time()
        provider_config = SYSTEM_CONFIG['agents']['providers']['claude']
        url = provider_config['endpoint']
        model = provider_config['model']
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json; charset=utf-8"
        }
        payload = {
            "model": model,
            "max_tokens": 1000,
            "system": _THREE_LAWS.rstrip(),
            "messages": [{
                "role": "user",
                "content": [{"type": "text", "text": prompt}]
            }]
        }

        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        end_time = time.time()
        latency_ms = int((end_time - start_time) * 1000)

        # ILL-1 TYPE-A boundary — validate raw response before field access
        try:
            raw = ClaudeRawResponse(**response.json())
        except ValidationError as exc:
            print(f"[CLAUDE] schema_drift: {exc}")
            return ProviderSchemaFailure(
                status='error',
                provider='claude',
                response='',
                answer='',
                error=f'schema_drift: {exc}',
                error_type='schema_drift'
            )

        answer_text = raw.content[0].text

        # Calculate confidence
        word_count = len(answer_text.split())
        quality_score = min(word_count / 100, 1.0)
        speed_score = max(0, 1 - (latency_ms / 5000))
        confidence = (quality_score * 0.6) + (speed_score * 0.4)
        print(f"[CLAUDE CONFIDENCE] words={word_count}, quality={quality_score:.2f}, speed={speed_score:.2f}, confidence={confidence:.2f}, latency={latency_ms}ms")

        # Apply belt+suspenders filter to strip preamble (Session 94 fix)
        filtered_answer = _filter_claude_preamble(answer_text)

        return {
            'status': 'success',
            'provider': 'claude',
            'response': filtered_answer,
            'answer': filtered_answer,
            'confidence': round(confidence, 2),
            'latency_ms': latency_ms,
            'error': None
        }
    except requests.exceptions.RequestException as e:
        return {
            'status': 'error',
            'provider': 'claude',
            'response': '',
            'answer': '',
            'error': str(e)
        }
    except (KeyError, IndexError) as e:
        return {
            'status': 'error',
            'provider': 'claude',
            'response': '',
            'answer': '',
            'error': f'Unexpected Claude response format: {str(e)}'
        }

def dispatch_gemini(agent: str, prompt: str) -> ProviderCallResult:
    """Dispatch to Gemini API via HTTP with safety-injected prompt"""

    if USE_MOCK_MODE:
        return {
            'status': 'mock',
            'provider': 'gemini',
            'response': '[MOCK] Gemini response per config.USE_MOCK_MODE',
            'answer': '[MOCK] Gemini response per config.USE_MOCK_MODE',
            'error': None
        }

    api_key = get_api_key("gemini")
    if not api_key:
        return {
            'status': 'error',
            'provider': 'gemini',
            'response': '',
            'answer': '',
            'error': 'GEMINI_API_KEY not configured'
        }

    model = SYSTEM_CONFIG['agents']['providers']['gemini']['model']

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "x-goog-api-key": api_key
    }

    payload = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 2048
        }
    }

    try:
        start_time = time.time()
        provider_config = SYSTEM_CONFIG['agents']['providers']['gemini']
        url = f"{provider_config['endpoint']}/{model}:generateContent"
        print(f"[GEMINI DEBUG] URL: {url}")
        print(f"[GEMINI DEBUG] Model: {model}")
        model = provider_config['model']

        response = requests.post(url, headers=headers, json=payload, timeout=30)
        end_time = time.time()
        latency_ms = int((end_time - start_time) * 1000)

        if response.status_code != 200:
            print(f"[GEMINI ERROR] Status: {response.status_code}")
            print(f"[GEMINI ERROR] Response: {response.text}")
            return {
                'status': 'error',
                'provider': 'gemini',
                'response': '',
                'answer': '',
                'error': f'Gemini API error {response.status_code}'
            }

        # ILL-1 TYPE-A boundary — validate raw response before field access
        try:
            raw = GeminiRawResponse(**response.json())
        except ValidationError as exc:
            print(f"[GEMINI] schema_drift: {exc}")
            return ProviderSchemaFailure(
                status='error',
                provider='gemini',
                response='',
                answer='',
                error=f'schema_drift: {exc}',
                error_type='schema_drift'
            )

        # Check finish reason BEFORE parsing
        if raw.candidates:
            finish_reason = raw.candidates[0].finishReason

            # Log truncation warning
            if finish_reason == 'MAX_TOKENS':
                print(f"[GEMINI WARNING] Response truncated - MAX_TOKENS reached. Consider increasing maxOutputTokens.")
            elif finish_reason == 'SAFETY':
                return {
                    'status': 'error',
                    'provider': 'gemini',
                    'response': '',
                    'answer': '',
                    'error': 'Content blocked by Gemini safety filters'
                }

        # Robust response extraction with partial text support
        answer_text = None

        try:
            if raw.candidates:
                candidate = raw.candidates[0]
                finish_reason = candidate.finishReason

                # Method 1: Standard parts array
                if candidate.content.parts:
                    parts = candidate.content.parts
                    if parts and parts[0].text:
                        answer_text = parts[0].text

                        # If truncated, append notice
                        if finish_reason == 'MAX_TOKENS':
                            answer_text += "\n\n[Note: Response truncated - increase token limit for complete answer]"

                # Method 2: Direct text field (fallback) — check raw dict
                elif 'text' in response.json().get('candidates', [{}])[0].get('content', {}):
                    answer_text = response.json()['candidates'][0]['content']['text']

                # Method 3: Legacy format — check raw dict
                elif 'output' in response.json().get('candidates', [{}])[0]:
                    answer_text = response.json()['candidates'][0]['output']

        except (KeyError, IndexError, TypeError) as parse_error:
            print(f"[GEMINI PARSE ERROR] {parse_error}")
            print(f"[GEMINI DEBUG] Response: {json.dumps(response.json(), indent=2)[:500]}")

        # Final validation
        if not answer_text or not answer_text.strip():
            finish_reason_str = raw.candidates[0].finishReason if raw.candidates else 'UNKNOWN'
            return {
                'status': 'error',
                'provider': 'gemini',
                'response': '',
                'answer': '',
                'error': f'Empty response from Gemini. Finish reason: {finish_reason_str}'
            }

        # Calculate confidence
        word_count = len(answer_text.split())
        quality_score = min(word_count / 100, 1.0)
        speed_score = max(0, 1 - (latency_ms / 5000))
        confidence = (quality_score * 0.6) + (speed_score * 0.4)

        return {
            'status': 'success',
            'provider': 'gemini',
            'response': answer_text,
            'answer': answer_text,
            'confidence': round(confidence, 2),
            'latency_ms': latency_ms,
            'error': None
        }

    except requests.exceptions.RequestException as e:
        return {
            'status': 'error',
            'provider': 'gemini',
            'response': '',
            'answer': '',
            'error': str(e)
        }
    except Exception as e:
        return {
            'status': 'error',
            'provider': 'gemini',
            'response': '',
            'answer': '',
            'error': f'Unexpected error: {str(e)}'
        }

def dispatch_mistral(agent: str, prompt: str) -> ProviderCallResult:
    """Dispatch to Mistral API via HTTP with safety-injected prompt"""

    if USE_MOCK_MODE:
        return {
            'status': 'mock',
            'provider': 'mistral',
            'response': '[MOCK] Mistral response per config.USE_MOCK_MODE',
            'answer': '[MOCK] Mistral response per config.USE_MOCK_MODE',
            'error': None
        }

    api_key = get_api_key("mistral")
    if not api_key:
        return {
            'status': 'error',
            'provider': 'mistral',
            'response': '',
            'answer': '',
            'error': 'MISTRAL_API_KEY not configured'
        }

    try:
        start_time = time.time()
        provider_config = SYSTEM_CONFIG['agents']['providers']['mistral']
        url = provider_config['endpoint']
        model = provider_config['model']

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8"
        }

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1000,
            "temperature": 0.3
        }

        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        end_time = time.time()
        latency_ms = int((end_time - start_time) * 1000)

        # ILL-1 TYPE-A boundary — validate raw response before field access
        try:
            raw = OpenAICompatibleRawResponse(**response.json())
        except ValidationError as exc:
            print(f"[MISTRAL] schema_drift: {exc}")
            return ProviderSchemaFailure(
                status='error',
                provider='mistral',
                response='',
                answer='',
                error=f'schema_drift: {exc}',
                error_type='schema_drift'
            )

        answer_text = raw.choices[0].message.content

        # Calculate confidence
        word_count = len(answer_text.split())
        quality_score = min(word_count / 100, 1.0)
        speed_score = max(0, 1 - (latency_ms / 5000))
        confidence = (quality_score * 0.6) + (speed_score * 0.4)

        return {
            'status': 'success',
            'provider': 'mistral',
            'response': answer_text,
            'answer': answer_text,
            'confidence': round(confidence, 2),
            'latency_ms': latency_ms,
            'error': None
        }
    except requests.exceptions.RequestException as e:
        return {
            'status': 'error',
            'provider': 'mistral',
            'response': '',
            'answer': '',
            'error': str(e)
        }
    except (KeyError, IndexError) as e:
        return {
            'status': 'error',
            'provider': 'mistral',
            'response': '',
            'answer': '',
            'error': f'Unexpected response format: {str(e)}'
        }

def dispatch_cohere(agent: str, prompt: str) -> ProviderCallResult:
    """Dispatch to Cohere API v2 via HTTP with safety-injected prompt

    FIXED: Using correct /v2/chat endpoint with v2 payload structure
    """

    if USE_MOCK_MODE:
        return {
            'status': 'mock',
            'provider': 'cohere',
            'response': '[MOCK] Cohere response per config.USE_MOCK_MODE',
            'answer': '[MOCK] Cohere response per config.USE_MOCK_MODE',
            'error': None
        }

    api_key = get_api_key("cohere")
    if not api_key:
        return {
            'status': 'error',
            'provider': 'cohere',
            'response': '',
            'answer': '',
            'error': 'COHERE_API_KEY not configured'
        }

    try:
        start_time = time.time()

        # ✅ FIXED: Use /v2/chat endpoint (v1 is deprecated)
        provider_config = SYSTEM_CONFIG['agents']['providers']['cohere']
        url = provider_config['endpoint']
        model = provider_config['model']

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8"
        }

        # ✅ FIXED: v2 uses "messages" array with role/content structure
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": 1000,
            "temperature": 0.3  # v2 default is 0.3
        }

        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        end_time = time.time()
        latency_ms = int((end_time - start_time) * 1000)

        # ILL-1 TYPE-A boundary — validate raw response before field access
        # ✅ FIXED: v2 response structure is nested: message.content[0].text
        try:
            raw = CohereV2RawResponse(**response.json())
        except ValidationError as exc:
            print(f"[COHERE] schema_drift: {exc}")
            return ProviderSchemaFailure(
                status='error',
                provider='cohere',
                response='',
                answer='',
                error=f'schema_drift: {exc}',
                error_type='schema_drift'
            )

        answer_text = raw.message.content[0].text if raw.message.content else ""

        # Calculate confidence
        word_count = len(answer_text.split())
        quality_score = min(word_count / 100, 1.0)
        speed_score = max(0, 1 - (latency_ms / 5000))
        confidence = (quality_score * 0.6) + (speed_score * 0.4)

        return {
            'status': 'success',
            'provider': 'cohere',
            'response': answer_text,
            'answer': answer_text,
            'confidence': round(confidence, 2),
            'latency_ms': latency_ms,
            'error': None
        }

    except requests.exceptions.RequestException as e:
        return {
            'status': 'error',
            'provider': 'cohere',
            'response': '',
            'answer': '',
            'error': str(e)
        }
    except (KeyError, IndexError) as e:
        return {
            'status': 'error',
            'provider': 'cohere',
            'response': '',
            'answer': '',
            'error': f'Unexpected Cohere v2 response format: {str(e)}'
        }

def dispatch_deepseek(agent: str, prompt: str) -> ProviderCallResult:
    """
    Dispatch to DeepSeek API via HTTP with safety-injected prompt.

    DeepSeek uses OpenAI-compatible API format.
    Model: deepseek-chat (or deepseek-reasoner for R1)

    Note:
        R1 gotcha: If model ignores constraints, move MISSION to user message.
        Currently using system prompt for automatic caching benefit.

    GPS: fr_03_uc_01_ec_01_tc_007
    """

    if USE_MOCK_MODE:
        return {
            'status': 'mock',
            'provider': 'deepseek',
            'response': '[MOCK] DeepSeek response per config.USE_MOCK_MODE',
            'answer': '[MOCK] DeepSeek response per config.USE_MOCK_MODE',
            'error': None
        }

    api_key = get_api_key("deepseek")
    if not api_key:
        return {
            'status': 'error',
            'provider': 'deepseek',
            'response': '',
            'answer': '',
            'error': 'DEEPSEEK_API_KEY not configured'
        }

    try:
        start_time = time.time()

        url = "https://api.deepseek.com/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8"
        }

        payload = {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1000,
            "temperature": 0.7
        }

        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()

        end_time = time.time()
        latency_ms = int((end_time - start_time) * 1000)

        # ILL-1 TYPE-A boundary — validate raw response before field access
        try:
            raw = OpenAICompatibleRawResponse(**response.json())
        except ValidationError as exc:
            print(f"[DEEPSEEK] schema_drift: {exc}")
            return ProviderSchemaFailure(
                status='error',
                provider='deepseek',
                response='',
                answer='',
                error=f'schema_drift: {exc}',
                error_type='schema_drift'
            )

        answer_text = raw.choices[0].message.content

        # Calculate confidence based on response quality
        word_count = len(answer_text.split())
        quality_score = min(word_count / 100, 1.0)
        speed_score = max(0, 1 - (latency_ms / 5000))
        confidence = (quality_score * 0.6) + (speed_score * 0.4)

        print(f"✅ [SUCCESS] deepseek: {answer_text[:100]}...")

        return {
            'status': 'success',
            'provider': 'deepseek',
            'response': answer_text,
            'answer': answer_text,
            'confidence': round(confidence, 2),
            'latency_ms': latency_ms,
            'model': 'deepseek-chat',
            'error': None
        }

    except requests.exceptions.RequestException as e:
        return {
            'status': 'error',
            'provider': 'deepseek',
            'response': '',
            'answer': '',
            'error': str(e)
        }
    except (KeyError, IndexError) as e:
        return {
            'status': 'error',
            'provider': 'deepseek',
            'response': '',
            'answer': '',
            'error': f'Unexpected response format: {str(e)}'
        }

# =============================================================================
# RETRY MECHANISM
# =============================================================================

def with_retry(dispatch_func, agent: str, prompt: str, max_retries: int = 3) -> ProviderCallResult:
    """
    Wrapper for retry logic on dispatch functions
    GPS: fr_03_uc_03_ec_01_tc_006
    """
    for attempt in range(max_retries):
        try:
            result = dispatch_func(agent, prompt)
            if result.get('status') != 'error':
                return result

            # If error, retry with exponential backoff
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                print(f"[RETRY] Attempt {attempt + 1} failed for {agent}: {result.get('error')}")
                print(f"[RETRY] Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
        except Exception as e:
            if attempt == max_retries - 1:
                return {
                    'status': 'error',
                    'provider': agent,
                    'response': '',
                    'answer': '',
                    'error': str(e),
                    'error_type': 'dispatch_exception'
                }
            wait_time = 2 ** attempt
            print(f"[RETRY] Exception on attempt {attempt + 1}: {str(e)}")
            print(f"[RETRY] Waiting {wait_time}s before retry...")
            time.sleep(wait_time)

    return {
        'status': 'error',
        'provider': agent,
        'response': '',
        'answer': '',
        'error': f'Max retries ({max_retries}) exceeded',
        'error_type': 'max_retries_exceeded'
    }

# =============================================================================
# MAIN DISPATCHER
# =============================================================================

def call_llm_agent(agent: str, question: str) -> ProviderCallResult:
    """
    Route to appropriate agent dispatcher based on agent name
    GPS Coordinate: fr_03_uc_03_ec_01_tc_004
    """
    print(f"\n🎯 [LLM_DISPATCHER] Agent: {agent}, Question: {question[:50]}...")

    # Check API key availability
    api_key = get_api_key(agent)
    if not api_key:
        print(f"⚠️ No API key for {agent}, excluding from run")
        return {
            'status': 'error',
            'provider': agent,
            'answer': '',
            'response': '',
            'error': f'API key not configured for {agent}'
        }


    # SAFETY PRIME INJECTION
    original_question = question
    question = _prepend_three_laws(question)
    print(f"[SAFETY_PRIME] Injected safety guidelines from SAFETY_PRIME.yaml")

    # Debug logging
    if USE_MOCK_MODE:
        print(f"[MOCK MODE] Config.USE_MOCK_MODE is True")
    else:
        print(f"[REAL MODE] Config.USE_MOCK_MODE is False")
        print(f"[DEBUG] OPENAI_API_KEY present: {bool(os.getenv('OPENAI_API_KEY'))}")
        print(f"[DEBUG] ANTHROPIC_API_KEY present: {bool(os.getenv('ANTHROPIC_API_KEY'))}")
        print(f"[DEBUG] GEMINI_API_KEY present: {bool(os.getenv('GEMINI_API_KEY'))}")
        print(f"[DEBUG] MISTRAL_API_KEY present: {bool(os.getenv('MISTRAL_API_KEY'))}")
        print(f"[DEBUG] COHERE_API_KEY present: {bool(os.getenv('COHERE_API_KEY'))}")
        print(f"[DEBUG] DEEPSEEK_API_KEY present: {bool(os.getenv('DEEPSEEK_API_KEY'))}")

    # Map agent names to dispatch functions
    agent_dispatchers = {
        'openai': dispatch_openai,
        'claude': dispatch_claude_api,
        'anthropic': dispatch_claude_api,  # Alias for claude
        'gemini': dispatch_gemini,
        'mistral': dispatch_mistral,
        'cohere': dispatch_cohere,
        'deepseek': dispatch_deepseek
    }

    # Dispatch to appropriate function
    dispatch_func = agent_dispatchers.get(agent.lower())
    if dispatch_func:
        # BUG-108-01: Claude uses system parameter for SAFETY_PRIME
        # so it receives raw query only; others get prepended prompt
        if agent.lower() in ('claude', 'anthropic'):
            result = with_retry(dispatch_func, agent, original_question)
        else:
            result = with_retry(dispatch_func, agent, question)

        # LOG THE RESULT
        if result.get('status') == 'success':
            print(f"[SUCCESS] {agent}: {result.get('response', '')[:100]}...")
        elif result.get('status') == 'mock':
            print(f"­ [MOCK] {agent}: Mock response returned")
        else:
            print(f"[FAILED] {agent}: {result.get('error', 'Unknown error')}")
            print(f"[ERROR_TYPE] {result.get('error_type', 'unspecified')}")

        return result
    else:
        return {
            'status': 'error',
            'provider': agent,
            'response': '',
            'answer': '',
            'error': f'Unknown agent: {agent}',
            'error_type': 'unknown_provider'
        }

# =============================================================================
# MULTI-AGENT PARALLEL EXECUTION - GPS: fr_03_uc_03_ec_01_tc_007
# =============================================================================

async def call_multiple_agents(
    agents_list: List[str],
    question: str,
    mode: str = 'wait_for_all',
    per_agent_timeout: int = 30,
    max_wait_seconds: int = 40
) -> MultiAgentResult:
    """
    Call multiple agents in parallel and collect responses
    GPS: fr_03_uc_03_ec_01_tc_007
    """
    start_time = time.time()
    results = {
        'agents_total': len(agents_list),
        'agents_responded': 0,
        'successful_responses': [],
        'failed_responses': [],
        'agent_status': {},
        'execution_time': 0
    }

    # Simple synchronous implementation for now
    for agent in agents_list:
        try:
            response = call_llm_agent(agent, question)
            results['agent_status'][agent] = response.get('status', 'unknown')

            if response.get('status') in ['success', 'mock']:
                results['agents_responded'] += 1
                results['successful_responses'].append({
                    'provider': agent,
                    'answer': response.get('answer', response.get('response', '')),
                    'status': response.get('status'),
                    'usage': {'total_tokens': 100},
                    'response_time': '2.0s'
                })
            else:
                results['failed_responses'].append({
                    'provider': agent,
                    'error': response.get('error', 'Unknown error'),
                    'status': 'error'
                })
        except Exception as e:
            results['failed_responses'].append({
                'provider': agent,
                'error': str(e),
                'status': 'error'
            })

    results['execution_time'] = time.time() - start_time
    return results