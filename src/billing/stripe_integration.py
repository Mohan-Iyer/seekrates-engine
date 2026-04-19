#!/usr/bin/env python3
# =============================================================================
# SCRIPT DNA METADATA - GPS FOUNDATION COMPLIANT
# =============================================================================
# CORE METADATA:
# =============================================================================
# filename: seekrates_engine_production/src/billing/stripe_integration.py
# =============================================================================
# PURPOSE AND DESCRIPTION:
# =============================================================================
# =============================================================================
# DEFINES:
# =============================================================================
# defines_classes: "StripeIntegration"
# defines_functions: "get_customer_by_email, create_stripe_customer, insert_customer_db, get_or_create_customer, update_customer_tier_by_stripe_id, get_customer_id_by_stripe_id, upsert_subscription, _ensure_grace_period_column, set_payment_grace_period, get_user_tier_by_email, get_queries_this_month, check_tier_limits, get_stripe_integration"
# =============================================================================
# DEPENDENCIES:
# =============================================================================
# =============================================================================
# FIELD CONTRACTS:
# =============================================================================
#   input_sources:
#     - path: "Stripe API"
#       type: "Webhook_Events"
#     - path: ".database/customers.db"
#       type: "SQLite_Database"
#     - path: "environment variables"
#       type: "OS_Environment"
#   output_destinations:
#     - path: "src/api/billing_endpoints.py"
#       type: "CustomerRecord"
#     - path: "src/api/auth_endpoints.py"
#       type: "TierConfig"
#     - path: ".database/customers.db"
#       type: "SQLite_Database"
# v3.0.0 - 2026-03-25: CCI_SE_ILL1_TYPEA_03 — All 6 Stripe API response boundaries
#   Pydantic-wired. create_subscription: model_validate added (was returning raw).
#   create_billing_portal_session: model_validate moved to happy path (was in except).
#   D-SE-ILL1-TYPEA-01 applied. EX-SE-001 active. project_name corrected.
# v3.5.0 - 2026-04-10: CCI-SE-198 (INDRA-198) — SE-189B-01 + SE-189B-04.
#   SE-189B-01: Retired CP vars comment updated — pro→silver, agency→gold.
#   SE-189B-04: Webhook handlers updated to call cp_billing.upsert_cp_credits_on_webhook()
#   after subscription create/update/delete. CP tier resolved from price_id via
#   cp_billing.resolve_cp_tier_from_price_id(). Option A: api_key = CONSENSUSPRESS_API_KEY.
# === END OF SCRIPT DNA HEADER ====================================

import stripe
import sqlite3
import os
from typing import Dict, Any, Optional, TypedDict
from datetime import datetime
import logging
from pydantic import BaseModel, ValidationError
logger = logging.getLogger(__name__)

# CP billing — credit ledger + webhook tier sync (CCI-SE-198)
from src.billing import cp_billing as _cp_billing

# =============================================================================
# TYPE CONTRACTS (ILL-1 GUARDRAIL — CCI-116-02)
# =============================================================================

class CustomerRecord(TypedDict):
    """Row from customers table. Return type for get_customer_by_email."""
    customer_id: str
    stripe_customer_id: str
    tier: str


class CustomerResult(TypedDict):
    """Return type for get_or_create_customer. Extends CustomerRecord + is_new."""
    customer_id: str
    stripe_customer_id: str
    tier: str
    is_new: bool


class UserTierInfo(TypedDict):
    """Return type for get_user_tier_by_email. Full tier limit info."""
    tier_name: str
    tier_code: str
    max_tokens: int
    queries_per_day: int
    queries_per_month: int
    query_length_chars: int


class TierConfig(TypedDict, total=False):
    """Return type for get_tier_limits. Mirrors TIER_CONFIG dict values.
    total=False: queries_per_day and price_env are None on free tier.
    """
    code: str
    price_env: Optional[str]
    queries_per_month: int
    queries_per_day: Optional[int]
    query_length_chars: int


class WebhookHandlerResult(TypedDict, total=False):
    """Return type for handle_webhook and all _handle_* methods.
    total=False: fields vary per handler path.
    status is always present. All other fields are path-dependent.
    """
    status: str                    # always: 'handled' | 'unhandled'
    action: str                    # handled paths
    type: str                      # unhandled path — Stripe event type
    stripe_customer_id: str
    stripe_subscription_id: str
    tier: str
    db_updated: bool
    subscription_upserted: bool
    subscription_status: str       # _handle_subscription_updated only
    new_tier: str                  # _handle_subscription_deleted only
    customer_id: str               # _handle_payment_succeeded only

# =============================================================================

# =============================================================================
# DATABASE CONFIGURATION
# =============================================================================
DB_PATH = ".database/telemetry.db"

# =============================================================================
# TIER CONFIGURATION
# =============================================================================
# Tier codes: AKO (Acolyte), ORA (Oracle), SAG (Sage)
# Seeker (free) has no Stripe product - handled by absence of subscription

