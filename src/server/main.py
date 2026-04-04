#!/usr/bin/env python3
# =============================================================================
# SCRIPT DNA METADATA - GPS FOUNDATION COMPLIANT
# =============================================================================
# CORE METADATA:
# =============================================================================
# change_history:
# =============================================================================
# PURPOSE AND DESCRIPTION:
# =============================================================================
# =============================================================================
# DEFINES:
# =============================================================================
# defines_classes: "None"
# defines_functions: "check_dependencies, create_app, verify_redis, verify_environment, verify_api_keys, main, add_no_cache_headers, root, pricing, signup_page"
# =============================================================================
# DEPENDENCIES:
# =============================================================================
# =============================================================================
# FIELD CONTRACTS:
# =============================================================================
#   input_sources:
#     - path: "directory_map.yaml"
#       type: "YAML_Config"
#     - path: "src/api/router.py"
#       type: "APIRouter"
#     - path: "src/api/billing_endpoints.py"
#       type: "APIRouter"
#   output_destinations:
#     - path: "HTTP endpoints"
#       type: "HTTP_Response"
#     - path: "templates/index.html"
#       type: "FileResponse"
# === END OF SCRIPT DNA HEADER ====================================

REQUIRED_PACKAGES = ['pydantic', 'boto3', 'fastapi', 'uvicorn', 'yaml']

def check_dependencies():
    missing = []
    for pkg in REQUIRED_PACKAGES:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"❌ Missing packages: {', '.join(missing)}")
        print(f"   Run: pip install {' '.join(missing)} --break-system-packages")
        exit(1)

check_dependencies()
# =============================================================================
from dotenv import load_dotenv
from pathlib import Path

# Get project root (assuming main.py is in src/server/)
project_root = Path(__file__).parent.parent.parent

# Load .env file with all configuration and credentials
env_file = project_root / ".env"
if env_file.exists():
    load_dotenv(env_file, override=True)

# =============================================================================
# CRITICAL: AWS SECRETS INJECTION (MUST RUN BEFORE LLM IMPORTS)
# =============================================================================
import sys
import os
from pathlib import Path

# Get project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load AWS Secrets Manager BEFORE any LLM library imports
print("\n" + "="*70)
print("🔐 LOADING AWS SECRETS MANAGER")
print("="*70)

try:
    import inject_llm_keys_from_aws
    from inject_llm_keys_from_aws import SecretsInjector  # ✅ Import from ROOT
    injector = SecretsInjector()
    success = injector.inject_all_providers()
    
    if success:
        print("✅ AWS Secrets Manager: 9/9 providers loaded")
        print("🎉 NO MANUAL API KEY EXPORTS NEEDED!")
    else:
        print("⚠️  AWS Secrets Manager: Partial load")
        
except Exception as e:
    print(f"❌ AWS Secrets Manager failed: {e}")
    print("⚠️  Falling back to .env variables")

print("="*70 + "\n")
# Initialize email notifier AFTER secrets are loaded
from src.utils.email_notifier import get_email_notifier
email_notifier = get_email_notifier()
print(f"✅ Email notifier initialized in {email_notifier.email_method} mode")
# In main.py, after line 946:
from src.utils.server_cache import ServerCache
ServerCache.initialize()  # Called ONCE at startup
# =============================================================================
# NOW SAFE TO IMPORT EVERYTHING ELSE
# =============================================================================
import yaml
import logging
from typing import Dict, Any

# Third-party imports
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    redis = None
    REDIS_AVAILABLE = False

# Load configuration from directory_map.yaml
with open(PROJECT_ROOT / 'directory_map.yaml', 'r') as f:
    directory_map = yaml.safe_load(f)

# Extract Redis configuration from directory_map
redis_config = directory_map.get('redis', {})
REDIS_HOST = redis_config.get('host', 'localhost')
REDIS_PORT = redis_config.get('port', 6379)
REDIS_DB = redis_config.get('db', 15)

# Server defaults (can be overridden by environment variables)
DEFAULT_PORT = 8000
DEFAULT_LOG_LEVEL = 'info'

