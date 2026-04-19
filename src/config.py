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
# defines_classes: "ConfigManager"
# defines_functions: "get_api_key, get_user_tier, get_token_limit, check_query_limit, can_upload_documents, has_api_access"
# =============================================================================
# DEPENDENCIES:
# =============================================================================
# =============================================================================
# FIELD CONTRACTS:
# =============================================================================
#   input_sources:
#     - path: "config/special_access.yaml"
#       type: "YAML_Config"
#     - path: "environment variables"
#       type: "OS_Environment"
#   output_destinations:
#     - path: "src/api/auth_endpoints.py"
#       type: "ConfigManager_Instance"
#     - path: "src/agents/llm_dispatcher.py"
#       type: "USE_MOCK_MODE_Bool"
# === END OF SCRIPT DNA HEADER ====================================

import os
import yaml
from pathlib import Path
from typing import Dict, Optional

# Mock mode toggle
USE_MOCK_MODE = False

# LLM providers
DEFAULT_AGENTS = ["openai", "claude", "gemini", "mistral", "cohere", "deepseek"]

API_KEYS = {
    "openai": "OPENAI_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
    "gemini": "GOOGLE_API_KEY", 
    "mistral": "MISTRAL_API_KEY",
    "cohere": "COHERE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY"
}

# Default tier settings
DEFAULT_TIERS = {
    "free": {
        "max_tokens": 500,
        "daily_queries": 5,
        "queries_per_month": 150,
        "document_upload": False,
        "api_access": False
    },
    "pro": {
        "max_tokens": 4000,
        "daily_queries": 100,
        "queries_per_month": 3000,
        "document_upload": True,
        "api_access": True
    },
    "enterprise": {
        "max_tokens": 8000,
        "daily_queries": None,  # Unlimited
        "queries_per_month": None,  # Unlimited
        "document_upload": True,
        "api_access": True
    },
    "unlimited": {
        "max_tokens": 8000,
        "daily_queries": None,  # Unlimited
        "queries_per_month": None,  # Unlimited
        "document_upload": True,
        "api_access": True,
        "special_access": True
    }
}


def get_api_key(provider):
    """Get API key from environment"""
    env_var = API_KEYS.get(provider, "")
    return os.environ.get(env_var, "")


