#!/usr/bin/env python3
# filename: seekrates_engine_production/src/agents/provider_factory.py
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
# defines_classes: "ProviderSchemaFailure, OpenAIRawResponse, ClaudeRawResponse, GeminiRawResponse, CohereRawResponse, ProviderCallResult, BaseProvider, OpenAIProvider, ClaudeProvider, GeminiProvider, MistralProvider, CohereProvider, ProviderFactory"
# defines_functions: "__init__, get_api_key, validate_api_key, call, _make_request, get_model_name"
# =============================================================================
# DEPENDENCIES:
# =============================================================================
# =============================================================================
# FIELD CONTRACTS:
# =============================================================================
#   input_sources:
#     - path: "directory_map.yaml"
#       type: "YAML_Config"
#     - path: "environment variables"
#       type: "OS_Environment"
#     - path: "src/core/protocols.py"
#       type: "ProviderProtocol"
#   output_destinations:
#     - path: "src/core/engine.py"
#       type: "ProviderProtocol"
#     - path: "src/agents/consensus_engine.py"
#       type: "ProviderProtocol"
# =============================================================================
# CHANGE LOG:
# =============================================================================
# v2.1.0 - 2026-03-25: CCI_SE_ILL1_TYPEA_02 — Pydantic raw response models
#   added for all 5 providers (OpenAI, Claude, Gemini, Mistral, Cohere).
#   Wired at HTTP boundary in each _make_request method.
#   project_name corrected seekrates_ai → seekrates_engine.
# v2.0.0 - 2026-02-26: HAL-001 sprint — replaced 7 Dict[str, Any] return types
# v1.0.0 - 2026-02-25: Initial production release.
# === END OF SCRIPT DNA HEADER ====================================

import logging
import yaml
import os
import requests
import time
from typing import Dict, Any, Optional, TypedDict, Union
from abc import ABC, abstractmethod
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

# Load paths from directory_map.yaml
with open('directory_map.yaml', 'r') as f:
    directory_map = yaml.safe_load(f)

from src.core.protocols import ProviderProtocol
from src.core.constants import ConsensusConstants


# =============================================================================
# PYDANTIC RAW RESPONSE MODELS — HTTP BOUNDARY VALIDATORS
# (CCI_SE_ILL1_TYPEA_02 — D-SE-ILL1-TYPEA-01)
# =============================================================================

class ProviderSchemaFailure(BaseModel):
    """Returned when raw API response fails Pydantic validation."""
    provider: str
    error: str
    raw_type: str


class OpenAIRawResponse(BaseModel):
    """Pydantic validator for raw OpenAI/Mistral chat completions response.
    Covers OpenAI and Mistral (identical response shape).
    """
    class Choice(BaseModel):
        class Message(BaseModel):
            content: str
        message: Message
    choices: list[Choice]
    usage: Optional[Dict[str, int]] = None


class ClaudeRawResponse(BaseModel):
    """Pydantic validator for raw Anthropic Claude response."""
    class ContentBlock(BaseModel):
        type: str
        text: str
    content: list[ContentBlock]


class GeminiRawResponse(BaseModel):
    """Pydantic validator for raw Google Gemini response."""
    class Candidate(BaseModel):
        class Content(BaseModel):
            class Part(BaseModel):
                text: str
            parts: list[Part]
        content: Content
    candidates: list[Candidate]


class CohereRawResponse(BaseModel):
    """Pydantic validator for raw Cohere v1 generate response."""
    class Generation(BaseModel):
        text: str
    generations: list[Generation]


# =============================================================================
# PROVIDER CALL RESULT — INTERNAL TYPED RETURN
# =============================================================================

class ProviderCallResult(TypedDict, total=False):
    """Typed return structure for all provider call and _make_request methods.
    total=False: not all providers return all fields (e.g. usage, model_used).
    usage typed Dict[str, int] — all token counts are integers (D-112-04).
    """
    status: str
    response: str
    confidence: float
    error: str
    usage: Dict[str, int]
    model_used: str


# =============================================================================
# BASE PROVIDER
# =============================================================================

