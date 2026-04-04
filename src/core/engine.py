#!/usr/bin/env python3
# filename: seekrates_engine_production/src/core/engine.py
# =============================================================================
# SCRIPT DNA METADATA - GPS FOUNDATION COMPLIANT
# =============================================================================
# =============================================================================
# PURPOSE AND DESCRIPTION:
# =============================================================================
# =============================================================================
# VERSION HISTORY:
# =============================================================================
# =============================================================================
# DEFINES:
# =============================================================================
# defines_classes: |
# defines_functions: "__init__, orchestrate_consensus, _collect_agent_responses, _call_agent_with_timeout, _calculate_consensus, _format_responses, _find_best_agent"
# =============================================================================
# DEPENDENCIES:
# =============================================================================
# =============================================================================
# FIELD CONTRACTS:
# =============================================================================
#   input_sources:
#     - path: "directory_map.yaml"
#       type: "YAML_Config"
#     - path: "src/agents/provider_factory.py"
#       type: "ProviderFactory"
#     - path: "src/core/consensus_cag.py"
#       type: "build_consensus_summary"
#   output_destinations:
#     - path: "src/agents/consensus_engine.py"
#       type: "EngineResult"
#     - path: "src/api/auth_endpoints.py"
#       type: "EngineResult"
# =============================================================================
# CHANGE LOG:
# =============================================================================
# v2.0.1 - 2026-03-25: CCI_SE_ILL1_TYPEA_02 — project_name corrected
#   seekrates_ai → seekrates_engine.
# v2.0.0 - 2026-02-26: Initial production release with typed local structures.
# === END OF SCRIPT DNA HEADER ====================================

import logging
import yaml
import asyncio
from typing import Dict, List, Any, Optional
from typing_extensions import TypedDict
from pathlib import Path
import time
from datetime import datetime

# Load configuration from directory_map.yaml
with open('directory_map.yaml', 'r') as f:
    directory_map = yaml.safe_load(f)

from src.core.constants import ConsensusConstants

logger = logging.getLogger(__name__)
from src.core.protocols import ScoringProtocol
from src.agents.provider_factory import ProviderFactory
from src.core.consensus_cag import build_consensus_summary, render_consensus_panel
from src.transformers.contracts import ProviderResponseItem

# =============================================================================
# LOCAL TYPES (v2.0.0 — replaces Dict[str, Any] for all known structures)
# =============================================================================

class AgentCallResult(TypedDict, total=False):
    """Single agent call result.
    total=False: error path omits 'response', success path omits 'error'.
    Built in _call_agent_with_timeout L187-199.
    """
    status: str        # 'success' | 'error'
    response: str      # success path only
    confidence: float
    latency_ms: int
    error: str         # error path only


class ConsensusCalcResult(TypedDict):
    """Output of _calculate_consensus.
    Structure fully known — built at L211-217.
    """
    consensus_reached: bool
    agreement_percentage: float
    threshold: float
    decision_id: str
    timestamp: str


class BestAgentResult(TypedDict):
    """Output of _find_best_agent.
    Structure fully known — built at L245-248.
    """
    agent: str
    score: float
    champion: Optional[str]


class EngineMetadata(TypedDict):
    """Metadata block inside EngineResultData.
    Structure fully known — built at L122-126.
    """
    gps_coordinate: str
    agents_count: int
    consensus_achieved: bool


class EngineResultData(TypedDict):
    """The 'result' sub-dict in a successful EngineResult.
    Structure known from orchestrate_consensus L114-127.
    """
    consensus_panel: Dict[str, str]          # {'panel': panel_text}
    summary_text: str
    responses: List[ProviderResponseItem]
    best_agent: BestAgentResult
    # HAL-001-DEFERRED: summary['telemetry'] from consensus_cag.py — not yet examined
    metrics: Dict[str, Any]  # HAL-001-DEFERRED [ARCH_EXCEPTION] EX-SE-022
    metadata: EngineMetadata


class EngineResult(TypedDict, total=False):
    """Return type of orchestrate_consensus.
    total=False: error path has status+error only, success path has status+result.
    """
    status: str
    result: EngineResultData
    error: str


# =============================================================================
# ENGINE
# =============================================================================

