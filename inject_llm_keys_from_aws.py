#!/usr/bin/env python3
# =============================================================================
# =============================================================================
# 
# function_number: "fr_17"
# error_code_number: "ec_01"
# test_case_number: "tc_001"
#
# uses_classes:
# depends_on_interfaces:
#
# internal_modules: []
# external_libraries: ["boto3", "json", "os", "pathlib", "dotenv"]
# database_connections: []
# redis_connections: []
#
# canonization_status: "CANONIZED"
# canonization_date: "2025-09-29"
# canonization_authority: "GPS Foundation"
# change_authorization_required: true
# =============================================================================

import os
import json
import boto3
from botocore.exceptions import ClientError, NoCredentialsError

class SecretsInjector:
    def __init__(self, region='ap-southeast-2', profile=None, fernet_key=None):
        self.region = region
        self.profile = profile
        
        # Load .env file if exists
        self._load_env_file()
        
        # Get Fernet key
        self.fernet_key = fernet_key or os.getenv('FERNET_KEY')
        
        # Use default profile if none specified
        if profile:
            self.session = boto3.Session(region_name=region, profile_name=profile)
        else:
            self.session = boto3.Session(region_name=region)
        self.client = self.session.client('secretsmanager')
        
        # Map provider secrets to env vars
        self.provider_map = {
            'seekrates_ai/openai_keys': 'OPENAI_API_KEY',
            'seekrates_ai/claude_keys': 'ANTHROPIC_API_KEY',
            'seekrates_ai/mistral_keys': 'MISTRAL_API_KEY',
            'seekrates_ai/gemini_keys': 'GEMINI_API_KEY',
            'seekrates_ai/cohere_keys': 'COHERE_API_KEY',
            "seekrates_ai/deepseek_keys": "DEEPSEEK_API_KEY",
            'seekrates_ai/ollama_keys': 'OLLAMA_API_KEY',
            'seekrates_ai/together_keys': 'TOGETHER_API_KEY',
            'seekrates_ai/grok_keys': 'GROK_API_KEY',
            'seekrates_ai/ai21_keys': 'AI21_API_KEY',
        }
    
    def _load_env_file(self):
        """Load .env file if it exists"""
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            # python-dotenv not installed, try manual load
            env_path = '.env'
            if os.path.exists(env_path):
                with open(env_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            key, value = line.split('=', 1)
                            os.environ[key.strip()] = value.strip()
    
    def decrypt_key(self, encrypted_key: str) -> str:
        """Decrypt - supports BOTH old and new encryption methods"""
        import base64
        from cryptography.fernet import Fernet
        
        if not self.fernet_key or not encrypted_key:
            return encrypted_key
        
        # Strip emoji if present
        clean_key = encrypted_key.lstrip('🔒')
        
        # Try NEW method (base64 derivation - matches secrets_manager.py)
        try:
            key = base64.urlsafe_b64encode(self.fernet_key[:32].encode())
            f = Fernet(key)
            return f.decrypt(clean_key.encode()).decode()
        except:
            pass
        
        # Try OLD method (direct encoding)
        try:
            f = Fernet(self.fernet_key.encode())
            return f.decrypt(clean_key.encode()).decode()
        except:
            pass
        
        return encrypted_key  # Failed both methods

    def inject_provider(self, secret_id: str, env_var: str):
        """Inject single provider key"""
        try:
            response = self.client.get_secret_value(SecretId=secret_id)
            secret = json.loads(response['SecretString'])
            
            # Find the API key in the secret (look for *_KEYS_ENC or *_KEY patterns)
            for key, value in secret.items():
                if 'key' in key.lower() and value:
                    # Handle both string and list values
                    if isinstance(value, list):
                        # Take first key if list
                        if len(value) > 0:
                            decrypted = self.decrypt_key(value[0])
                            os.environ[env_var] = str(decrypted)
                            # print(f"✅ Injected AAA: {env_var}")
                            return True
                    else:
                        # String value
                        decrypted = self.decrypt_key(value)
                        os.environ[env_var] = str(decrypted)
                        # print(f"✅ Injected AAA: {env_var}")
                        return True
            
            print(f"⚠️  No key found in {secret_id}")
            return False
            
        except ClientError as e:
            print(f"⚠️  {secret_id}: {e.response['Error']['Code']}")
            return False
        except Exception as e:
            print(f"⚠️  {secret_id}: {str(e)}")
            return False
    
    def inject_all_providers(self):
        """Inject all provider keys from separate secrets"""
        success_count = 0
        
        for secret_id, env_var in self.provider_map.items():
            if self.inject_provider(secret_id, env_var):
                success_count += 1
        
        # print(f"\n✅ Injected AAA {success_count}/{len(self.provider_map)} providers")
        
        # ADD THIS BLOCK:
        # try:
            # if self.inject_gmail_credentials():
                # print("✅ Injected AAA: EMAIL_PASSWORD (Gmail SMTP)")
        # except Exception as e:
            # print(f"⚠️  Gmail: {e}")
        
        return success_count >= 4
