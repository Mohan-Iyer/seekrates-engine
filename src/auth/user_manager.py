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
# defines_classes: "UserRegistrationResult, UserSessionData, UserRecord, UserManager"
# defines_functions: "__init__, _ensure_database, create_pending_registration, complete_registration, validate_session, register_user, _create_session, _generate_session_token, _log_action, get_user_by_email, deactivate_user, cleanup_expired_sessions"
# =============================================================================
# DEPENDENCIES:
# =============================================================================
# =============================================================================
# FIELD CONTRACTS:
# =============================================================================
#   input_sources:
#     - path: ".database/users.db"
#       type: "SQLite_Database"
#     - path: "HTTP request data"
#       type: "HTTP_Request"
#   output_destinations:
#     - path: "src/api/auth_endpoints.py"
#       type: "UserRegistrationResult"
#     - path: ".database/users.db"
#       type: "SQLite_Database"
# =============================================================================
# CHANGE LOG:
# =============================================================================
# v3.0.0 - 2026-02-26: HAL-001 sprint — replaced 4 Dict[str, Any] with typed
# v2.0.0 - 2026-02-25: Initial production release.
# === END OF SCRIPT DNA HEADER ====================================

import os
import json
import uuid
import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List, Union, TypedDict
import secrets
import base64

class UserRegistrationResult(TypedDict):
    """Typed return for complete_registration — all fields always present on success."""
    user_id: str
    email: str
    name: str
    role: str
    auth_token: str


class UserSessionData(TypedDict):
    """Typed return for validate_session — all fields always present on success."""
    user_id: str
    email: str
    name: str
    role: str
    session_valid_until: str


class UserRecord(TypedDict, total=False):
    """Typed return for get_user_by_email — last_login may be None."""
    user_id: str
    email: str
    name: str
    role: str
    created_at: str
    last_login: Optional[str]
    is_active: bool