TIER_CONFIG = {
    'seeker': {
        'code': 'SEK',
        'price_env': None,  # Free tier - no Stripe price
        'queries_per_month': 150,
        'queries_per_day': 5,
        'query_length_chars': 500,
    },
    'acolyte': {
        'code': 'AKO',
        'price_env': 'STRIPE_PRICE_AKO',
        'queries_per_month': 100,
        'queries_per_day': None,
        'query_length_chars': 1500,
    },
    'oracle': {
        'code': 'ORA',
        'price_env': 'STRIPE_PRICE_ORA',
        'queries_per_month': 300,
        'queries_per_day': None,
        'query_length_chars': 5000,
    },
    'sage': {
        'code': 'SAG',
        'price_env': 'STRIPE_PRICE_SAG',
        'queries_per_month': 1000,
        'queries_per_day': None,
        'query_length_chars': 10000,
    },
}

# =============================================================================
# DATABASE FUNCTIONS FOR AUTH INTEGRATION
# =============================================================================

def get_customer_by_email(email: str) -> Optional[CustomerRecord]:
    """
    Check if customer exists in DB by email.
    
    Args:
        email: User's email address
        
    Returns:
        Dict with customer_id, stripe_customer_id, tier if exists, None otherwise
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, stripe_customer_id, tier FROM customers WHERE email = ?",
            (email.lower(),)
        )
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'customer_id': row['id'],
                'stripe_customer_id': row['stripe_customer_id'],
                'tier': row['tier']
            }
        return None
    except Exception as e:
        logger.error(f"DB error getting customer by email: {e}")
        return None


def create_stripe_customer(email: str) -> str:
    """
    Create Stripe customer via API.
    
    Args:
        email: User's email address
        
    Returns:
        stripe_customer_id (cus_xxx string)
    """
    stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
    customer = stripe.Customer.create(
        email=email,
        metadata={'source': 'seekrates_otp_registration'}
    )
    logger.info(f"Created Stripe customer: {customer.id} for {email}")
    return customer.id


def insert_customer_db(email: str, stripe_customer_id: str) -> int:
    """
    INSERT new customer into customers table.
    
    Args:
        email: User's email address
        stripe_customer_id: Stripe customer ID (cus_xxx)
        
    Returns:
        customer_id (integer primary key)
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO customers (email, stripe_customer_id, tier) 
               VALUES (?, ?, 'seeker')""",
            (email.lower(), stripe_customer_id)
        )
        customer_id = cursor.lastrowid
        conn.commit()
        conn.close()
        logger.info(f"Inserted customer: id={customer_id}, email={email}")
        return customer_id
    except sqlite3.IntegrityError as e:
        logger.warning(f"Customer already exists: {email} - {e}")
        # Return existing customer
        existing = get_customer_by_email(email)
        return existing['customer_id'] if existing else -1
    except Exception as e:
        logger.error(f"DB error inserting customer: {e}")
        raise


def get_or_create_customer(email: str) -> CustomerResult:
    """
    Idempotent customer creation: get existing or create new.
    
    Args:
        email: User's email address
        
    Returns:
        Dict with customer_id, stripe_customer_id, tier, is_new
    """
    # Check if exists
    existing = get_customer_by_email(email)
    if existing:
        logger.info(f"Returning existing customer for {email}")
        return {**existing, 'is_new': False}
    
    # Create new
    stripe_customer_id = create_stripe_customer(email)
    customer_id = insert_customer_db(email, stripe_customer_id)
    
    return {
        'customer_id': customer_id,
        'stripe_customer_id': stripe_customer_id,
        'tier': 'seeker',
        'is_new': True
    }


def update_customer_tier_by_stripe_id(stripe_customer_id: str, tier: str) -> bool:
    """
    Update customer tier in DB by Stripe customer ID.
    Called by webhook handlers when subscription changes.
    
    Args:
        stripe_customer_id: Stripe customer ID (cus_xxx)
        tier: New tier name (seeker/acolyte/oracle/sage)
        
    Returns:
        True if updated, False if customer not found
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE customers 
               SET tier = ?, updated_at = CURRENT_TIMESTAMP 
               WHERE stripe_customer_id = ?""",
            (tier, stripe_customer_id)
        )
        rows_affected = cursor.rowcount
        conn.commit()
        conn.close()
        
        if rows_affected > 0:
            logger.info(f"Updated tier to '{tier}' for Stripe customer: {stripe_customer_id}")
            return True
        else:
            logger.warning(f"No customer found for Stripe ID: {stripe_customer_id}")
            return False
    except Exception as e:
        logger.error(f"DB error updating customer tier: {e}")
        return False


def get_customer_id_by_stripe_id(stripe_customer_id: str) -> Optional[int]:
    """
    Get internal customer_id by Stripe customer ID.
    Used for FK lookup when inserting subscriptions.
    
    Args:
        stripe_customer_id: Stripe customer ID (cus_xxx)
        
    Returns:
        customer_id (int) or None if not found
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM customers WHERE stripe_customer_id = ?",
            (stripe_customer_id,)
        )
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"DB error getting customer_id: {e}")
        return None


