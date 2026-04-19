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
# defines_classes: "EventStoreError, EventAppendError, EventReplayError, EventStore"
# defines_functions: "__init__, get_session, append_consensus_decision, append_gps_error, append_agent_interaction, append_event, get_events, get_consensus_history, get_gps_error_history, replay_events, get_latest_sequence, get_aggregate_state, health_check"
# =============================================================================
# DEPENDENCIES:
# =============================================================================
# =============================================================================
# FIELD CONTRACTS:
# =============================================================================
#   input_sources:
#     - path: "directory_map.yaml"
#       type: "YAML_Config"
#     - path: "core/database.py"
#       type: "SQLAlchemy_Database"
#   output_destinations:
#     - path: "Event tables"
#       type: "SQLAlchemy_Database"
#     - path: "src/telemetry/telemetry_logger.py"
#       type: "AggregateState"
# =============================================================================
# CHANGE LOG:
# =============================================================================
# v2.0.0 - 2026-02-26: HAL-001 sprint — 5 return type violations fixed.
# v1.0.0 - 2026-02-25: Initial production release.
# === END OF SCRIPT DNA HEADER ====================================

import json
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Union, TypedDict
from contextlib import contextmanager

from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

# =============================================================================
# GPS FOUNDATION COMPLIANT IMPORTS
# =============================================================================

import sys
import os
from pathlib import Path
import yaml


# =============================================================================
# HAL-001 SPRINT TYPES (v2.0.0)
# =============================================================================

class ConsensusHistoryEntry(TypedDict):
    """Return list item for get_consensus_history."""
    event_id: str
    gps_coordinate: Optional[str]
    consensus_result: Optional[Any]   # HAL-001-DEFERRED [TYPE-C]: schema owned by consensus engine
    agent_votes: Optional[Any]        # HAL-001-DEFERRED [TYPE-C]: schema owned by consensus engine
    timestamp: str
    metadata: Optional[Any]           # HAL-001-DEFERRED [TYPE-B]: open accumulator


class GpsErrorEntry(TypedDict):
    """Return list item for get_gps_error_history."""
    event_id: str
    gps_coordinate: Optional[str]
    error_type: Optional[str]
    error_message: Optional[str]
    fix_strategy: Optional[Any]       # HAL-001-DEFERRED [TYPE-B]: open fix strategy accumulator
    timestamp: str


class ReplayEventEntry(TypedDict):
    """Return list item for replay_events."""
    event_id: str
    event_type: str
    event_data: Any                   # HAL-001-DEFERRED [TYPE-B]: intentionally polymorphic — varies per event_type
    aggregate_id: str
    aggregate_type: str
    version: int
    timestamp: str
    metadata: Any                     # HAL-001-DEFERRED [TYPE-B]: open accumulator


class AggregateState(TypedDict):
    """Return of get_aggregate_state."""
    aggregate_id: str
    event_count: int
    last_updated: Optional[str]
    events: List[ReplayEventEntry]
    gps_foundation_compliant: bool


class HealthCheckResult(TypedDict, total=False):
    """Return of health_check — covers healthy (9 keys) and unhealthy (4 keys) paths."""
    status: str                        # always present: 'healthy' or 'unhealthy'
    gps_coordinate: str                # always present
    timestamp: str                     # always present
    gps_foundation_compliant: bool     # healthy path only
    total_events: int                  # healthy path only
    consensus_decisions: int           # healthy path only
    gps_errors: int                    # healthy path only
    recent_events_1h: int              # healthy path only
    database_connection: str           # healthy path only
    error: str                         # unhealthy path only


# =============================================================================
def get_path(key: str, fallback: str = None) -> str:
    """GPS Foundation compliant path resolver using directory_map.yaml"""
    try:
        # Locate directory_map.yaml from project root
        current_file = Path(__file__).resolve()
        project_root = current_file.parent.parent.parent
        map_file = project_root / "directory_map.yaml"
        
        if map_file.exists():
            with open(map_file, 'r') as f:
                dir_map = yaml.safe_load(f) or {}
            
            # Flatten nested structures
            flattened_map = {}
            for k, v in dir_map.items():
                if isinstance(v, str):
                    flattened_map[k] = v
                elif isinstance(v, dict):
                    for nested_k, nested_v in v.items():
                        if isinstance(nested_v, str):
                            flattened_map[nested_k] = nested_v
            
            return flattened_map.get(key, fallback or key)
        else:
            return fallback or key
            
    except Exception:
        return fallback or key

