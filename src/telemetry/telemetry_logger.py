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
# defines_classes: "TelemetryLogger"
# defines_functions: "__new__, __init__, _load_directory_map, _load_schema, _resolve_db_path, _ensure_database_exists, log_event, log_metric, log_error, start_session, end_session"
# =============================================================================
# DEPENDENCIES:
# =============================================================================
# =============================================================================
# FIELD CONTRACTS:
# =============================================================================
#   input_sources:
#     - path: "directory_map.yaml"
#       type: "YAML_Config"
#     - path: "telemetry schema JSON"
#       type: "JSON_Schema"
#   output_destinations:
#     - path: ".database/telemetry.db"
#       type: "SQLite_Database"
#     - path: "src/agents/consensus_engine.py"
#       type: "log_metric_Consumer"
# === END OF SCRIPT DNA HEADER ====================================

import sqlite3
import json
import yaml
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List
import uuid

class TelemetryLogger:
    """Telemetry logger with JSON schema template and directory_map resolution"""
    
    _instance = None
    
    def __new__(cls):
        """Singleton pattern"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self.dm = self._load_directory_map()
        self.schema = self._load_schema()
        self.db_path = self._resolve_db_path()
        self._ensure_database_exists()
        self._initialized = True
    
    def _load_directory_map(self) -> Dict:
        """Load directory map for path resolution"""
        # Walk up to find project root with directory_map.yaml
        current = Path(__file__).resolve()
        while current.parent != current:
            dm_path = current / 'directory_map.yaml'
            if dm_path.exists():
                with open(dm_path, 'r') as f:
                    return yaml.safe_load(f)
            current = current.parent
        
        raise FileNotFoundError("directory_map.yaml not found in project hierarchy")
    
    def _load_schema(self) -> Dict:
        """Load telemetry schema from JSON template"""
        # Find project root (where directory_map.yaml is)
        project_root = Path(__file__).resolve()
        while project_root.parent != project_root:
            if (project_root / 'directory_map.yaml').exists():
                break
            project_root = project_root.parent
        
        # Resolve schema path from directory_map
        if 'telemetry_framework' in self.dm and 'telemetry_schema' in self.dm['telemetry_framework']:
            schema_path = project_root / self.dm['telemetry_framework']['telemetry_schema']
        else:
            # Default path relative to project root
            schema_path = project_root / 'docs/telemetry/schema/telemetry_schema.json'
        
        print(f"[DEBUG] Attempting to load schema from: {schema_path}")
        print(f"[DEBUG] File exists: {schema_path.exists()}")
        
        if not schema_path.exists():
            raise FileNotFoundError(f"Telemetry schema not found at {schema_path}")
        
        with open(schema_path, 'r') as f:
            content = f.read()
            print(f"[DEBUG] File content length: {len(content)}")
            if not content:
                raise ValueError(f"Schema file is empty: {schema_path}")
            return json.loads(content)  # Use json.loads instead of json.load
                
    def _resolve_db_path(self) -> Path:
        """Resolve database path from directory_map"""
        if 'telemetry_framework' in self.dm and 'telemetry_db' in self.dm['telemetry_framework']:
            return Path(self.dm['telemetry_framework']['telemetry_db'])
        
        # Use database directory from directory_map
        db_dir = Path(self.dm.get('database', '.database'))
        return db_dir / 'telemetry.db'
    
    def _ensure_database_exists(self):
        """Create database from JSON schema if it doesn't exist"""
        if self.db_path.exists():
            return
        
        # Ensure directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create database from schema
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        if 'tables' in self.schema:
            for table_name, table in self.schema['tables'].items():
                # Build CREATE TABLE from columns dict
                if 'columns' in table:
                    cols = ", ".join(f"{col} {dtype}" for col, dtype in table['columns'].items())
                    cursor.execute(f"CREATE TABLE IF NOT EXISTS {table_name} ({cols})")
                elif 'create_sql' in table:
                    cursor.execute(table['create_sql'])
                
                # Create indexes if specified
                for index in table.get('indexes', []):
                    cursor.execute(index)
        
        conn.commit()
        conn.close()
        
        print(f"✅ Telemetry database created at {self.db_path}")
        print(f"   Schema version: {self.schema.get('version', 'unknown')}")
    
    def log_event(self, 
                  event_type: str, 
                  component: str, 
                  # HAL-001-DEFERRED [TYPE-C] — Open event data bag, intentionally untyped.
                  data: Dict[str, Any] = None,
                  session_id: Optional[str] = None,
                  gps_coordinate: Optional[str] = None,
                  severity: str = 'INFO',
                  user_id: Optional[str] = None) -> None:
        """Log telemetry event"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO events (
                timestamp, event_type, component, session_id, 
                user_id, data, severity, gps_coordinate
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.utcnow().isoformat(),
            event_type,
            component,
            session_id,
            user_id,
            json.dumps(data) if data else None,
            severity,
            gps_coordinate
        ))
        
        conn.commit()
        conn.close()
    
    def log_metric(self,
                   metric_name: str,
                   metric_value: float,
                   unit: Optional[str] = None,
                   component: Optional[str] = None,
                   session_id: Optional[str] = None,
                   tags: Optional[Dict] = None) -> None:
        """Log numeric metric"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO metrics (
                timestamp, metric_name, metric_value, 
                unit, component, session_id, tags
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.utcnow().isoformat(),
            metric_name,
            metric_value,
            unit,
            component,
            session_id,
            json.dumps(tags) if tags else None
        ))
        
        conn.commit()
        conn.close()
    
    def log_error(self,
                  error_type: str,
                  error_message: str,
                  stack_trace: Optional[str] = None,
                  component: Optional[str] = None,
                  gps_coordinate: Optional[str] = None,
                  session_id: Optional[str] = None) -> None:
        """Log error with GPS tracking"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO errors (
                timestamp, error_type, error_message, 
                stack_trace, component, gps_coordinate, 
                session_id, resolved
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.utcnow().isoformat(),
            error_type,
            error_message,
            stack_trace,
            component,
            gps_coordinate,
            session_id,
            False
        ))
        
        conn.commit()
        conn.close()
    
    def start_session(self,
                      user_id: Optional[str] = None,
                      environment: str = 'production',
                      metadata: Optional[Dict] = None) -> str:
        """Start new telemetry session"""
        session_id = str(uuid.uuid4())
        
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO sessions (
                session_id, start_time, user_id, 
                environment, metadata
            )
            VALUES (?, ?, ?, ?, ?)
        ''', (
            session_id,
            datetime.utcnow().isoformat(),
            user_id,
            environment,
            json.dumps(metadata) if metadata else None
        ))
        
        conn.commit()
        conn.close()
        
        return session_id
    
    def end_session(self, session_id: str) -> None:
        """End telemetry session"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE sessions 
            SET end_time = ?
            WHERE session_id = ?
        ''', (datetime.utcnow().isoformat(), session_id))
        
        conn.commit()
        conn.close()

# Singleton instance
telemetry_logger = TelemetryLogger()

# Export convenience functions
log_event = telemetry_logger.log_event
log_metric = telemetry_logger.log_metric
log_error = telemetry_logger.log_error
start_session = telemetry_logger.start_session
end_session = telemetry_logger.end_session