# Internal imports from refactored components
from src.api.router import router
from src.api.billing_endpoints import router as billing_router

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="Decision Referee API",
        version="4.0.0",
        description="Multi-Agent Consensus Engine"
    )
    # =============================================================================
    # NO-CACHE MIDDLEWARE FOR HTML PAGES
    # =============================================================================
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"]
    )
    
    # Include the refactored router FIRST (before static files)
    app.include_router(router, prefix="/api/v1")
    app.include_router(billing_router, prefix="/billing")
    from src.api.consensuspress_endpoints import router as consensuspress_router
    app.include_router(consensuspress_router)
    print("[MAIN-INIT] About to register router from router.py")

    @app.get("/health")
    async def health_check():
        return {"status": "ok", "version": "3.1.1"}

    return app
# =============================================================================
# PRE-FLIGHT VERIFICATION
# =============================================================================

def verify_redis() -> bool:
    """Verify Redis connectivity on db 15."""
    if not REDIS_AVAILABLE:
        # logger.warning("⚠️ Redis module not installed - skipping cache")
        return False
    try:
        client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)
        client.ping()
        logger.info(f"✅ Redis connected (db={REDIS_DB})")
        return True
    except Exception as e:
        logger.error(f"❌ Redis connection failed [GPS: fr_09_uc_11_ec_01_tc_001]: {e}")
        return False

def verify_environment() -> bool:
    """Verify environment and load configuration."""
    # Check directory_map.yaml
    directory_map_path = PROJECT_ROOT / "directory_map.yaml"
    if not directory_map_path.exists():
        logger.error(f"❌ directory_map.yaml not found [GPS: fr_09_uc_11_ec_01_tc_001]")
        return False
    
    try:
        with open(directory_map_path) as f:
            yaml.safe_load(f)
        logger.info("✅ directory_map.yaml loaded")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to load directory_map.yaml [GPS: fr_09_uc_11_ec_01_tc_001]: {e}")
        return False

def verify_api_keys() -> Dict[str, bool]:
    """Check available API keys."""
    keys = {
        'OPENAI_API_KEY': bool(os.getenv('OPENAI_API_KEY')),
        'ANTHROPIC_API_KEY': bool(os.getenv('ANTHROPIC_API_KEY') or os.getenv('CLAUDE_API_KEY')),
        'GEMINI_API_KEY': bool(os.getenv('GEMINI_API_KEY')),
        'MISTRAL_API_KEY': bool(os.getenv('MISTRAL_API_KEY')),
        'COHERE_API_KEY': bool(os.getenv('COHERE_API_KEY'))
    }
    
    available = [k for k, v in keys.items() if v]
    logger.info(f"✅ API keys found: {len(available)}/{len(keys)}")
    return keys

# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    """Run pre-flight checks and start server."""
    logger.info("🚀 seekrates-engine API v1.0.0 - Server Startup")
    logger.debug(f"📍 GPS Coordinate: fr_09_uc_11_ec_01_tc_001")
    
    # Run pre-flight checks
    if not verify_environment():
        sys.exit(1)
    
    if not verify_redis():
        logger.warning("⚠️ Redis not available - continuing without cache")
    
    verify_api_keys()
    
    # Create and start application
    app = create_app()
    
    port = int(os.getenv("PORT", DEFAULT_PORT))
    host = os.getenv("HOST", "0.0.0.0")
    
    logger.info(f"🌐 Starting server on http://{host}:{port}")
    logger.info(f"📚 API docs at http://{host}:{port}/docs")
    

    uvicorn.run(app, host=host, port=port, log_level="info")

if __name__ == "__main__":
    main()


# =============================================================================
# OBJECT MODEL METADATA
# =============================================================================
# uses_classes:
#   - FastAPI: Web framework
#   - Router: API endpoints from router.py
#   - Redis: Cache connectivity
# depends_on_interfaces:
#   - router.py: All API endpoints
#   - constants.py: Configuration values
#   - directory_map.yaml: Path resolution
# migration:
#   suggested_category: "infra"
#   migratable: true
#   migration_strategy: "parse_transform"
#   destination_mapping: "src/server/"