class ConsensusEngine:
    """Main orchestration engine for multi-agent consensus."""

    def __init__(self):
        # Load configuration from directory_map.yaml
        try:
            with open('directory_map.yaml', 'r') as f:
                self.paths = yaml.safe_load(f)
        except FileNotFoundError as e:
            logger.error("directory_map.yaml not found: %s", e)
            raise
        except Exception as e:
            logger.error("Failed to load directory_map.yaml: %s", e)
            raise

        self.provider_factory = ProviderFactory()
        self.constants = ConsensusConstants()

    async def orchestrate_consensus(
        self,
        query: str,
        agents: List[str],
        # HAL-001-DEFERRED: Caller-controlled options — structure not owned by engine
        options: Optional[Dict[str, Any]] = None
    ) -> EngineResult:
        """
        Main orchestration logic - PRESERVED from original consensus_engine.py
        Just moved to src/core for better organization
        """
        options = options or {}

        # Validate minimum agents
        if len(agents) < self.constants.MINIMUM_AGENTS_FOR_CONSENSUS:
            return EngineResult(
                status='error',
                error=f'Minimum {self.constants.MINIMUM_AGENTS_FOR_CONSENSUS} agents required'
            )

        # Collect responses from all agents
        responses = await self._collect_agent_responses(query, agents)

        if not responses:
            return EngineResult(
                status='error',
                error='No agent responses received'
            )

        # Calculate consensus using CAG algorithm
        consensus_calc = self._calculate_consensus(responses)

        # Build consensus summary
        summary = build_consensus_summary(consensus_calc, responses)

        # Generate panel text
        panel_text = render_consensus_panel(summary)

        return EngineResult(
            status='success',
            result=EngineResultData(
                consensus_panel={'panel': panel_text},
                summary_text=panel_text,
                responses=self._format_responses(responses),
                best_agent=self._find_best_agent(responses),
                metrics=summary['telemetry'],
                metadata=EngineMetadata(
                    gps_coordinate='fr_09_uc_02_ec_01_tc_001',
                    agents_count=len(agents),
                    consensus_achieved=summary['consensus']['label'] == 'CONSENSUS_REACHED'
                )
            )
        )

    async def _collect_agent_responses(
        self,
        query: str,
        agents: List[str]
    ) -> Dict[str, AgentCallResult]:
        """Collect responses from all agents in parallel."""
        responses: Dict[str, AgentCallResult] = {}

        # Create tasks for parallel execution
        tasks = []
        for agent in agents:
            provider = self.provider_factory.get_provider(agent)
            if provider:
                task = asyncio.create_task(
                    self._call_agent_with_timeout(provider, query, agent)
                )
                tasks.append((agent, task))

        # Wait for all with timeout
        for agent, task in tasks:
            try:
                response = await asyncio.wait_for(
                    task,
                    timeout=self.constants.TIMEOUT_SECONDS
                )
                responses[agent] = response
            except asyncio.TimeoutError:
                responses[agent] = AgentCallResult(
                    status='error',
                    error='Timeout',
                    confidence=0.0,
                    latency_ms=self.constants.TIMEOUT_SECONDS * 1000
                )
            except Exception as e:
                responses[agent] = AgentCallResult(
                    status='error',
                    error=str(e),
                    confidence=0.0,
                    latency_ms=0
                )

        return responses

    async def _call_agent_with_timeout(
        self,
        provider,
        query: str,
        agent: str
    ) -> AgentCallResult:
        """Call a single agent with timeout."""
        import time
        start_time = time.time()

        try:
            result = await provider.call(query)
            latency_ms = int((time.time() - start_time) * 1000)

            return AgentCallResult(
                status='success',
                response=result.get('response', ''),
                confidence=result.get('confidence', 0.5),
                latency_ms=latency_ms
            )
        except Exception as e:
            return AgentCallResult(
                status='error',
                error=str(e),
                confidence=0.0,
                latency_ms=int((time.time() - start_time) * 1000)
            )

    def _calculate_consensus(
        self,
        responses: Dict[str, AgentCallResult]
    ) -> ConsensusCalcResult:
        """Calculate consensus from responses."""
        successful_count = sum(
            1 for r in responses.values()
            if r.get('status') == 'success'
        )
        total_count = len(responses)

        agreement_percentage = (successful_count / total_count * 100) if total_count > 0 else 0

        return ConsensusCalcResult(
            consensus_reached=agreement_percentage >= self.constants.DEFAULT_CONFIDENCE_THRESHOLD * 100,
            agreement_percentage=agreement_percentage,
            threshold=self.constants.DEFAULT_CONFIDENCE_THRESHOLD * 100,
            decision_id='decision_' + str(int(time.time())),
            timestamp=datetime.now().isoformat()
        )

    def _format_responses(
        self,
        responses: Dict[str, AgentCallResult]
    ) -> List[ProviderResponseItem]:
        """Format responses for output."""
        formatted: List[ProviderResponseItem] = []
        for agent, response in responses.items():
            formatted.append(ProviderResponseItem(
                agent=agent,
                success=response.get('status') == 'success',
                response=response.get('response', ''),
                confidence=response.get('confidence', 0.0),
                latency_ms=response.get('latency_ms', 0),
                word_count=len(response.get('response', '').split())
            ))
        return formatted

    def _find_best_agent(
        self,
        responses: Dict[str, AgentCallResult]
    ) -> BestAgentResult:
        """Find the best performing agent."""
        best_agent = None
        best_confidence = 0.0

        for agent, response in responses.items():
            if response.get('status') == 'success':
                confidence = response.get('confidence', 0.0)
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_agent = agent

        return BestAgentResult(
            agent=best_agent or 'none',
            score=best_confidence,
            champion=best_agent
        )