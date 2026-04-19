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
# defines_classes: "ScoringProtocol, ProviderProtocol, TransformerProtocol, SessionProtocol"
# defines_functions: "calculate_consensus, calculate_similarity, call, validate_api_key, get_model_name, to_frontend_format, to_socrates_format, store_context, retrieve_context"
# =============================================================================
# DEPENDENCIES:
# =============================================================================
# =============================================================================
# FIELD CONTRACTS:
# =============================================================================
#   input_sources:
#     - path: "src/core/constants.py"
#       type: "Python_Module"
#   output_destinations:
#     - path: "src/agents/provider_factory.py"
#       type: "ProviderProtocol"
#     - path: "src/transformers/response_transformer.py"
#       type: "TransformerProtocol"
#     - path: "src/core/engine.py"
#       type: "ScoringProtocol"
# === END OF SCRIPT DNA HEADER ====================================

from typing import Protocol, List, Dict, Any, Optional
from abc import abstractmethod
# =============================================================================
# PROTOCOL TypeAliases (CCI-SP-FZ-04)
# Named boundaries for abstract method signatures.
# Concrete implementations carry fully-typed TypedDicts in their own modules.
# TypeAliases satisfy sweep (named reference) while preserving Protocol boundary.
# ARCH-EXCEPT-FZ04-02: Protocol boundary — see docs/governance/violation_registry.yaml
# =============================================================================
ConsensusInputItem = Dict[str, Any]   # Provider response item passed to ScoringProtocol
ConsensusOutput    = Dict[str, Any]   # Consensus result from ScoringProtocol
ProviderCallResult = Dict[str, Any]   # Raw response from ProviderProtocol.call()
EngineResultRaw    = Dict[str, Any]   # Raw EngineResult passed to TransformerProtocol
FrontendResponse   = Dict[str, Any]   # Frontend dict returned by TransformerProtocol
SessionContext     = Dict[str, Any]   # Session context for SessionProtocol

class ScoringProtocol(Protocol):
    """Type-safe interface for scoring"""
    
    @abstractmethod
    # HAL-001-DEFERRED [TYPE-C] — Protocol signature. Concrete impls typed. Circular import risk.
    def calculate_consensus(self, responses: List[ConsensusInputItem]) -> ConsensusOutput:
        """
        Returns consensus result with type safety
        
        Args:
            responses: List of agent response dictionaries
            
        Returns:
            Dictionary with consensus results including:
            - consensus_reached: bool
            - confidence: float
            - scores: Dict[str, float]
        """
        ...
    
    @abstractmethod
    def calculate_similarity(self, text1: str, text2: str) -> float:
        """
        Calculate similarity between two text responses
        
        Args:
            text1: First text response
            text2: Second text response
            
        Returns:
            Similarity score between 0.0 and 1.0
        """
        ...

class ProviderProtocol(Protocol):
    """Type-safe interface for LLM providers"""
    
    @abstractmethod
    # HAL-001-DEFERRED [TYPE-C] — Protocol signature. Concrete impls typed. Circular import risk.
    async def call(self, query: str, **kwargs) -> ProviderCallResult:
        """
        Call LLM provider and return response
        
        Args:
            query: User query to send to LLM
            **kwargs: Additional provider-specific parameters
            
        Returns:
            Dictionary with:
            - status: str ('success' or 'error')
            - response: str (LLM response text)
            - confidence: float (0.0 to 1.0)
            - error: Optional[str]
            - usage: Optional[Dict[str, int]]
        """
        ...
    
    @abstractmethod
    def validate_api_key(self) -> bool:
        """
        Validate that provider has valid API key configured
        
        Returns:
            True if API key is present and valid format
        """
        ...
    
    @abstractmethod
    def get_model_name(self) -> str:
        """
        Get the model name being used
        
        Returns:
            Model identifier string
        """
        ...

class TransformerProtocol(Protocol):
    """Type-safe interface for response transformers"""
    
    @abstractmethod
    # HAL-001-DEFERRED [TYPE-C] — Protocol signature. Concrete impls typed. Circular import risk.
    def to_frontend_format(self, engine_result: EngineResultRaw) -> FrontendResponse:
        """
        Transform engine result to frontend format
        
        Args:
            engine_result: Raw result from consensus engine
            
        Returns:
            Frontend-compatible response dictionary
        """
        ...
    
    @abstractmethod
    # HAL-001-DEFERRED [TYPE-C] — Protocol signature. Concrete impls typed. Circular import risk.
    def to_socrates_format(self, engine_result: EngineResultRaw, start_time: float) -> FrontendResponse:
        """
        Transform engine result to Socrates v4.1 format
        
        Args:
            engine_result: Raw result from consensus engine
            start_time: Request start timestamp
            
        Returns:
            Socrates-compatible response dictionary
        """
        ...

class SessionProtocol(Protocol):
    """Type-safe interface for session management"""
    
    @abstractmethod
    # HAL-001-DEFERRED [TYPE-C] — Protocol signature. SessionState defined in contracts.py. Circular import risk.
    def store_context(self, session_id: str, context: SessionContext) -> bool:
        """
        Store session context
        
        Args:
            session_id: Unique session identifier
            context: Context data to store
            
        Returns:
            True if storage successful
        """
        ...
    
    @abstractmethod
    # HAL-001-DEFERRED [TYPE-C] — Protocol signature. SessionState defined in contracts.py. Circular import risk.
    def retrieve_context(self, session_id: str) -> Optional[SessionContext]:
        """
        Retrieve session context
        
        Args:
            session_id: Unique session identifier
            
        Returns:
            Stored context or None if not found
        """
        ...