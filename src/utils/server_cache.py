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
# defines_classes: "ServerCache, CacheStats"
# defines_functions: "get_directory_map, get_system_config, get_special_access, get_pricing_tiers, get_telemetry_schema, get_safety_prime, initialize, _find_project_root, get, is_initialized, get_stats, reload"
# =============================================================================
# DEPENDENCIES:
# =============================================================================
# =============================================================================
# FIELD CONTRACTS:
# =============================================================================
#   input_sources:
#     - path: "directory_map.yaml"
#       type: "YAML_Config"
#     - path: "config/system.yaml"
#       type: "YAML_Config"
#     - path: "config/special_access.yaml"
#       type: "YAML_Config"
#   output_destinations:
#     - path: "src/agents/llm_dispatcher.py"
#       type: "SYSTEM_CONFIG_Dict"
#     - path: "src/server/main.py"
#       type: "CacheStats"
# =============================================================================
# CHANGE LOG:
# =============================================================================
# v2.0.0 - 2026-02-26: HAL-001 sprint — 1 return annotation fixed, 7 deferred.
# v1.0.0 - 2026-02-25: Previous production release.
# === END OF SCRIPT DNA HEADER ====================================

"""
Server Cache - In-Memory Configuration Cache
=============================================

PURPOSE:
Load configuration files once at startup, serve from memory.
Eliminates disk I/O on every request.

USAGE:
    from src.utils.server_cache import ServerCache
    
    # At startup (main.py):
    ServerCache.initialize()
    
    # In code:
    config = ServerCache.get('system')
    schema = ServerCache.get('telemetry_schema')

CONVENIENCE FUNCTIONS:
    get_directory_map() -> Dict
    get_system_config() -> Dict
    get_special_access() -> Dict
    get_pricing_tiers() -> Dict
    get_telemetry_schema() -> Dict
    get_safety_prime() -> Dict
"""

import json
import yaml
import time
from pathlib import Path
from typing import Dict, Any, Optional, TypedDict, List

# =============================================================================
# HAL-001 TYPED RESULT CLASSES
# =============================================================================

class CacheStats(TypedDict):
    """Fixed return type for ServerCache.get_stats(). All 5 fields always present."""
    initialized: bool
    init_time_ms: float
    cached_keys: List[str]
    loaded_count: int
    total_count: int


# =============================================================================
# MODULE-LEVEL CACHE (Singleton Pattern)
# =============================================================================
_cache: Dict[str, Any] = {}  # HAL-001-DEFERRED: stores 6 heterogeneous YAML/JSON configs —
                               # architecturally open by design. No shared schema across cached files.
_initialized: bool = False
_init_time_ms: float = 0


class ServerCache:
    """
    In-memory cache for configuration files.
    
    Thread-safe for reads (Python GIL protects dict reads).
    Initialize once at startup, read many times during requests.
    
    CACHED FILES:
    - directory_map: directory_map.yaml
    - system: config/system.yaml
    - special_access: config/special_access.yaml
    - pricing_tiers: config/pricing_tiers.yaml
    - telemetry_schema: docs/telemetry/schema/telemetry_schema.json
    - safety_prime: SAFETY_PRIME.yaml
    """
    
    # File paths relative to project root
    CACHE_FILES = {
        'directory_map': 'directory_map.yaml',
        'system': 'config/system.yaml',
        'special_access': 'config/special_access.yaml',
        'pricing_tiers': 'config/pricing_tiers.yaml',
        'telemetry_schema': 'docs/telemetry/schema/telemetry_schema.json',
        'safety_prime': 'SAFETY_PRIME.yaml',
    }
    
    @classmethod
    def initialize(cls, project_root: Optional[Path] = None) -> bool:
        """
        Load all configuration files into memory.
        
        Call once at server startup (main.py).
        
        Args:
            project_root: Path to project root. Auto-detected if None.
        
        Returns:
            True if all files loaded, False if any failed.
        """
        global _cache, _initialized, _init_time_ms
        
        start_time = time.time()
        
        # Auto-detect project root if not provided
        if project_root is None:
            project_root = cls._find_project_root()
            if project_root is None:
                print("[CACHE] ERROR: Could not find project root (no directory_map.yaml)")
                return False
        
        print(f"[CACHE] Project root: {project_root}")
        print(f"[CACHE] Loading {len(cls.CACHE_FILES)} configuration files...")
        
        success_count = 0
        failed_files = []
        total_bytes = 0
        
        for key, relative_path in cls.CACHE_FILES.items():
            file_path = project_root / relative_path
            
            try:
                if file_path.suffix == '.json':
                    with open(file_path, 'r', encoding='utf-8') as f:
                        _cache[key] = json.load(f)
                else:  # .yaml or .yml
                    with open(file_path, 'r', encoding='utf-8') as f:
                        _cache[key] = yaml.safe_load(f)
                
                file_size = file_path.stat().st_size
                total_bytes += file_size
                print(f"[CACHE] OK {key}: {file_size:,} bytes")
                success_count += 1
                
            except FileNotFoundError:
                print(f"[CACHE] WARN {key}: NOT FOUND at {file_path}")
                failed_files.append(key)
                _cache[key] = None
                
            except json.JSONDecodeError as e:
                print(f"[CACHE] ERROR {key}: Invalid JSON - {e}")
                failed_files.append(key)
                _cache[key] = None
                
            except yaml.YAMLError as e:
                print(f"[CACHE] ERROR {key}: Invalid YAML - {e}")
                failed_files.append(key)
                _cache[key] = None
                
            except Exception as e:
                print(f"[CACHE] ERROR {key}: {type(e).__name__} - {e}")
                failed_files.append(key)
                _cache[key] = None
        
        _init_time_ms = (time.time() - start_time) * 1000
        _initialized = True
        
        print(f"[CACHE] Loaded {success_count}/{len(cls.CACHE_FILES)} files "
              f"({total_bytes:,} bytes) in {_init_time_ms:.1f}ms")
        
        if failed_files:
            print(f"[CACHE] Missing/failed files: {failed_files}")
        
        return len(failed_files) == 0
    
    @classmethod
    def _find_project_root(cls) -> Optional[Path]:
        """Walk up from this file to find directory_map.yaml."""
        current = Path(__file__).resolve()
        while current.parent != current:
            if (current / 'directory_map.yaml').exists():
                return current
            current = current.parent
        return None
    
    @classmethod
    def get(cls, key: str) -> Optional[Dict[str, Any]]:  # HAL-001-DEFERRED: returns any of 6 configs with different structures —
                                                           # no common schema possible at this cache abstraction layer.
        """
        Get cached configuration by key.
        
        Args:
            key: One of 'directory_map', 'system', 'special_access', 
                 'pricing_tiers', 'telemetry_schema', 'safety_prime'
        
        Returns:
            Cached dict or None if key not found/not initialized.
        """
        if not _initialized:
            print(f"[CACHE] WARNING: Cache not initialized, returning None for '{key}'")
            return None
        
        if key not in _cache:
            print(f"[CACHE] WARNING: Unknown key '{key}', valid keys: {list(cls.CACHE_FILES.keys())}")
            return None
        
        return _cache.get(key)
    
    @classmethod
    def is_initialized(cls) -> bool:
        """Check if cache has been initialized."""
        return _initialized
    
    @classmethod
    def get_stats(cls) -> CacheStats:
        """
        Get cache statistics for monitoring.
        
        Returns:
            Dict with initialized, init_time_ms, cached_keys, loaded_count, total_count
        """
        return {
            'initialized': _initialized,
            'init_time_ms': round(_init_time_ms, 2),
            'cached_keys': list(_cache.keys()),
            'loaded_count': sum(1 for v in _cache.values() if v is not None),
            'total_count': len(cls.CACHE_FILES),
        }
    
    @classmethod
    def reload(cls, project_root: Optional[Path] = None) -> bool:
        """
        Force reload all cached files.
        
        Use sparingly - only if config files change at runtime.
        
        Returns:
            True if all files reloaded successfully.
        """
        global _cache, _initialized
        _cache = {}
        _initialized = False
        print("[CACHE] Reloading all configuration files...")
        return cls.initialize(project_root)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================
