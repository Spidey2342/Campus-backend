"""
Paystack integration for Featured Listings (and, later, any other paid
marketplace feature — Chale for Business, verified badges, etc. can reuse
these same two functions).

Docs: https://paystack.com/docs/api/transaction/

We use the "Initialize Transaction" + redirect flow (not Paystack Inline JS):
the backend asks Paystack for a hosted checkout URL, the frontend redirects
the browser there, and Paystack redirects back to our own callback page with
a `reference` query param once the user finishes paying. This only needs the
secret key server-side and works reliably on slow mobile connections without
loading any extra JS on the frontend.
"""
import os
import hmac
import hashlib
import httpx

PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
PAYSTACK_BASE_URL = "https://api.paystack.co"

# Featured Listing pricing — GH₵, per the "Featured Listings" plan
# (pin a listing to the top of the marketplace feed for N days).
FEATURE_PRICING = {
    3: 20,
    7: 45,
    14: 80,
}


def _headers():
    return {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }


def initialize_transaction(email: str, amount_ghs: float, reference: str, callback_url: str, metadata: dict = None) -> dict:
    """
    Asks Paystack for a hosted checkout link. Returns Paystack's response
    data dict, which includes `authorization_url` (redirect the browser
    here) and `access_code`.

    amount_ghs is in whole cedis (e.g. 45.0) — Paystack's API wants the
    amount in the smallest currency unit (pesewas for GHS), so we convert.
    """
    if not PAYSTACK_SECRET_KEY:
        raise RuntimeError("PAYSTACK_SECRET_KEY is not set")

    payload = {
        "email": email,
        "amount": int(round(amount_ghs * 100)),  # GHS -> pesewas
        "currency": "GHS",
        "reference": reference,
        "callback_url": callback_url,
    }
    if metadata:
        payload["metadata"] = metadata

    response = httpx.post(
        f"{PAYSTACK_BASE_URL}/transaction/initialize",
        headers=_headers(),
        json=payload,
        timeout=15,
    )
    response.raise_for_status()
    body = response.json()
    if not body.get("status"):
        raise RuntimeError(f"Paystack initialize failed: {body.get('message')}")
    return body["data"]


def verify_transaction(reference: str) -> dict:
    """
    Asks Paystack for the current status of a transaction by reference.
    Returns Paystack's data dict — the fields we care about are
    data["status"] ("success" | "failed" | "abandoned") and data["amount"]
    (in pesewas, for cross-checking against what we expected to charge).
    """
    if not PAYSTACK_SECRET_KEY:
        raise RuntimeError("PAYSTACK_SECRET_KEY is not set")

    response = httpx.get(
        f"{PAYSTACK_BASE_URL}/transaction/verify/{reference}",
        headers=_headers(),
        timeout=15,
    )
    response.raise_for_status()
    body = response.json()
    if not body.get("status"):
        raise RuntimeError(f"Paystack verify failed: {body.get('message')}")
    return body["data"]


def verify_webhook_signature(raw_body: bytes, signature_header: str) -> bool:
    """
    Paystack signs webhook payloads with HMAC-SHA512 using your secret key,
    sent as the `x-paystack-signature` header. Always verify this before
    trusting a webhook payload — otherwise anyone could POST a fake
    "charge.success" event and get free featured listings.
    """
    if not PAYSTACK_SECRET_KEY or not signature_header:
        return False
    computed = hmac.new(
        PAYSTACK_SECRET_KEY.encode("utf-8"),
        raw_body,
        hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(computed, signature_header)