def upsert_subscription(
    stripe_subscription_id: str,
    stripe_customer_id: str,
    tier: str,
    status: str,
    period_start: Optional[int] = None,
    period_end: Optional[int] = None
) -> bool:
    """
    Insert or update subscription record.
    
    Args:
        stripe_subscription_id: Stripe subscription ID (sub_xxx)
        stripe_customer_id: Stripe customer ID (cus_xxx)
        tier: Tier name (acolyte/oracle/sage)
        status: Subscription status (active/canceled/past_due)
        period_start: Unix timestamp of period start
        period_end: Unix timestamp of period end
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Get customer_id FK
        customer_id = get_customer_id_by_stripe_id(stripe_customer_id)
        if not customer_id:
            # Option B (INDRA-179): customer not in DB — retrieve from Stripe and auto-create.
            # Handles subscribers who completed checkout before SE DB was seeded.
            logger.warning(f"Customer not found for {stripe_customer_id} — auto-creating record")
            try:
                stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
                stripe_customer = stripe.Customer.retrieve(stripe_customer_id)
                email: str = stripe_customer.email or ''
            except stripe.error.StripeError as e:
                logger.error(f"Cannot retrieve Stripe customer {stripe_customer_id}: {e}")
                return False
            if not email:
                logger.error(
                    f"Stripe customer {stripe_customer_id} has no email — "
                    "cannot create DB record"
                )
                return False
            insert_customer_db(email=email, stripe_customer_id=stripe_customer_id)
            update_customer_tier_by_stripe_id(stripe_customer_id, tier)
            customer_id = get_customer_id_by_stripe_id(stripe_customer_id)
            if not customer_id:
                logger.error(
                    f"Auto-create failed for {stripe_customer_id} — "
                    "customer_id still None after insert"
                )
                return False
            logger.info(f"Auto-created customer record for {stripe_customer_id} ({email})")
        
        # Convert Unix timestamps to ISO format
        from datetime import datetime as dt
        period_start_dt = dt.utcfromtimestamp(period_start).isoformat() if period_start else None
        period_end_dt = dt.utcfromtimestamp(period_end).isoformat() if period_end else None
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Try INSERT, on conflict UPDATE
        cursor.execute("""
            INSERT INTO subscriptions 
                (customer_id, stripe_subscription_id, tier, status, 
                 current_period_start, current_period_end)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(stripe_subscription_id) DO UPDATE SET
                tier = excluded.tier,
                status = excluded.status,
                current_period_start = excluded.current_period_start,
                current_period_end = excluded.current_period_end,
                updated_at = CURRENT_TIMESTAMP
        """, (customer_id, stripe_subscription_id, tier, status, 
              period_start_dt, period_end_dt))
        
        conn.commit()
        conn.close()
        
        logger.info(f"Upserted subscription: {stripe_subscription_id}, status={status}, tier={tier}")
        return True
    except Exception as e:
        logger.error(f"DB error upserting subscription: {e}")
        return False


def _ensure_grace_period_column() -> None:
    """Ensure payment_grace_until column exists on customers table. Safe to call multiple times."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "ALTER TABLE customers ADD COLUMN payment_grace_until TEXT"
        )
        conn.commit()
        conn.close()
        logger.info("Migration: added payment_grace_until column to customers")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            pass  # Column already exists — expected after first run
        elif "no such table" in str(e).lower():
            pass  # Table not yet created — safe, tables created on first startup
        else:
            logger.error(f"Migration error for payment_grace_until: {e}")
            raise


# Run migration on import — idempotent, safe
_ensure_grace_period_column()


def set_payment_grace_period(stripe_customer_id: str, grace_until_iso: str) -> bool:
    """
    Write 7-day grace period to customers table by stripe_customer_id.
    Returns True if row updated, False if customer not found or on error.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE customers
               SET payment_grace_until = ?, updated_at = CURRENT_TIMESTAMP
               WHERE stripe_customer_id = ?""",
            (grace_until_iso, stripe_customer_id)
        )
        rows_affected = cursor.rowcount
        conn.commit()
        conn.close()
        if rows_affected > 0:
            logger.info(f"Grace period set until {grace_until_iso} for {stripe_customer_id}")
            return True
        else:
            logger.warning(f"set_payment_grace_period: no customer for {stripe_customer_id}")
            return False
    except Exception as e:
        logger.error(f"DB error setting grace period: {e}")
        return False