class ConfigManager:
    """Manages user tiers and access levels"""
    
    def __init__(self):
        self.special_access_users = {}
        self.load_special_access()
    
    def load_special_access(self):
        """Load special access configuration from YAML"""
        special_access_file = Path(__file__).parent.parent / "config" / "special_access.yaml"
        
        if not special_access_file.exists():
            print(f"Warning: Special access file not found: {special_access_file}")
            return
        
        try:
            with open(special_access_file, 'r') as f:
                config = yaml.safe_load(f)
            
            if config and 'unlimited_access' in config:
                for user in config['unlimited_access']:
                    email = user.get('email', '').lower()
                    if email and email != 'REPLACE_WITH_ACTUAL_EMAIL'.lower():  # Skip placeholder
                        self.special_access_users[email] = {
                            'tier': user.get('tier', 'unlimited'),
                            'max_tokens': user.get('max_tokens', 8000),
                            'daily_queries': user.get('daily_queries'),
                            'reason': user.get('reason', 'Special access'),
                            'granted_date': user.get('granted_date'),
                            'granted_by': user.get('granted_by')
                        }
                        print(f"Loaded special access for: {email}")
            
        except Exception as e:
            print(f"Error loading special access config: {e}")
    
    def get_user_tier(self, email: str) -> Dict:
        """
        Get tier configuration for a user email
        
        Args:
            email: User's email address
            
        Returns:
            Dictionary with tier settings (max_tokens, daily_queries, etc.)
        """
        # Validate email exists
        if not email:
            print("Warning: get_user_tier called with no email, returning free tier")
            tier_config = DEFAULT_TIERS['free'].copy()
            tier_config['tier_name'] = 'free'
            tier_config['is_special_access'] = False
            return tier_config
        
        email = email.lower().strip()
        
        # Check special access first
        if email in self.special_access_users:
            special_config = self.special_access_users[email]
            tier_name = special_config['tier']
            tier_config = DEFAULT_TIERS.get(tier_name, DEFAULT_TIERS['unlimited']).copy()
            
            # Override with special access settings
            tier_config['max_tokens'] = special_config['max_tokens']
            tier_config['daily_queries'] = special_config['daily_queries']
            tier_config['tier_name'] = tier_name
            tier_config['is_special_access'] = True
            tier_config['reason'] = special_config['reason']
            
            return tier_config
        
        # TODO: Check database for paid tier assignments
        # For now, assume everyone else is free tier
        tier_config = DEFAULT_TIERS['free'].copy()
        tier_config['tier_name'] = 'free'
        tier_config['is_special_access'] = False
        
        return tier_config

        
        # TODO: Check database for paid tier assignments
        # For now, assume everyone else is free tier
        tier_config = DEFAULT_TIERS['free'].copy()
        tier_config['tier_name'] = 'free'
        tier_config['is_special_access'] = False
        
        return tier_config
    
    def check_query_limit(self, email: str, queries_today: int) -> tuple:
        """
        Check if user has exceeded daily query limit
        
        Args:
            email: User's email address
            queries_today: Number of queries submitted today
            
        Returns:
            Tuple of (allowed: bool, message: Optional[str])
        """
        tier = self.get_user_tier(email)
        daily_limit = tier['daily_queries']
        
        # Unlimited access
        if daily_limit is None:
            return True, None
        
        # Check limit
        if queries_today >= daily_limit:
            return False, f"Daily limit reached ({daily_limit} queries). Upgrade to Pro for 100 queries/day."
        
        return True, None
    
    def get_token_limit(self, email: str) -> int:
        """Get maximum tokens per response for user"""
        tier = self.get_user_tier(email)
        return tier['max_tokens']
    
    def can_upload_documents(self, email: str) -> bool:
        """Check if user can upload documents"""
        tier = self.get_user_tier(email)
        return tier.get('document_upload', False)
    
    def has_api_access(self, email: str) -> bool:
        """Check if user has API access"""
        tier = self.get_user_tier(email)
        return tier.get('api_access', False)


# Global config manager instance
config_manager = ConfigManager()


# Convenience functions (maintain backward compatibility)
def get_user_tier(email: str) -> Dict:
    """Get tier configuration for a user (convenience wrapper)"""
    return config_manager.get_user_tier(email)


def get_token_limit(email: str) -> int:
    """Get maximum tokens per response for user"""
    return config_manager.get_token_limit(email)


def check_query_limit(email: str, queries_today: int) -> tuple:
    """Check if user has exceeded daily query limit"""
    return config_manager.check_query_limit(email, queries_today)


def can_upload_documents(email: str) -> bool:
    """Check if user can upload documents"""
    return config_manager.can_upload_documents(email)


def has_api_access(email: str) -> bool:
    """Check if user has API access"""
    return config_manager.has_api_access(email)


# Example usage and testing
if __name__ == "__main__":
    print("Testing Config Manager\n")
    
    # Test special access user
    test_email = "REPLACE_WITH_ACTUAL_EMAIL"  # Replace with actual test email
    tier = get_user_tier(test_email)
    print(f"Email: {test_email}")
    print(f"Tier: {tier['tier_name']}")
    print(f"Max tokens: {tier['max_tokens']}")
    print(f"Daily queries: {tier['daily_queries'] or 'Unlimited'}")
    print(f"Special access: {tier.get('is_special_access', False)}\n")
    
    # Test free tier user
    test_email = "regular_user@example.com"
    tier = get_user_tier(test_email)
    print(f"Email: {test_email}")
    print(f"Tier: {tier['tier_name']}")
    print(f"Max tokens: {tier['max_tokens']}")
    print(f"Daily queries: {tier['daily_queries']}\n")
    
    # Test query limit
    allowed, message = check_query_limit("regular_user@example.com", 3)
    print(f"Query #3 allowed: {allowed}")
    
    allowed, message = check_query_limit("regular_user@example.com", 5)
    print(f"Query #5 allowed: {allowed}")
    if not allowed:
        print(f"Message: {message}")