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
# defines_classes: "ResponseTransformer"
# defines_functions: "__init__, to_frontend_format, to_socrates_format"
# =============================================================================
# DEPENDENCIES:
# =============================================================================
# =============================================================================
# FIELD CONTRACTS:
# =============================================================================
#   input_sources:
#     - path: "src/core/engine.py"
#       type: "EngineResult"
#     - path: "src/transformers/contracts.py"
#       type: "BackendResponse"
#     - path: "directory_map.yaml"
#       type: "YAML_Config"
#   output_destinations:
#     - path: "src/api/auth_endpoints.py"
#       type: "BackendResponse"
#     - path: "src/api/router.py"
#       type: "SocratesResponse"
# =============================================================================
# CHANGE LOG:
# =============================================================================
# v2.0.0 - 2026-02-26: HAL-001 sprint — 2 params annotated HAL-001-DEFERRED.
# v1.0.0 - 2026-02-25: Previous production release.
# === END OF SCRIPT DNA HEADER ====================================

import logging
import yaml
import time
from typing import Dict, Any, List

# Load paths from directory_map.yaml
with open('directory_map.yaml', 'r') as f:
    directory_map = yaml.safe_load(f)

from src.transformers.contracts import BackendResponse, SocratesResponse
from src.core.protocols import TransformerProtocol

logger = logging.getLogger(__name__)

class ResponseTransformer(TransformerProtocol):
    """Transform consensus engine results to various output formats"""
    
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
    
    def to_frontend_format(self, engine_result: Dict[str, Any]) -> BackendResponse:  # HAL-001-DEFERRED: raw consensus engine output — cross-module boundary,
                                                                                       # no fixed schema enforced at transformer layer. Architecturally correct.
        """Transform engine result to frontend format"""
        
        if engine_result.get('status') != 'success':
            # Error response
            return BackendResponse(
                consensus='',
                confidence=0.0,
                panel=[],
                metadata={'error': engine_result.get('error', 'Unknown error')},
                session_id='',
                consensus_panel='',
                participating_agents=[],
                champion=None,
                scores={},
                responses=[],
                metrics={},
                agents_total=0,
                agents_responded=0,
                successful_responses=[],
                agent_status={},
                response_count=0,
                agent_count=0
            )
        
        result_data = engine_result.get('result', {})
        
        # Extract consensus text
        consensus_text = ''
        if 'consensus_panel' in result_data and isinstance(result_data['consensus_panel'], dict):
            consensus_text = result_data['consensus_panel'].get('panel', '')
        elif 'summary_text' in result_data:
            consensus_text = result_data['summary_text']
        
        # Extract participating agents
        responses = result_data.get('responses', [])
        participating_agents = [r['agent'] for r in responses if r.get('success')]
        
        # Extract best agent info
        best_agent = result_data.get('best_agent', {})
        champion = best_agent.get('champion') or best_agent.get('agent')
        
        # Build agent status
        agent_status = {}
        for response in responses:
            agent = response.get('agent', '')
            agent_status[agent] = 'success' if response.get('success') else 'failed'
        
        # Calculate metrics
        successful_responses = [r for r in responses if r.get('success')]
        agents_total = len(set(r.get('agent') for r in responses))
        agents_responded = len(successful_responses)
        
        return BackendResponse(
            consensus=consensus_text,
            confidence=best_agent.get('score', 0.0),
            panel=responses,
            metadata=result_data.get('metadata', {}),
            session_id=result_data.get('metadata', {}).get('session_id', ''),
            consensus_panel=consensus_text,
            participating_agents=participating_agents,
            champion=champion,
            scores={r['agent']: r.get('confidence', 0.0) for r in responses},
            responses=responses,
            metrics=result_data.get('metrics', {}),
            agents_total=agents_total,
            agents_responded=agents_responded,
            successful_responses=successful_responses,
            agent_status=agent_status,
            response_count=agents_responded,
            agent_count=agents_total
        )
    
    def to_socrates_format(self, engine_result: Dict[str, Any], start_time: float) -> SocratesResponse:  # HAL-001-DEFERRED: same as to_frontend_format — cross-module boundary input.
        """Transform engine result to Socrates v4.1 format"""
        
        if engine_result.get('status') != 'success':
            return SocratesResponse(
                success=False,
                responses=[],
                synthesis='Analysis failed.',
                champion=None,
                metrics={'response_count': 0, 'champion_score': 0, 'process_time': 0},
                agents={},
                error=engine_result.get('error', 'Unknown error'),
                trace=None
            )
        
        result_data = engine_result.get('result', {})
        raw_responses = result_data.get('responses', [])
        
        # Build Socrates-format responses
        responses = []
        agent_scores = {}
        
        for response_data in raw_responses:
            agent_name = response_data.get('agent', 'unknown')
            
            if response_data.get('success') and response_data.get('response'):
                content = response_data.get('response', '').strip()
                
                if content:
                    word_count = response_data.get('word_count', len(content.split()))
                    confidence = response_data.get('confidence', 0.5)
                    score = int(min(100, max(0, confidence * 100)))
                    
                    responses.append({
                        'agent': agent_name.replace('_', ' ').title(),
                        'content': content,
                        'word_count': word_count,
                        'score': score,
                        'response_time': response_data.get('latency_ms', 0) / 1000.0
                    })
                    
                    agent_scores[agent_name] = {
                        'score': score,
                        'champion': False
                    }
        
        if not responses:
            return SocratesResponse(
                success=False,
                responses=[],
                synthesis='No valid agent responses received.',
                champion=None,
                metrics={'response_count': 0, 'champion_score': 0, 'process_time': 0},
                agents={},
                error='No valid responses',
                trace=None
            )
        
        # Find champion
        champion_response = max(responses, key=lambda x: x['score'])
        champion = champion_response['agent']
        
        # Update champion flag
        for agent_name in agent_scores:
            agent_scores[agent_name]['champion'] = (
                agent_name.replace('_', ' ').title() == champion
            )
        
        processing_time = time.time() - start_time
        
        # Extract synthesis
        synthesis = result_data.get('summary_text', '')
        if not synthesis and 'consensus_panel' in result_data:
            synthesis = result_data['consensus_panel'].get('panel', '')
        if not synthesis:
            synthesis = f"Expert panel analysis complete with {len(responses)} response(s)."
        
        return SocratesResponse(
            success=True,
            responses=responses,
            synthesis=synthesis,
            champion=champion,
            metrics={
                'response_count': len(responses),
                'total_words': sum(r['word_count'] for r in responses),
                'total_tokens': sum(r.get('tokens', 0) for r in raw_responses),
                'champion_score': champion_response['score'],
                'process_time': round(processing_time, 1)
            },
            agents=agent_scores,
            error=None,
            trace=None
        )