def get_user_tier_by_email(email: str) -> UserTierInfo:
    """
    Get user's tier info from customers table.
    Returns dict compatible with existing auth_endpoints usage.
    
    Args:
        email: User's email address
        
    Returns:
        Dict with tier_name, max_tokens, queries_per_day, queries_per_month, query_length_chars
    """
    # Default to seeker (free) tier
    default_tier = 'seeker'
    
    # 1. Check special_access.yaml FIRST (whitelist override)
    try:
        import yaml
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        special_access_path = os.path.join(project_root, 'config', 'special_access.yaml')
        
        with open(special_access_path, 'r') as f:
            special_access = yaml.safe_load(f)
        
        for entry in special_access.get('special_access', []):
            if entry.get('email', '').lower() == email.lower():
                tier_name = entry.get('tier', 'seeker')
                print(f"[TIER] Special access: {email} → {tier_name}")
                tier_config = TIER_CONFIG.get(tier_name, TIER_CONFIG['seeker'])
                return {
                    'tier_name': tier_name,
                    'tier_code': tier_config['code'],
                    'max_tokens': tier_config['query_length_chars'],
                    'queries_per_day': tier_config['queries_per_day'],
                    'queries_per_month': tier_config['queries_per_month'],
                    'query_length_chars': tier_config['query_length_chars']
                }
    except Exception as e:
        logger.warning(f"Special access check failed: {e}")
    
    # 2. Fall back to database lookup
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT tier FROM customers WHERE email = ?",
            (email.lower(),)
        )
        row = cursor.fetchone()
        conn.close()
        
        tier_name = row[0] if row else default_tier
    except Exception as e:
        logger.error(f"DB error getting user tier: {e}")
        tier_name = default_tier
    
    
    # Get limits from TIER_CONFIG
    tier_config = TIER_CONFIG.get(tier_name, TIER_CONFIG['seeker'])
    
    return {
        'tier_name': tier_name,
        'tier_code': tier_config['code'],
        'max_tokens': tier_config['query_length_chars'],  # Map to expected field name
        'queries_per_day': tier_config['queries_per_day'],
        'queries_per_month': tier_config['queries_per_month'],
        'query_length_chars': tier_config['query_length_chars']
    }