# These provide backward-compatible access patterns for consumers.

def get_directory_map() -> Optional[Dict[str, Any]]:  # HAL-001-DEFERRED: config structure unique per file — no shared TypedDict.
    """Get cached directory_map.yaml"""
    return ServerCache.get('directory_map')


def get_system_config() -> Optional[Dict[str, Any]]:  # HAL-001-DEFERRED: config structure unique per file — no shared TypedDict.
    """Get cached config/system.yaml"""
    return ServerCache.get('system')


def get_special_access() -> Optional[Dict[str, Any]]:  # HAL-001-DEFERRED: config structure unique per file — no shared TypedDict.
    """Get cached config/special_access.yaml"""
    return ServerCache.get('special_access')


def get_pricing_tiers() -> Optional[Dict[str, Any]]:  # HAL-001-DEFERRED: config structure unique per file — no shared TypedDict.
    """Get cached config/pricing_tiers.yaml"""
    return ServerCache.get('pricing_tiers')


def get_telemetry_schema() -> Optional[Dict[str, Any]]:  # HAL-001-DEFERRED: config structure unique per file — no shared TypedDict.
    """Get cached docs/telemetry/schema/telemetry_schema.json"""
    return ServerCache.get('telemetry_schema')


def get_safety_prime() -> Optional[Dict[str, Any]]:  # HAL-001-DEFERRED: config structure unique per file — no shared TypedDict.
    """Get cached SAFETY_PRIME.yaml"""
    return ServerCache.get('safety_prime')


# =============================================================================
# STANDALONE TEST
# =============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("SERVER CACHE TEST - GPS: fr_23_uc_01_ec_01_tc_001")
    print("=" * 60)
    
    # Initialize
    success = ServerCache.initialize()
    
    print("\n" + "=" * 60)
    print("CACHE STATS")
    print("=" * 60)
    stats = ServerCache.get_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    print("\n" + "=" * 60)
    print("SAMPLE DATA")
    print("=" * 60)
    
    # Test each cached file
    directory_map = get_directory_map()
    if directory_map:
        print(f"  directory_map keys: {list(directory_map.keys())[:5]}...")
    
    system = get_system_config()
    if system:
        print(f"  system.yaml keys: {list(system.keys())[:5]}...")
    
    pricing = get_pricing_tiers()
    if pricing:
        tiers = pricing.get('tiers', {})
        print(f"  pricing_tiers: {list(tiers.keys()) if isinstance(tiers, dict) else 'N/A'}")
    
    safety = get_safety_prime()
    if safety:
        print(f"  safety_prime keys: {list(safety.keys())[:3]}...")
    
    print("\n" + "=" * 60)
    if success:
        print("RESULT: ALL FILES LOADED SUCCESSFULLY")
    else:
        print("RESULT: SOME FILES FAILED - CHECK LOGS ABOVE")
    print("=" * 60)