class BaseProvider(ABC, ProviderProtocol):
    """Base class for all LLM providers"""

    def __init__(self):
        self.constants = ConsensusConstants()
        self.api_key = self.get_api_key()

    @abstractmethod
    def get_api_key(self) -> Optional[str]:
        """Get API key from environment"""
        pass

    def validate_api_key(self) -> bool:
        """Validate API key exists"""
        return bool(self.api_key)

    async def call(self, query: str, **kwargs) -> ProviderCallResult:
        """Call provider with retry logic"""
        for attempt in range(self.constants.MAX_RETRY_ATTEMPTS):
            try:
                result = await self._make_request(query, **kwargs)
                if result.get('status') == 'success':
                    return result

                if attempt < self.constants.MAX_RETRY_ATTEMPTS - 1:
                    wait_time = 2 ** attempt
                    time.sleep(wait_time)
            except Exception as e:
                if attempt == self.constants.MAX_RETRY_ATTEMPTS - 1:
                    return {
                        'status': 'error',
                        'error': str(e),
                        'response': '',
                        'confidence': 0.0
                    }
                wait_time = 2 ** attempt
                time.sleep(wait_time)

        return {
            'status': 'error',
            'error': 'Max retries exceeded',
            'response': '',
            'confidence': 0.0
        }

    @abstractmethod
    async def _make_request(self, query: str, **kwargs) -> ProviderCallResult:
        """Make actual API request"""
        pass


# =============================================================================
# PROVIDER IMPLEMENTATIONS
# =============================================================================

class OpenAIProvider(BaseProvider):
    """OpenAI API provider"""

    def get_api_key(self) -> Optional[str]:
        return os.environ.get("OPENAI_API_KEY")

    def get_model_name(self) -> str:
        return self.constants.DEFAULT_OPENAI_MODEL

    async def _make_request(self, query: str, **kwargs) -> ProviderCallResult:
        """Make request to OpenAI API"""
        try:
            url = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": self.get_model_name(),
                "messages": [{"role": "user", "content": query}],
                "max_tokens": kwargs.get('max_tokens', self.constants.MAX_TOKENS_PER_AGENT),
                "temperature": kwargs.get('temperature', self.constants.DEFAULT_TEMPERATURE)
            }

            response = requests.post(url, headers=headers, json=payload, timeout=self.constants.TIMEOUT_SECONDS)
            response.raise_for_status()

            try:
                parsed = OpenAIRawResponse.model_validate(response.json())
            except ValidationError as e:
                logger.error("OpenAIProvider schema validation failed: %s", e)
                return ProviderCallResult(
                    status='error',
                    error=f'Schema validation failed: {e}',
                    response='',
                    confidence=0.0
                )
            return ProviderCallResult(
                status='success',
                response=parsed.choices[0].message.content,
                confidence=0.8,
                usage=parsed.usage or {}
            )
        except Exception as e:
            logger.error("OpenAIProvider._make_request failed: %s", e)
            raise


class ClaudeProvider(BaseProvider):
    """Claude/Anthropic API provider"""

    def get_api_key(self) -> Optional[str]:
        # Try CLAUDE_API_KEY first, then ANTHROPIC_API_KEY
        return os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")

    def get_model_name(self) -> str:
        return self.constants.DEFAULT_CLAUDE_MODEL

    async def _make_request(self, query: str, **kwargs) -> ProviderCallResult:
        """Make request to Claude API"""
        try:
            url = "https://api.anthropic.com/v1/messages"
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            }
            payload = {
                "model": self.get_model_name(),
                "max_tokens": kwargs.get('max_tokens', self.constants.MAX_TOKENS_PER_AGENT),
                "messages": [{
                    "role": "user",
                    "content": [{"type": "text", "text": query}]
                }]
            }

            response = requests.post(url, headers=headers, json=payload, timeout=self.constants.TIMEOUT_SECONDS)
            response.raise_for_status()

            try:
                parsed = ClaudeRawResponse.model_validate(response.json())
            except ValidationError as e:
                logger.error("ClaudeProvider schema validation failed: %s", e)
                return ProviderCallResult(
                    status='error',
                    error=f'Schema validation failed: {e}',
                    response='',
                    confidence=0.0
                )
            text = parsed.content[0].text
            return ProviderCallResult(
                status='success',
                response=text,
                confidence=0.85,
                usage={'total_tokens': len(query.split()) + len(text.split())}
            )
        except Exception as e:
            logger.error("ClaudeProvider._make_request failed: %s", e)
            raise