def get_queries_this_month(email: str) -> int:
    """
    Get count of queries submitted this month by user.
    
    Args:
        email: User's email address
        
    Returns:
        Number of queries this month
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Get first day of current month
        from datetime import datetime as dt
        now = dt.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        
        cursor.execute("""
            SELECT COUNT(*) 
            FROM consensus_results 
            WHERE user_id = ? 
            AND timestamp >= ?
        """, (email.lower(), month_start))
        
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except Exception as e:
        logger.error(f"Error counting monthly queries: {e}")
        return 0


def check_tier_limits(email: str, queries_today: int) -> tuple:
    """
    Check if user is within their tier limits.
    
    Args:
        email: User's email address
        queries_today: Number of queries already made today
        
    Returns:
        Tuple of (allowed: bool, error_message: Optional[str])
    """
    tier_info = get_user_tier_by_email(email)
    tier_name = tier_info['tier_name']
    
    # Seeker: daily limit
    if tier_name == 'seeker':
        daily_limit = tier_info['queries_per_day']
        if daily_limit and queries_today >= daily_limit:
            return (False, f"Daily limit reached ({daily_limit} queries/day). Upgrade to Acolyte for 100 queries/month.")
    
    # Paid tiers: monthly limit
    else:
        monthly_limit = tier_info['queries_per_month']
        if monthly_limit:
            queries_this_month = get_queries_this_month(email)
            if queries_this_month >= monthly_limit:
                if tier_name == 'acolyte':
                    return (False, f"Monthly limit reached ({monthly_limit} queries). Upgrade to Oracle for 300 queries/month.")
                elif tier_name == 'oracle':
                    return (False, f"Monthly limit reached ({monthly_limit} queries). Upgrade to Sage for 1000 queries/month.")
                else:
                    return (False, f"Monthly limit reached ({monthly_limit} queries).")
    
    return (True, None)


# =============================================================================
# TYPEDICTS
# =============================================================================

class CheckoutSessionResult(TypedDict):
    """Typed return from retrieve_checkout_session. Strict subset of Stripe Session fields."""
    session_id:      str   # Stripe session ID (cs_live_... or cs_test_...)
    status:          str   # 'complete' | 'expired' | 'open'
    payment_status:  str   # 'paid' | 'unpaid' | 'no_payment_required'
    customer:        str   # stripe_customer_id (cus_...)
    tier:            str   # from session metadata['tier'], defaults to 'seeker' if absent


class PaymentFailedInvoice(TypedDict):
    """Typed subset of the Stripe Invoice object from the webhook event."""
    customer:            str   # stripe_customer_id (cus_...)
    customer_email:      str   # subscriber's email address
    amount_due:          int   # amount in cents (e.g. 900 = US$9.00)
    hosted_invoice_url:  str   # Stripe-hosted URL for payment retry


class StripeEventData(TypedDict):
    """Typed wrapper for event['data'] dict in webhook events."""
    object: PaymentFailedInvoice


class StripeWebhookEvent(TypedDict):
    """Typed parameter replacing 'event: Dict' in _handle_payment_failed."""
    type: str               # e.g. 'invoice.payment_failed'
    data: StripeEventData   # Contains the invoice object


class PaymentFailedResult(TypedDict):
    """Typed return from _handle_payment_failed."""
    status:             str    # Always 'handled'
    action:             str    # Always 'payment_failed'
    customer_id:        str    # stripe_customer_id
    email_sent:         bool   # True if notification email sent successfully
    grace_period_set:   bool   # True if payment_grace_until written to DB
    grace_until:        str    # ISO datetime of grace period end (or '' if not set)

class StripeCustomerResponse(BaseModel):
    """Pydantic validator for Stripe Customer object at API boundary.
    Fields accessed by callers — confirmed from create_customer usage."""
    id: str
    email: str = ""
    metadata: dict = {}

    class Config:
        extra = "allow"  # Stripe objects have many fields — allow unknown


class StripeSubscriptionResponse(BaseModel):
    """Pydantic validator for Stripe Subscription object at API boundary.
    Covers create_subscription, update_subscription, cancel_subscription."""
    id: str
    customer: str
    status: str
    metadata: dict = {}

    class Config:
        extra = "allow"


class StripeCheckoutSessionResponse(BaseModel):
    """Pydantic validator for Stripe CheckoutSession object at API boundary."""
    id: str
    status: str = ""
    payment_status: str = ""
    customer: str = ""
    metadata: dict = {}

    class Config:
        extra = "allow"


class StripeBillingPortalResponse(BaseModel):
    """Pydantic validator for Stripe BillingPortal Session object at API boundary."""
    id: str
    url: str = ""
    customer: str = ""

    class Config:
        extra = "allow"


class StripeSchemaFailure(BaseModel):
    """Returned when Stripe response fails Pydantic validation."""
    provider: str = "stripe"
    error: str
    raw_type: str

# =============================================================================
# STRIPE INTEGRATION CLASS
# =============================================================================

class StripeIntegration:
    """Stripe payment processing and subscription management for Seekrates AI"""
    
    def __init__(self):
        stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
        self.webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET')
        
        # Price IDs from Railway env vars — no hardcoded fallbacks (INDRA-178 fix).
        # seekrates-engine supports SAG only. AKO and ORA are not valid plugin
        # tiers — no checkout routes, no plugin subscribers below Sage (INDRA-179).
        _sag = os.getenv('STRIPE_PRICE_SAG', '')
        if not _sag:
            logger.error(
                "STRIPE_PRICE_SAG env var missing — tier_by_price lookup will fail. "
                "Set STRIPE_PRICE_SAG on Railway before processing webhooks."
            )
        self.price_ids = {
            'sage': _sag,
        }
        
        # Reverse lookup: price_id -> tier_name
        self.tier_by_price = {v: k for k, v in self.price_ids.items()}
        # CP price IDs managed by cp_billing.py (CCI-SE-198, INDRA-198).
        # CP tier namespace: free / silver / gold (D-36-TIER-NAMES-01).
        # Pro and Agency slugs retired — D-36-TIER-NAMES-01.
        # CP vars: STRIPE_PRICE_CP_SILVER, STRIPE_PRICE_CP_GOLD,
        #          STRIPE_PRICE_CP_PAYG
    
    def get_tier_limits(self, tier: str) -> TierConfig:
        """Get limits for a tier"""
        return TIER_CONFIG.get(tier, TIER_CONFIG['seeker'])
    
    # HAL_DEFER: TYPE-B — Stripe Customer object, Sprint C+1
    def create_customer(self, email: str, user_id: str) -> StripeCustomerResponse:
        """Create or retrieve a Stripe customer"""
        try:
            customer = stripe.Customer.create(
                email=email,
                metadata={
                    'user_id': user_id,
                    'product': 'SK'  # Seekrates product code
                }
            )
            logger.info(f"Created Stripe customer: {customer.id} for user: {user_id}")
            try:
                return StripeCustomerResponse.model_validate(dict(customer))
            except ValidationError as e:
                logger.error("StripeCustomerResponse validation failed: %s", e)
                raise
            return customer
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating customer: {e}")
            raise
    
    def create_subscription(
        self, 
        customer_id: str, 
        tier: str,
        trial_days: int = 0
    # HAL_DEFER: TYPE-B — Stripe Subscription object, Sprint C+1
    ) -> StripeSubscriptionResponse:
        if tier not in self.price_ids:
            raise ValueError(f"Invalid tier: {tier}. Must be one of: {list(self.price_ids.keys())}")
        
        try:
            params = {
                'customer': customer_id,
                'items': [{'price': self.price_ids[tier]}],
                'metadata': {
                    'tier': tier,
                    'tier_code': TIER_CONFIG[tier]['code']
                }
            }
            
            if trial_days > 0:
                params['trial_period_days'] = trial_days
            
            subscription = stripe.Subscription.create(**params)
            logger.info(f"Created subscription: {subscription.id} for tier: {tier}")
            try:
                return StripeSubscriptionResponse.model_validate(dict(subscription))
            except ValidationError as e:
                logger.error("StripeSubscriptionResponse validation failed (create): %s", e)
                raise
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating subscription: {e}")
            raise
    
    def update_subscription(
        self,
        subscription_id: str,
        new_tier: str
    # HAL_DEFER: TYPE-B — Stripe Subscription object, Sprint C+1
    ) -> StripeSubscriptionResponse:
        """Update subscription to a different tier (upgrade/downgrade)"""
        if new_tier not in self.price_ids:
            raise ValueError(f"Invalid tier: {new_tier}. Must be one of: {list(self.price_ids.keys())}")
        
        try:
            subscription = stripe.Subscription.retrieve(subscription_id)
            
            # Update the subscription item with new price
            updated = stripe.Subscription.modify(
                subscription_id,
                items=[{
                    'id': subscription['items']['data'][0].id,
                    'price': self.price_ids[new_tier]
                }],
                metadata={
                    'tier': new_tier,
                    'tier_code': TIER_CONFIG[new_tier]['code']
                }
            )
            
            logger.info(f"Updated subscription {subscription_id} to {new_tier}")
            try:
                return StripeSubscriptionResponse.model_validate(dict(updated))
            except ValidationError as e:
                logger.error("StripeSubscriptionResponse validation failed (update): %s", e)
                raise     
            return updated
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error updating subscription: {e}")
            raise
    
    def cancel_subscription(
        self,
        subscription_id: str,
        immediate: bool = False
    # HAL_DEFER: TYPE-B — Stripe Subscription object, Sprint C+1
    ) -> StripeSubscriptionResponse:
        """Cancel a subscription"""
        try:
            if immediate:
                subscription = stripe.Subscription.delete(subscription_id)
            else:
                subscription = stripe.Subscription.modify(
                    subscription_id,
                    cancel_at_period_end=True
                )
            
            logger.info(f"Cancelled subscription: {subscription_id} (immediate={immediate})")
            try:
                return StripeSubscriptionResponse.model_validate(dict(subscription))
            except ValidationError as e:
                logger.error("StripeSubscriptionResponse validation failed (cancel): %s", e)
                raise
            return subscription
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error cancelling subscription: {e}")
            raise
    
    def get_customer_tier(self, customer_id: str) -> str:
        """Get current tier for a customer based on active subscription"""
        try:
            subscriptions = stripe.Subscription.list(
                customer=customer_id,
                status='active',
                limit=1
            )
            
            if not subscriptions.data:
                return 'seeker'  # No active subscription = free tier
            
            sub = subscriptions.data[0]
            price_id = sub['items']['data'][0]['price']['id']
            
            return self.tier_by_price.get(price_id, 'seeker')
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error getting customer tier: {e}")
            return 'seeker'  # Default to free on error
    
    def create_checkout_session(
        self,
        customer_id: str,
        tier: str,
        success_url: str,
        cancel_url: str
    # HAL_DEFER: TYPE-B — Stripe CheckoutSession object, Sprint C+1
    ) -> StripeCheckoutSessionResponse:
        """Create a Stripe Checkout session for subscription signup"""
        if tier not in self.price_ids:
            raise ValueError(f"Invalid tier: {tier}")
        
        try:
            session = stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=['card'],
                line_items=[{
                    'price': self.price_ids[tier],
                    'quantity': 1,
                }],
                mode='subscription',
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    'tier': tier,
                    'tier_code': TIER_CONFIG[tier]['code']
                }
            )
            logger.info(f"Created checkout session: {session.id}")
            try:
                return StripeCheckoutSessionResponse.model_validate(dict(session))
            except ValidationError as e:
                logger.error("StripeCheckoutSessionResponse validation failed: %s", e)
                raise
            return StripeCheckoutSessionResponse.model_validate(dict(session))
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating checkout session: {e}")
            raise
    
    def create_billing_portal_session(
        self,
        customer_id: str,
        return_url: str
    # HAL_DEFER: TYPE-B — Stripe BillingPortal.Session object, Sprint C+1
    ) -> StripeBillingPortalResponse:
        """Create a Stripe Billing Portal session for self-service management"""
        try:
            session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url
            )
            logger.info(f"Created billing portal session for customer: {customer_id}")
            try:
                return StripeBillingPortalResponse.model_validate(dict(session))
            except ValidationError as e:
                logger.error("StripeBillingPortalResponse validation failed: %s", e)
                raise
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating billing portal: {e}")
            raise
    
    def retrieve_checkout_session(self, session_id: str) -> CheckoutSessionResult:
        """
        Retrieve a Stripe checkout session and return typed subset.
        Called by checkout_success endpoint to verify session legitimacy.
        """
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            metadata = session.metadata or {}
            return CheckoutSessionResult(
                session_id=session.id,
                status=session.status,
                payment_status=session.payment_status,
                customer=session.customer or '',
                tier=metadata.get('tier', 'seeker')
            )
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error retrieving checkout session {session_id}: {e}")
            raise

    def handle_webhook(self, payload: str, signature: str) -> WebhookHandlerResult:
        """Handle Stripe webhook events"""
        try:
            event = stripe.Webhook.construct_event(
                payload, signature, self.webhook_secret
            ).to_dict()

            
            logger.info(f"Received webhook event: {event['type']}")
            
            # Handle specific event types
            handlers = {
                'customer.subscription.created': self._handle_subscription_created,
                'customer.subscription.updated': self._handle_subscription_updated,
                'customer.subscription.deleted': self._handle_subscription_deleted,
                'invoice.payment_succeeded': self._handle_payment_succeeded,
                'invoice.payment_failed': self._handle_payment_failed,
                'checkout.session.completed': self._handle_checkout_completed,
            }
            
            handler = handlers.get(event['type'])
            if handler:
                return handler(event)
            
            return {'status': 'unhandled', 'type': event['type']}
            
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Invalid webhook signature: {e}")
            raise
        except Exception as e:
            logger.error(f"Webhook handling error: {e}")
            raise
    
    def _handle_subscription_created(self, event: Dict) -> WebhookHandlerResult:
        """Handle new subscription creation"""
        subscription = event['data']['object']
        stripe_customer_id = subscription['customer']
        stripe_subscription_id = subscription['id']
        status = subscription['status']
        period_start = subscription.get('current_period_start')
        period_end = subscription.get('current_period_end')
        
        # Derive tier from price_id — safe traversal (INDRA-178 fix).
        # subscription['items'] may be unexpanded in some webhook payloads.
        try:
            items_data = subscription['items']['data'] if subscription.get('items') else []
            price_id = items_data[0]['price']['id'] if items_data else ''
        except (KeyError, IndexError, TypeError) as e:
            logger.error(f"Could not extract price_id from subscription {stripe_subscription_id}: {e}")
            price_id = ''
        tier = self.tier_by_price.get(price_id, 'seeker') if price_id else 'seeker'

        logger.info(
            f"Subscription created: {stripe_subscription_id}, customer={stripe_customer_id}, "
            f"price_id={price_id}, tier={tier}"
        )
        
        # Update customer tier in database
        tier_updated = update_customer_tier_by_stripe_id(stripe_customer_id, tier)
        
        # Insert subscription record
        sub_upserted = upsert_subscription(
            stripe_subscription_id=stripe_subscription_id,
            stripe_customer_id=stripe_customer_id,
            tier=tier,
            status=status,
            period_start=period_start,
            period_end=period_end
        )
        
        # SE-189B-04: Update CP credit ledger on subscription created
        cp_api_key = os.getenv('CONSENSUSPRESS_API_KEY', '')
        if cp_api_key and price_id:
            cp_tier = _cp_billing.resolve_cp_tier_from_price_id(price_id)
            _cp_billing.upsert_cp_credits_on_webhook(cp_api_key, cp_tier)

        return {
            'status': 'handled',
            'action': 'subscription_created',
            'stripe_customer_id': stripe_customer_id,
            'stripe_subscription_id': stripe_subscription_id,
            'tier': tier,
            'db_updated': tier_updated,
            'subscription_upserted': sub_upserted
        }
    
    def _handle_subscription_updated(self, event: Dict) -> WebhookHandlerResult:
        """Handle subscription updates (upgrades/downgrades)"""
        subscription = event['data']['object']
        stripe_customer_id = subscription['customer']
        stripe_subscription_id = subscription['id']
        status = subscription['status']
        period_start = subscription.get('current_period_start')
        period_end = subscription.get('current_period_end')
        
        # Derive tier from price_id — safe traversal (INDRA-178 fix).
        try:
            items_data = subscription['items']['data'] if subscription.get('items') else []
            price_id = items_data[0]['price']['id'] if items_data else ''
        except (KeyError, IndexError, TypeError) as e:
            logger.error(f"Could not extract price_id from subscription {stripe_subscription_id}: {e}")
            price_id = ''
        tier = self.tier_by_price.get(price_id, 'seeker') if price_id else 'seeker'

        logger.info(
            f"Subscription updated: {stripe_subscription_id}, status={status}, "
            f"price_id={price_id}, tier={tier}"
        )
        
        # Update customer tier in database
        tier_updated = update_customer_tier_by_stripe_id(stripe_customer_id, tier)
        
        # Update subscription record
        sub_upserted = upsert_subscription(
            stripe_subscription_id=stripe_subscription_id,
            stripe_customer_id=stripe_customer_id,
            tier=tier,
            status=status,
            period_start=period_start,
            period_end=period_end
        )
        
        # SE-189B-04: Update CP credit ledger on subscription updated
        cp_api_key = os.getenv('CONSENSUSPRESS_API_KEY', '')
        if cp_api_key and price_id:
            cp_tier = _cp_billing.resolve_cp_tier_from_price_id(price_id)
            _cp_billing.upsert_cp_credits_on_webhook(cp_api_key, cp_tier)

        return {
            'status': 'handled',
            'action': 'subscription_updated',
            'stripe_customer_id': stripe_customer_id,
            'stripe_subscription_id': stripe_subscription_id,
            'tier': tier,
            'subscription_status': status,
            'db_updated': tier_updated,
            'subscription_upserted': sub_upserted
        }
    
    def _handle_subscription_deleted(self, event: Dict) -> WebhookHandlerResult:
        """Handle subscription cancellation"""
        subscription = event['data']['object']
        stripe_customer_id = subscription['customer']
        stripe_subscription_id = subscription['id']
        
        logger.info(f"Subscription cancelled: {stripe_subscription_id}")
        
        # Downgrade customer to free tier
        tier_updated = update_customer_tier_by_stripe_id(stripe_customer_id, 'seeker')
        
        # Update subscription status to canceled
        sub_upserted = upsert_subscription(
            stripe_subscription_id=stripe_subscription_id,
            stripe_customer_id=stripe_customer_id,
            tier='seeker',
            status='canceled',
            period_start=subscription.get('current_period_start'),
            period_end=subscription.get('current_period_end')
        )
        
        # SE-189B-04: Revert CP credits to free on cancellation
        cp_api_key = os.getenv('CONSENSUSPRESS_API_KEY', '')
        if cp_api_key:
            _cp_billing.upsert_cp_credits_on_webhook(cp_api_key, 'free')

        return {
            'status': 'handled',
            'action': 'subscription_deleted',
            'stripe_customer_id': stripe_customer_id,
            'stripe_subscription_id': stripe_subscription_id,
            'new_tier': 'seeker',
            'db_updated': tier_updated,
            'subscription_upserted': sub_upserted
        }
    
    def _handle_payment_succeeded(self, event: Dict) -> WebhookHandlerResult:
        """Handle successful payment"""
        invoice = event['data']['object']
        customer_id = invoice['customer']
        
        logger.info(f"Payment succeeded for customer: {customer_id}")
        
        return {
            'status': 'handled',
            'action': 'payment_succeeded',
            'customer_id': customer_id
        }
    
    def _handle_payment_failed(self, event: StripeWebhookEvent) -> PaymentFailedResult:
        """
        Handle invoice.payment_failed webhook event.
        1. Send notification email to subscriber.
        2. Record 7-day grace period in customers table.
        """
        invoice: PaymentFailedInvoice = event['data']['object']
        stripe_customer_id: str = invoice['customer']
        customer_email: str = invoice.get('customer_email', '')
        amount_due: int = invoice.get('amount_due', 0)
        invoice_url: str = invoice.get('hosted_invoice_url', '')

        logger.warning(
            f"Payment failed: customer={stripe_customer_id}, "
            f"email={customer_email}, amount_due={amount_due}"
        )

        # --- Email notification ---
        email_sent: bool = False
        if customer_email:
            try:
                from src.utils.email_notifier import get_email_notifier
                notifier = get_email_notifier()
                amount_display = f"US${amount_due / 100:.2f}"
                retry_button = (
                    f"<p><a href='{invoice_url}' "
                    f"style='background:#0B1E3A;color:#fff;padding:10px 20px;"
                    f"text-decoration:none;border-radius:4px;'>Retry Payment</a></p>"
                    if invoice_url else ""
                )
                html_content = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family: Arial, sans-serif; padding: 20px; color: #333;">
    <h2 style="color: #c0392b;">&#9888; Payment Failed &mdash; Seekrates AI</h2>
    <p>We were unable to process your subscription payment of <strong>{amount_display}</strong>.</p>
    <p>Your access will continue for <strong>7 days</strong> while you update your payment details.</p>
    {retry_button}
    <p style="margin-top: 20px; color: #666; font-size: 12px;">
        If you have questions, reply to this email or contact mohan@pixels.net.nz
    </p>
</body>
</html>"""
                email_sent = notifier._send_email(
                    to_email=customer_email,
                    subject="\u26a0\ufe0f Payment Failed \u2014 Action Required",
                    html_content=html_content
                )
                if email_sent:
                    logger.info(f"Payment failure notification sent to {customer_email}")
                else:
                    logger.error(f"Failed to send payment failure notification to {customer_email}")
            except Exception as e:
                logger.error(f"Email error in _handle_payment_failed: {e}")
                email_sent = False
        else:
            logger.warning(
                f"No customer_email in invoice for {stripe_customer_id} — cannot send notification"
            )

        # --- Grace period ---
        grace_period_set: bool = False
        grace_until: str = ''
        try:
            from datetime import timedelta
            grace_until_dt = datetime.utcnow() + timedelta(days=7)
            grace_until = grace_until_dt.isoformat()
            grace_period_set = set_payment_grace_period(stripe_customer_id, grace_until)
        except Exception as e:
            logger.error(f"Grace period error in _handle_payment_failed: {e}")
            grace_period_set = False

        return PaymentFailedResult(
            status='handled',
            action='payment_failed',
            customer_id=stripe_customer_id,
            email_sent=email_sent,
            grace_period_set=grace_period_set,
            grace_until=grace_until
        )

    
    def _handle_checkout_completed(self, event: Dict) -> WebhookHandlerResult:
        """Handle completed checkout session"""
        session = event['data']['object']
        stripe_customer_id = session['customer']
        tier = session['metadata'].get('tier', 'seeker')
        
        logger.info(f"Checkout completed: customer={stripe_customer_id}, tier={tier}")
        
        # Update customer tier in database
        # Note: subscription.created webhook will also fire, but idempotent
        updated = update_customer_tier_by_stripe_id(stripe_customer_id, tier)
        
        return {
            'status': 'handled',
            'action': 'checkout_completed',
            'stripe_customer_id': stripe_customer_id,
            'tier': tier,
            'db_updated': updated
        }


# =============================================================================
# MODULE-LEVEL SINGLETON
# =============================================================================
_stripe_integration = None

def get_stripe_integration() -> StripeIntegration:
    """Get or create StripeIntegration singleton"""
    global _stripe_integration
    if _stripe_integration is None:
        _stripe_integration = StripeIntegration()
    return _stripe_integration