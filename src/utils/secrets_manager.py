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
# defines_classes: "SecretsManager"
# defines_functions: "get_decrypted_key, __init__, _load_api_keys, _get_decrypted_key, encrypt, decrypt, get_api_key, has_api_key, get_available_providers"
# =============================================================================
# DEPENDENCIES:
# =============================================================================
# =============================================================================
# FIELD CONTRACTS:
# =============================================================================
#   input_sources:
#     - path: "environment variables"
#       type: "OS_Environment"
#     - path: ".env file"
#       type: "DotEnv_File"
#   output_destinations:
#     - path: "src/agents/llm_dispatcher.py"
#       type: "Decrypted_API_Keys"
#     - path: "src/agents/provider_factory.py"
#       type: "Decrypted_API_Keys"
# === END OF SCRIPT DNA HEADER ====================================

import os
from pathlib import Path
import base64
import logging
from typing import Optional, Dict

try:
    from cryptography.fernet import Fernet
    FERNET_AVAILABLE = True
except ImportError:
    FERNET_AVAILABLE = False

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent.parent / ".env")
except ImportError:
    pass

logger = logging.getLogger(__name__)

class SecretsManager:
    """
    Secure secrets management for Decision Referee system.
    GPS Coordinate: fn_01_uc_07_ec_01_tc_001
    """
    
    def __init__(self, master_key: str = None):
        """Initialize secrets manager."""
        self.master_key = master_key or os.getenv('ENCRYPTION_KEY', 'dev_default_key')
        self.api_keys = self._load_api_keys()
        
    def _load_api_keys(self) -> Dict[str, Optional[str]]:
        """Load all API keys from environment."""
        return {
            'openai': self._get_decrypted_key('OPENAI_API_KEY'),
            'anthropic': self._get_decrypted_key('ANTHROPIC_API_KEY') or self._get_decrypted_key('CLAUDE_API_KEY'),
            'gemini': self._get_decrypted_key('GEMINI_API_KEY'),
            'mistral': self._get_decrypted_key('MISTRAL_API_KEY'),
            'cohere': self._get_decrypted_key('COHERE_API_KEY'),
            'together': self._get_decrypted_key('TOGETHER_API_KEY')
        }
    
    def _get_decrypted_key(self, key_name: str) -> Optional[str]:
        """Get and decrypt a key from environment."""
        encrypted_key = os.getenv(key_name)
        if encrypted_key:
            return self.decrypt(encrypted_key)
        return None
        
    def encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext string."""
        try:
            if FERNET_AVAILABLE and len(self.master_key) >= 32:
                # Use Fernet encryption if available
                key = base64.urlsafe_b64encode(self.master_key[:32].encode())
                fernet = Fernet(key)
                encrypted = fernet.encrypt(plaintext.encode()).decode()
                return encrypted
            else:
                # Fallback to base64
                encoded = base64.b64encode(plaintext.encode()).decode()
                return encoded
        except Exception as e:
            logger.warning(f"Encryption failed: {e}")
            return plaintext
            
    def decrypt(self, encrypted_text: str) -> str:
        """Decrypt encrypted string."""
        try:
            if not encrypted_text or len(encrypted_text) < 10:
                return encrypted_text
                
            encrypted_data = encrypted_text  # No prefix to remove
            
            if FERNET_AVAILABLE and len(self.master_key) >= 32:
                # Try Fernet decryption
                try:
                    key = base64.urlsafe_b64encode(self.master_key[:32].encode())
                    fernet = Fernet(key)
                    return fernet.decrypt(encrypted_data.encode()).decode()
                except:
                    pass
                    
            # Fallback to base64
            return base64.b64decode(encrypted_data.encode()).decode()
            
        except Exception as e:
            logger.warning(f"Decryption failed: {e}")
            return encrypted_text.replace('Encrypted', '')
    
    def get_api_key(self, provider: str) -> Optional[str]:
        """Get API key for a specific provider."""
        return self.api_keys.get(provider)
    
    def has_api_key(self, provider: str) -> bool:
        """Check if API key exists for a provider."""
        return bool(self.api_keys.get(provider))
    
    def get_available_providers(self) -> list:
        """Get list of providers with valid API keys."""
        return [provider for provider, key in self.api_keys.items() if key]

def get_decrypted_key(key_name: str, encryption_key_env: str = "ENCRYPTION_KEY", env_file: str = ".env") -> str:
    """
    Enhanced function - Decrypt API keys from environment variables or .env files.
    Handles both simple encrypted strings and JSON key pools from AWS Secrets Manager.
    GPS Coordinate: fn_01_uc_07_ec_01_tc_001
    """
    import json
    
    # First check environment variables (AWS Secrets Manager injection)
    encrypted_key = os.getenv(key_name)
    
    # Fallback to .env file if not in environment
    if not encrypted_key:
        env_path = Path(__file__).resolve().parent.parent.parent / env_file
        if env_path.exists():
            try:
                from dotenv import load_dotenv
                load_dotenv(dotenv_path=env_path)
                encrypted_key = os.getenv(key_name)
            except ImportError:
                pass
    
    if not encrypted_key:
        raise ValueError(f"Missing {key_name} in environment or {env_file}")
    
    # Try to parse as JSON (AWS Secrets Manager format)
    try:
        key_data = json.loads(encrypted_key)
        if isinstance(key_data, dict):
            # Handle AWS Secrets Manager JSON format: {"OPENAI_KEYS_ENC": [list]}
            for key_list_name, key_list in key_data.items():
                if isinstance(key_list, list) and len(key_list) > 0:
                    # Use first key from rotation pool
                    encrypted_key = key_list[0]
                    break
            else:
                raise ValueError(f"No valid key list found in JSON for {key_name}")
    except json.JSONDecodeError:
        # Not JSON, treat as simple encrypted string
        pass
    
    # Get encryption key for Fernet decryption
    encryption_key = os.getenv(encryption_key_env)
    if not encryption_key:
        # Try common Fernet key environment variables
        encryption_key = os.getenv('FERNET_KEY') or os.getenv('MASTER_KEY')
    
    if not encryption_key:
        return encrypted_key  # Return as-is if no encryption key
    
    # Use SecretsManager for decryption
    manager = SecretsManager(encryption_key)
    decrypted = manager.decrypt(encrypted_key)
    
    # Verify we got a valid API key format
    if key_name.startswith('OPENAI') and decrypted.startswith('sk-'):
        return decrypted
    elif key_name.startswith('CLAUDE') and 'sk-' in decrypted:
        return decrypted
    elif key_name.startswith('MISTRAL') and len(decrypted) > 20:
        return decrypted
    else:
        # Return decrypted content regardless of format
        return decrypted