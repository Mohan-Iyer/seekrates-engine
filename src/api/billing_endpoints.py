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
# defines_classes: "SageWaitlistRequest"
# defines_functions: "_update_customer_use_case, _update_customer_stripe_id, _create_customer_record, stripe_webhook, create_checkout, create_customer_and_checkout, checkout_success, checkout_cancel, billing_portal, get_tiers, get_user_tier, join_sage_waitlist"
# =============================================================================
# DEPENDENCIES:
# =============================================================================
# =============================================================================
# FIELD CONTRACTS:
# =============================================================================
#   input_sources:
#     - path: "src/billing/stripe_integration.py"
#       type: "StripeIntegration"
#     - path: "HTTP request"
#       type: "HTTP_Request"
#   output_destinations:
#     - path: "HTTP_Response"
#       type: "JSON"
#     - path: "Stripe API"
#       type: "Webhook_Events"
# === END OF SCRIPT DNA HEADER ====================================

from fastapi import APIRouter, Request, HTTPException, Header
from typing import Optional
from pydantic import BaseModel, EmailStr
from datetime import datetime
import logging

from src.billing.stripe_integration import (
    get_stripe_integration, 
    TIER_CONFIG,
    get_customer_by_email
)

logger = logging.getLogger(__name__)

def _update_customer_use_case(email: str, use_case: str):
    """Update use_case for existing customer."""
    import sqlite3
    try:
        conn = sqlite3.connect('.database/telemetry.db')
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE customers SET use_case = ?, updated_at = CURRENT_TIMESTAMP WHERE email = ?",
            (use_case, email)
        )
        conn.commit()
        conn.close()
        logger.info(f"[SIGNUP] Updated use_case for {email}")
    except Exception as e:
        logger.error(f"[SIGNUP] Failed to update use_case: {e}")


def _update_customer_stripe_id(email: str, stripe_customer_id: str, use_case: str = None):
    """Update existing customer with Stripe ID."""
    import sqlite3
    try:
        conn = sqlite3.connect('.database/telemetry.db')
        cursor = conn.cursor()
        if use_case:
            cursor.execute(
                """UPDATE customers 
                   SET stripe_customer_id = ?, use_case = ?, updated_at = CURRENT_TIMESTAMP 
                   WHERE email = ?""",
                (stripe_customer_id, use_case, email)
            )
        else:
            cursor.execute(
                """UPDATE customers 
                   SET stripe_customer_id = ?, updated_at = CURRENT_TIMESTAMP 
                   WHERE email = ?""",
                (stripe_customer_id, email)
            )
        conn.commit()
        conn.close()
        logger.info(f"[SIGNUP] Updated stripe_customer_id for {email}")
    except Exception as e:
        logger.error(f"[SIGNUP] Failed to update stripe_customer_id: {e}")


def _create_customer_record(email: str, stripe_customer_id: str, use_case: str = None):
    """Create new customer record."""
    import sqlite3
    try:
        conn = sqlite3.connect('.database/telemetry.db')
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO customers (email, stripe_customer_id, tier, use_case, created_at, updated_at) 
               VALUES (?, ?, 'seeker', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (email, stripe_customer_id, use_case)
        )
        conn.commit()
        conn.close()
        logger.info(f"[SIGNUP] Created customer record for {email}")
    except Exception as e:
        logger.error(f"[SIGNUP] Failed to create customer: {e}")

# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class SageWaitlistRequest(BaseModel):
    """Request model for Sage waitlist signup."""
    email: EmailStr
    use_case: str


# =============================================================================
# ROUTER SETUP
# =============================================================================
router = APIRouter(prefix="/billing", tags=["billing"])

# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("/stripe-webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature")
):
    """
    Receive and process Stripe webhook events.
    
    Stripe sends events for:
    - subscription.created/updated/deleted
    - invoice.payment_succeeded/failed
    - checkout.session.completed
    """
    try:
        # Get raw payload
        payload = await request.body()
        payload_str = payload.decode('utf-8')
        
        if not stripe_signature:
            logger.warning("Webhook received without signature")
            raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")
        
        # Process webhook
        stripe_integration = get_stripe_integration()
        result = stripe_integration.handle_webhook(payload_str, stripe_signature)
        
        logger.info(f"Webhook processed: {result.get('action', 'unknown')}")
        
        return {"status": "success", "result": result}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/tiers")
async def get_tiers():
    """
    Return available pricing tiers and their limits.
    Useful for frontend display.
    """
    return {
        "status": "success",
        "tiers": {
            name: {
                "code": config["code"],
                "queries_per_month": config["queries_per_month"],
                "queries_per_day": config["queries_per_day"],
                "query_length_chars": config["query_length_chars"],
            }
            for name, config in TIER_CONFIG.items()
        }
    }


@router.get("/user-tier")
async def get_user_tier(email: str):
    """
    Get current tier for a user by email.
    
    Returns tier name and limits.
    """
    try:
        # TODO: Look up customer_id by email from database
        # TODO: Query Stripe for active subscription
        
        # For now, return seeker (free) as default
        tier = "seeker"
        limits = TIER_CONFIG.get(tier, TIER_CONFIG["seeker"])
        
        return {
            "status": "success",
            "email": email,
            "tier": tier,
            "limits": {
                "queries_per_month": limits["queries_per_month"],
                "queries_per_day": limits["queries_per_day"],
                "query_length_chars": limits["query_length_chars"],
            }
        }
        
    except Exception as e:
        logger.error(f"Get user tier error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# SAGE WAITLIST ENDPOINT (Added v1.1.0)
# =============================================================================

@router.post("/sage-waitlist")
async def join_sage_waitlist(request: SageWaitlistRequest):
    """
    Add user to Sage tier waitlist via email notification.
    
    DNA: fr_81_uc_001_ec_01_tc_001
    INPUT: email (EmailStr), use_case (str)
    OUTPUT: {"status": str, "message": str}
    CONSUMERS: pricing.html waitlist form
    
    Note: No database storage - email to mohan@pixels.net.nz IS the record.
    """
    try:
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        
        # Build notification email
        notification_html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family: Arial, sans-serif; padding: 20px;">
    <h2 style="color: #0B1E3A;">🎯 New Sage Waitlist Entry</h2>
    <table style="border-collapse: collapse; width: 100%; max-width: 500px;">
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Email:</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{request.email}</td>
        </tr>
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Use Case:</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{request.use_case}</td>
        </tr>
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Submitted:</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{timestamp}</td>
        </tr>
    </table>
    <p style="margin-top: 20px; color: #666;">
        Competition: "First 100 innovators get 1 year free"
    </p>
</body>
</html>
"""
        
        # Send via existing notifier._send_email (proven pattern)
        from src.utils.email_notifier import get_email_notifier
        notifier = get_email_notifier()
        
        success = notifier._send_email(
            to_email="mohan@pixels.net.nz",
            subject=f"🎯 Sage Waitlist: {request.email}",
            html_content=notification_html
        )
        
        if success:
            logger.info(f"[WAITLIST] ✅ Sent to mohan@pixels.net.nz: {request.email}")
            return {
                "status": "success",
                "message": "You're on the list! We'll notify you when Sage launches."
            }
        else:
            logger.error(f"[WAITLIST] ❌ Email send returned False for {request.email}")
            raise HTTPException(status_code=500, detail="Failed to send notification")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[WAITLIST] ❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Email error: {str(e)}")
    # =============================================================================
# VERSION HISTORY UPDATE
# =============================================================================
# Update the version history comment at the top of billing_endpoints.py:
#
#   v1.2.0 (2026-01-04): Added /create-customer-and-checkout endpoint (Session 81)
#                        - Combined customer creation + checkout
#                        - Handles new and existing users
#                        - Captures use_case for marketing segmentation
#
# =============================================================================