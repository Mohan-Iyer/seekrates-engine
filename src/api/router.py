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
# defines_classes: "None"
# defines_functions: "None"
# =============================================================================
# DEPENDENCIES:
# =============================================================================
# =============================================================================
# FIELD CONTRACTS:
# =============================================================================
# === END OF SCRIPT DNA HEADER ====================================

import json
import time
import traceback
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
import yaml
from src.api.billing_endpoints import router as billing_router

# Load paths from directory_map.yaml
with open('directory_map.yaml', 'r') as f:
    directory_map = yaml.safe_load(f)

# Import contracts and engine
from src.transformers.contracts import FrontendRequest, BackendResponse
from src.core.engine import ConsensusEngine
from src.transformers.response_transformer import ResponseTransformer

# Import authentication services
# from src.auth.otp_service import OTPService
from src.auth.user_manager import UserManager

# Import auth endpoints - THIS LINE IS REQUIRED
from src.api.auth_endpoints import router as imported_auth_router

# Create router instance
router = APIRouter()
# ✅ DIAGNOSTIC - CORRECTED VERSION:
print("[ROUTER-INIT] router.py loaded, APIRouter created")
print(f"[ROUTER-INIT] About to include auth_router from auth_endpoints")
from src.api.auth_endpoints import router as imported_auth_router  # ← FIXED!
print(f"[ROUTER-INIT] auth_router imported successfully: {type(imported_auth_router)}")

# Include auth router
router.include_router(imported_auth_router, tags=["auth"])
router.include_router(billing_router, tags=["billing"])
print(f"[ROUTER-INIT] auth_router included, routes: {[r.path for r in imported_auth_router.routes]}")
print(f"[ROUTER-INIT] auth_router included, routes: {[r.path for r in imported_auth_router.routes]}")
print(f"🔍 [ROUTER DEBUG] auth_router included")
print(f"🔍 [ROUTER DEBUG] auth_router routes: {[r.path for r in imported_auth_router.routes]}")

# Initialize components
engine = ConsensusEngine()
transformer = ResponseTransformer()

# Initialize authentication services
# otp_service = OTPService()
user_manager = UserManager()