class GeminiProvider(BaseProvider):
    """Google Gemini API provider"""

    def get_api_key(self) -> Optional[str]:
        return os.environ.get("GEMINI_API_KEY")

    def get_model_name(self) -> str:
        return self.constants.DEFAULT_GEMINI_MODELS[0]

    async def _make_request(self, query: str, **kwargs) -> ProviderCallResult:
        """Make request to Gemini API with fallback models"""
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{
                "parts": [{"text": query}]
            }],
            "generationConfig": {
                "temperature": kwargs.get('temperature', self.constants.DEFAULT_TEMPERATURE),
                "maxOutputTokens": kwargs.get('max_tokens', self.constants.MAX_TOKENS_PER_AGENT)
            }
        }

        # Try each model until one works
        for model in self.constants.DEFAULT_GEMINI_MODELS:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"

            try:
                response = requests.post(url, headers=headers, json=payload, timeout=self.constants.TIMEOUT_SECONDS)

                if response.status_code == 200:
                    try:
                        parsed = GeminiRawResponse.model_validate(response.json())
                    except ValidationError as e:
                        logger.error("GeminiProvider schema validation failed (model %s): %s", model, e)
                        continue
                    if parsed.candidates:
                        return ProviderCallResult(
                            status='success',
                            response=parsed.candidates[0].content.parts[0].text,
                            confidence=0.75,
                            model_used=model
                        )
                elif response.status_code != 404:
                    break
            except:
                continue

        return {
            'status': 'error',
            'error': 'All Gemini models failed',
            'response': '',
            'confidence': 0.0
        }


class MistralProvider(BaseProvider):
    """Mistral API provider"""

    def get_api_key(self) -> Optional[str]:
        return os.environ.get("MISTRAL_API_KEY")

    def get_model_name(self) -> str:
        return self.constants.DEFAULT_MISTRAL_MODEL

    async def _make_request(self, query: str, **kwargs) -> ProviderCallResult:
        """Make request to Mistral API"""
        try:
            url = "https://api.mistral.ai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": self.get_model_name(),
                "messages": [{"role": "user", "content": query}],
                "max_tokens": kwargs.get('max_tokens', self.constants.MAX_TOKENS_PER_AGENT),
                "temperature": kwargs.get('temperature', self.constants.DEFAULT_TEMPERATURE)
            }

            response = requests.post(url, headers=headers, json=payload, timeout=self.constants.TIMEOUT_SECONDS)
            response.raise_for_status()

            try:
                parsed = OpenAIRawResponse.model_validate(response.json())
            except ValidationError as e:
                logger.error("MistralProvider schema validation failed: %s", e)
                return ProviderCallResult(
                    status='error',
                    error=f'Schema validation failed: {e}',
                    response='',
                    confidence=0.0
                )
            return ProviderCallResult(
                status='success',
                response=parsed.choices[0].message.content,
                confidence=0.7
            )
        except Exception as e:
            logger.error("MistralProvider._make_request failed: %s", e)
            raise


class CohereProvider(BaseProvider):
    """Cohere API provider"""

    def get_api_key(self) -> Optional[str]:
        return os.environ.get("COHERE_API_KEY")

    def get_model_name(self) -> str:
        return self.constants.DEFAULT_COHERE_MODEL

    async def _make_request(self, query: str, **kwargs) -> ProviderCallResult:
        """Make request to Cohere API"""
        try:
            url = "https://api.cohere.ai/v1/generate"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": self.get_model_name(),
                "prompt": query,
                "max_tokens": kwargs.get('max_tokens', self.constants.MAX_TOKENS_PER_AGENT),
                "temperature": kwargs.get('temperature', self.constants.DEFAULT_TEMPERATURE)
            }

            response = requests.post(url, headers=headers, json=payload, timeout=self.constants.TIMEOUT_SECONDS)
            response.raise_for_status()

            try:
                parsed = CohereRawResponse.model_validate(response.json())
            except ValidationError as e:
                logger.error("CohereProvider schema validation failed: %s", e)
                return ProviderCallResult(
                    status='error',
                    error=f'Schema validation failed: {e}',
                    response='',
                    confidence=0.0
                )
            return ProviderCallResult(
                status='success',
                response=parsed.generations[0].text.strip(),
                confidence=0.65
            )
        except Exception as e:
            logger.error("CohereProvider._make_request failed: %s", e)
            raise


# =============================================================================
# PROVIDER FACTORY
# =============================================================================

class ProviderFactory:
    """Single dispatch point replacing 5 duplicate functions"""

    def __init__(self):
        try:
            with open('directory_map.yaml', 'r') as f:
                self.paths = yaml.safe_load(f)
        except FileNotFoundError as e:
            logger.error("directory_map.yaml not found: %s", e)
            raise
        except Exception as e:
            logger.error("Failed to load directory_map.yaml: %s", e)
            raise

        self.providers = {
            'openai': OpenAIProvider,
            'claude': ClaudeProvider,
            'anthropic': ClaudeProvider,  # Alias
            'gemini': GeminiProvider,
            'mistral': MistralProvider,
            'cohere': CohereProvider
        }

    def get_provider(self, name: str) -> Optional[ProviderProtocol]:
        """Factory method replacing duplicate dispatch logic"""
        provider_class = self.providers.get(name.lower())
        if not provider_class:
            raise ValueError(f"Unknown provider: {name}")

        provider = provider_class()
        if not provider.validate_api_key():
            return None

        return provider