# Add project root to Python path using GPS compliant path resolution
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# GPS compliant core module imports
core_path = Path(get_path("core_modules", "src/core"))
if core_path.exists():
    sys.path.append(str(core_path.parent))

# Import database module using GPS compliant path resolution
try:
    from core.database import Event, AgentInteraction, Checkpoint, DATABASE_URL, engine
except ImportError:
    # Fallback for development
    from database import Event, AgentInteraction, Checkpoint, DATABASE_URL, engine

class EventStoreError(Exception):
    """Base exception for event store operations"""
    pass

class EventAppendError(EventStoreError):
    """Raised when event append fails"""
    pass

class EventReplayError(EventStoreError):
    """Raised when event replay fails"""
    pass

class EventStore:
    """
    GPS Foundation Event Store with PostgreSQL backend
    Provides immutable audit trail and event replay capabilities for all consensus decisions
    
    GPS Coordinate: fn_01_uc_01_ec_01_tc_001
    Purpose: Core infrastructure for autonomous build agent event sourcing
    """
    
    def __init__(self, database_url: str = DATABASE_URL):
        """Initialize event store with GPS Foundation compliance"""
        self.engine = engine
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.gps_coordinate = "fn_01_uc_01_ec_01_tc_001"
    
    @contextmanager
    def get_session(self):
        """Context manager for database sessions with automatic cleanup"""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            raise
        finally:
            session.close()
    
    def append_consensus_decision(
        self,
        session_id: str,
        gps_coordinate: str,
        agent_votes: Dict[str, Dict[str, Any]],  # HAL-001-DEFERRED [TYPE-C]: inner schema owned by consensus_engine
        consensus_result: Dict[str, Any],          # HAL-001-DEFERRED [TYPE-C]: shape owned by consensus engine output
        metadata: Optional[Dict[str, Any]] = None  # HAL-001-DEFERRED [TYPE-B]: open accumulator, caller-controlled keys
    ) -> str:
        """
        GPS Foundation: Log consensus decisions with surgical precision
        
        Args:
            session_id: Unique session identifier
            gps_coordinate: GPS coordinate for surgical error tracking
            agent_votes: Individual agent voting results
            consensus_result: Final consensus decision
            metadata: Additional metadata (timing, confidence, etc.)
            
        Returns:
            event_id: Unique identifier for the consensus event
        """
        consensus_data = {
            "gps_coordinate": gps_coordinate,
            "agent_votes": agent_votes,
            "consensus_result": consensus_result,
            "decision_timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        return self.append_event(
            event_type="consensus_decision",
            aggregate_id=session_id,
            event_data=consensus_data,
            metadata=metadata,
            aggregate_type="autonomous_build_agent"
        )
    
    def append_gps_error(
        self,
        session_id: str,
        gps_coordinate: str,
        error_type: str,
        error_message: str,
        fix_strategy: Optional[Dict[str, Any]] = None,  # HAL-001-DEFERRED [TYPE-B]: open fix strategy accumulator
        metadata: Optional[Dict[str, Any]] = None        # HAL-001-DEFERRED [TYPE-B]: open accumulator, caller-controlled keys
    ) -> str:
        """
        GPS Foundation: Log GPS-tracked errors for autonomous fixing
        
        Args:
            session_id: Session identifier
            gps_coordinate: Precise GPS error location
            error_type: Classification of error
            error_message: Error details
            fix_strategy: Proposed autonomous fix strategy
            metadata: Additional error context
        """
        error_data = {
            "gps_coordinate": gps_coordinate,
            "error_type": error_type,
            "error_message": error_message,
            "fix_strategy": fix_strategy,
            "error_timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        return self.append_event(
            event_type="gps_error",
            aggregate_id=session_id,
            event_data=error_data,
            metadata=metadata,
            aggregate_type="gps_error_tracking"
        )
    
    def append_agent_interaction(
        self,
        session_id: str,
        agent_id: str,
        interaction_type: str,
        request_data: Dict[str, Any],            # HAL-001-DEFERRED [TYPE-C]: shape owned by calling agent
        response_data: Dict[str, Any],            # HAL-001-DEFERRED [TYPE-C]: shape owned by calling agent
        metadata: Optional[Dict[str, Any]] = None # HAL-001-DEFERRED [TYPE-B]: open accumulator
    ) -> str:
        """
        GPS Foundation: Log agent interactions for consensus tracking
        """
        interaction_data = {
            "agent_id": agent_id,
            "interaction_type": interaction_type,
            "request_data": request_data,
            "response_data": response_data,
            "interaction_timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        return self.append_event(
            event_type="agent_interaction",
            aggregate_id=session_id,
            event_data=interaction_data,
            metadata=metadata,
            aggregate_type="multi_agent_consensus"
        )
    
    def append_event(
        self,
        event_type: str,
        aggregate_id: str,
        event_data: Dict[str, Any],               # HAL-001-DEFERRED [TYPE-B]: intentionally polymorphic — shape varies per event_type
        event_version: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None, # HAL-001-DEFERRED [TYPE-B]: open accumulator, caller-controlled keys
        aggregate_type: str = "autonomous_build_agent"
    ) -> str:
        """
        Append new event to the immutable event store
        
        Args:
            event_type: Type of event (e.g., 'consensus_decision', 'gps_error', 'agent_interaction')
            aggregate_id: Unique identifier for the aggregate (e.g., session_id)
            event_data: Event payload data
            event_version: Event schema version (auto-increments if None)
            metadata: Optional metadata (timestamps, user_id, GPS coordinates, etc.)
            aggregate_type: Type of aggregate
            
        Returns:
            event_id: Unique identifier for the appended event
            
        Raises:
            EventAppendError: If event cannot be appended
        """
        try:
            with self.get_session() as session:
                event_id = uuid.uuid4()
                
                # Auto-increment version if not provided
                if event_version is None:
                    latest_version = self.get_latest_sequence(aggregate_id)
                    event_version = latest_version + 1
                
                # Add GPS Foundation metadata
                enhanced_metadata = metadata or {}
                enhanced_metadata.update({
                    "event_store_gps": self.gps_coordinate,
                    "event_source": "gps_foundation_event_store",
                    "immutable_audit_trail": True
                })
                
                # Create event record using existing schema
                event = Event(
                    id=event_id,
                    aggregate_id=aggregate_id,
                    aggregate_type=aggregate_type,
                    event_type=event_type,
                    event_data=event_data,
                    event_metadata=enhanced_metadata,
                    version=event_version,
                    created_at=datetime.now(timezone.utc)
                )
                
                session.add(event)
                session.flush()
                
                return str(event_id)
                
        except IntegrityError as e:
            raise EventAppendError(f"Event append failed due to constraint violation: {e}")
        except SQLAlchemyError as e:
            raise EventAppendError(f"Database error during event append: {e}")
        except Exception as e:
            raise EventAppendError(f"Unexpected error during event append: {e}")
    
    def get_events(
        self,
        aggregate_id: Optional[str] = None,
        event_type: Optional[str] = None,
        aggregate_type: Optional[str] = None,
        gps_coordinate: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[Event]:
        """
        Retrieve events from the store with GPS Foundation filtering
        
        Args:
            gps_coordinate: Filter by GPS coordinate for surgical precision
            
        Returns:
            List of events ordered by created_at
        """
        try:
            with self.get_session() as session:
                query = session.query(Event)
                
                # Apply filters
                if aggregate_id:
                    query = query.filter(Event.aggregate_id == aggregate_id)
                if event_type:
                    query = query.filter(Event.event_type == event_type)
                if aggregate_type:
                    query = query.filter(Event.aggregate_type == aggregate_type)
                if gps_coordinate:
                    # Filter by GPS coordinate in event data or metadata
                    query = query.filter(
                        Event.event_data.contains({"gps_coordinate": gps_coordinate})
                    )
                
                # Order by created_at
                query = query.order_by(Event.created_at)
                
                # Apply limit
                if limit:
                    query = query.limit(limit)
                
                return query.all()
                
        except SQLAlchemyError as e:
            raise EventReplayError(f"Database error during event retrieval: {e}")
    
    def get_consensus_history(
        self,
        session_id: str,
        gps_coordinate: Optional[str] = None
    ) -> List[ConsensusHistoryEntry]:
        """
        GPS Foundation: Get consensus decision history for analysis
        """
        events = self.get_events(
            aggregate_id=session_id,
            event_type="consensus_decision",
            gps_coordinate=gps_coordinate
        )
        
        return [
            {
                'event_id': str(event.id),
                'gps_coordinate': event.event_data.get('gps_coordinate'),
                'consensus_result': event.event_data.get('consensus_result'),
                'agent_votes': event.event_data.get('agent_votes'),
                'timestamp': event.created_at.isoformat(),
                'metadata': event.event_metadata
            }
            for event in events
        ]
    
    def get_gps_error_history(
        self,
        gps_coordinate: Optional[str] = None,
        error_type: Optional[str] = None
    ) -> List[GpsErrorEntry]:
        """
        GPS Foundation: Get GPS error history for autonomous fixing
        """
        events = self.get_events(
            event_type="gps_error",
            aggregate_type="gps_error_tracking"
        )
        
        filtered_events = []
        for event in events:
            event_gps = event.event_data.get('gps_coordinate')
            event_error_type = event.event_data.get('error_type')
            
            if gps_coordinate and event_gps != gps_coordinate:
                continue
            if error_type and event_error_type != error_type:
                continue
                
            filtered_events.append({
                'event_id': str(event.id),
                'gps_coordinate': event_gps,
                'error_type': event_error_type,
                'error_message': event.event_data.get('error_message'),
                'fix_strategy': event.event_data.get('fix_strategy'),
                'timestamp': event.created_at.isoformat()
            })
        
        return filtered_events
    
    def replay_events(
        self,
        aggregate_id: str,
        aggregate_type: str = "autonomous_build_agent"
    ) -> List[ReplayEventEntry]:
        """
        Replay events for an aggregate to reconstruct state
        """
        try:
            # Get events and convert to dict within the session context
            with self.get_session() as session:
                query = session.query(Event)
                
                # Apply filters
                query = query.filter(Event.aggregate_id == aggregate_id)
                query = query.filter(Event.aggregate_type == aggregate_type)
                
                # Order by version then created_at
                query = query.order_by(Event.version, Event.created_at)
                
                events = query.all()
                
                # Convert to dict while session is still active
                event_dicts = []
                for event in events:
                    event_dict = {
                        'event_id': str(event.id),
                        'event_type': event.event_type,
                        'event_data': event.event_data,
                        'aggregate_id': event.aggregate_id,
                        'aggregate_type': event.aggregate_type,
                        'version': event.version,
                        'timestamp': event.created_at.isoformat(),
                        'metadata': event.event_metadata or {}
                    }
                    event_dicts.append(event_dict)
                
                return event_dicts
            
        except Exception as e:
            raise EventReplayError(f"Error during event replay: {e}")
    
    def get_latest_sequence(self, aggregate_id: Optional[str] = None) -> int:
        """Get the latest version number for an aggregate"""
        try:
            with self.get_session() as session:
                query = session.query(Event.version)
                
                if aggregate_id:
                    query = query.filter(Event.aggregate_id == aggregate_id)
                
                result = query.order_by(Event.version.desc()).first()
                return result[0] if result else 0
                
        except SQLAlchemyError as e:
            raise EventStoreError(f"Error getting latest sequence: {e}")
    
    def get_aggregate_state(self, aggregate_id: str) -> AggregateState:
        """Get current state of an aggregate by replaying all events"""
        events = self.replay_events(aggregate_id)
        
        state = {
            'aggregate_id': aggregate_id,
            'event_count': len(events),
            'last_updated': events[-1]['timestamp'] if events else None,
            'events': events,
            'gps_foundation_compliant': True
        }
        
        return state
    
    def health_check(self) -> HealthCheckResult:
        """Check event store health and return GPS Foundation diagnostics"""
        try:
            with self.get_session() as session:
                session.execute(text("SELECT 1"))
                
                total_events = session.query(Event).count()
                consensus_events = session.query(Event).filter(
                    Event.event_type == "consensus_decision"
                ).count()
                gps_errors = session.query(Event).filter(
                    Event.event_type == "gps_error"
                ).count()
                
                one_hour_ago = datetime.now(timezone.utc) - datetime.timedelta(hours=1)
                recent_events = session.query(Event).filter(
                    Event.created_at >= one_hour_ago
                ).count()
                
                return {
                    'status': 'healthy',
                    'gps_coordinate': self.gps_coordinate,
                    'gps_foundation_compliant': True,
                    'total_events': total_events,
                    'consensus_decisions': consensus_events,
                    'gps_errors': gps_errors,
                    'recent_events_1h': recent_events,
                    'database_connection': 'ok',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
                
        except Exception as e:
            return {
                'status': 'unhealthy',
                'gps_coordinate': self.gps_coordinate,
                'error': str(e),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

# Global GPS Foundation compliant event store instance
event_store = EventStore()