class UserManager:
    """
    User registration and session management system.
    GPS Coordinate: fr_16_uc_01_ec_01_tc_001
    """
    
    def __init__(self, db_path: str = ".database/users.db"):
        """Initialize UserManager with database connection."""
        self.db_path = db_path
        self._ensure_database()
        self._pending_registrations = {}  # In-memory storage for pending registrations
        
    def _ensure_database(self):
        """Ensure database and tables exist."""
        # Create database directory if it doesn't exist
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                role TEXT DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                metadata TEXT
            )
        """)
        
        # Create sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                token TEXT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                ip_address TEXT,
                user_agent TEXT,
                is_active BOOLEAN DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)
        
        # Create audit_log table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                action TEXT NOT NULL,
                details TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ip_address TEXT,
                success BOOLEAN
            )
        """)
        
        conn.commit()
        conn.close()
        
    def create_pending_registration(self, email: str, name: str, otp_code: str) -> str:
        """
        Create a pending registration with OTP.
        
        Args:
            email: User email address
            name: User full name
            otp_code: Generated OTP code
            
        Returns:
            Session token for OTP verification
        """
        session_token = self._generate_session_token()
        
        # Store pending registration in memory
        self._pending_registrations[session_token] = {
            'email': email,
            'name': name,
            'otp_code': otp_code,
            'created_at': datetime.now(timezone.utc),
            'expires_at': datetime.now(timezone.utc) + timedelta(minutes=10)
        }
        
        # Log the attempt
        self._log_action(None, 'registration_initiated', {
            'email': email,
            'session_token': session_token[:8] + '...'
        })
        
        return session_token
        
    def complete_registration(self, session_token: str, otp_code: str) -> Optional[UserRegistrationResult]:
        """
        Complete registration by verifying OTP.
        
        Args:
            session_token: Session token from pending registration
            otp_code: User-provided OTP code
            
        Returns:
            User data if successful, None otherwise
        """
        # Check if pending registration exists
        if session_token not in self._pending_registrations:
            self._log_action(None, 'registration_failed', {'reason': 'invalid_session'})
            return None
            
        pending = self._pending_registrations[session_token]
        
        # Check if expired
        if datetime.now(timezone.utc) > pending['expires_at']:
            del self._pending_registrations[session_token]
            self._log_action(None, 'registration_failed', {'reason': 'expired_otp'})
            return None
            
        # Verify OTP
        if pending['otp_code'] != otp_code:
            self._log_action(None, 'registration_failed', {'reason': 'invalid_otp'})
            return None
            
        # Create user
        user_id = str(uuid.uuid4())
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO users (user_id, email, name, role, created_at, is_active, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                pending['email'],
                pending['name'],
                'user',
                datetime.now(timezone.utc),
                1,
                json.dumps({'registration_method': 'otp', 'three_laws_acknowledged': True})
            ))
            
            conn.commit()
            
            # Clean up pending registration
            del self._pending_registrations[session_token]
            
            # Create session for the new user
            auth_token = self._create_session(user_id)
            
            # Log successful registration
            self._log_action(user_id, 'registration_completed', {
                'email': pending['email']
            }, success=True)
            
            return {
                'user_id': user_id,
                'email': pending['email'],
                'name': pending['name'],
                'role': 'user',
                'auth_token': auth_token
            }
            
        except sqlite3.IntegrityError as e:
            conn.rollback()
            self._log_action(None, 'registration_failed', {
                'reason': 'email_exists',
                'email': pending['email']
            })
            return None
        finally:
            conn.close()
            
    def validate_session(self, auth_token: str) -> Optional[UserSessionData]:
        """
        Validate an authentication token and return user data.
        
        Args:
            auth_token: Authentication token to validate
            
        Returns:
            User data if valid, None otherwise
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Check if session exists and is active
            cursor.execute("""
                SELECT s.user_id, s.expires_at, u.email, u.name, u.role
                FROM sessions s
                JOIN users u ON s.user_id = u.user_id
                WHERE s.token = ? AND s.is_active = 1 AND u.is_active = 1
            """, (auth_token,))
            
            result = cursor.fetchone()
            
            if not result:
                return None
                
            user_id, expires_at, email, name, role = result
            
            # Check if session expired
            expiry = datetime.fromisoformat(expires_at)
            if datetime.now(timezone.utc) > expiry:
                # Deactivate expired session
                cursor.execute("""
                    UPDATE sessions SET is_active = 0 WHERE token = ?
                """, (auth_token,))
                conn.commit()
                return None
                
            # Update last login
            cursor.execute("""
                UPDATE users SET last_login = ? WHERE user_id = ?
            """, (datetime.now(timezone.utc), user_id))
            conn.commit()
            
            return {
                'user_id': user_id,
                'email': email,
                'name': name,
                'role': role,
                'session_valid_until': expires_at
            }
            
        finally:
            conn.close()
            
    def register_user(self, email: str, name: str, role: str = 'user') -> Optional[str]:
        """
        Direct registration without OTP (for admin use).
        
        Args:
            email: User email address
            name: User full name
            role: User role (default 'user')
            
        Returns:
            User ID if successful, None otherwise
        """
        user_id = str(uuid.uuid4())
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO users (user_id, email, name, role, created_at, is_active, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                email,
                name,
                role,
                datetime.now(timezone.utc),
                1,
                json.dumps({'registration_method': 'direct', 'three_laws_acknowledged': True})
            ))
            
            conn.commit()
            
            self._log_action(user_id, 'user_registered_direct', {
                'email': email,
                'role': role
            }, success=True)
            
            return user_id
            
        except sqlite3.IntegrityError:
            conn.rollback()
            return None
        finally:
            conn.close()
            
    def _create_session(self, user_id: str, duration_hours: int = 24) -> str:
        """Create a new session for a user."""
        session_id = str(uuid.uuid4())
        token = self._generate_session_token()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=duration_hours)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO sessions (session_id, user_id, token, expires_at, is_active)
            VALUES (?, ?, ?, ?, ?)
        """, (session_id, user_id, token, expires_at, 1))
        
        conn.commit()
        conn.close()
        
        return token
        
    def _generate_session_token(self) -> str:
        """Generate a secure session token."""
        return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8')
        
    def _log_action(self, user_id: Optional[str], action: str, details: Dict[str, Union[str, int, bool]], 
                   ip_address: str = None, success: bool = False):
        """Log user actions for audit trail."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO audit_log (user_id, action, details, ip_address, success)
            VALUES (?, ?, ?, ?, ?)
        """, (
            user_id,
            action,
            json.dumps(details),
            ip_address,
            success
        ))
        
        conn.commit()
        conn.close()
        
    def get_user_by_email(self, email: str) -> Optional[UserRecord]:
        """Get user data by email address."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT user_id, email, name, role, created_at, last_login, is_active
            FROM users WHERE email = ?
        """, (email,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return {
                'user_id': result[0],
                'email': result[1],
                'name': result[2],
                'role': result[3],
                'created_at': result[4],
                'last_login': result[5],
                'is_active': result[6]
            }
        return None
        
    def deactivate_user(self, user_id: str) -> bool:
        """Deactivate a user account."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE users SET is_active = 0 WHERE user_id = ?
        """, (user_id,))
        
        # Also deactivate all sessions
        cursor.execute("""
            UPDATE sessions SET is_active = 0 WHERE user_id = ?
        """, (user_id,))
        
        conn.commit()
        affected = cursor.rowcount > 0
        conn.close()
        
        if affected:
            self._log_action(user_id, 'user_deactivated', {}, success=True)
            
        return affected
        
    def cleanup_expired_sessions(self):
        """Clean up expired sessions from database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE sessions SET is_active = 0
            WHERE expires_at < ? AND is_active = 1
        """, (datetime.now(timezone.utc),))
        
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        
        if affected > 0:
            self._log_action(None, 'cleanup_sessions', {
                'sessions_cleaned': affected
            }, success=True)
            
        return affected

# Export for easy import
__all__ = ['UserManager']