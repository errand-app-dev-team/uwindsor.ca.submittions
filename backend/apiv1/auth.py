"""Company accounts — sign up and sign in (Nikhil).

A company registers with a name, an email and a password. We store the password only as a
secure hash (never the plain text). Signing in with the name + password connects them to
their own data — deliveries, wallet, events — because everything is scoped to the owner id
derived from the company name, so their previous orders are right there when they log in.

Accounts live in the ``companies`` collection, which is saved to disk with everything else,
so a company's login and history survive a restart.
"""
import uuid
from datetime import datetime, timezone

from django.contrib.auth.hashers import check_password, make_password

from . import db

# Same namespace the API keys use, so a company's owner id matches its deliveries/wallet.
_NS = uuid.UUID("a1b2c3d4-0000-4000-8000-000000000000")


def _companies():
    return db.get_db()["companies"]


def owner_for(company_name):
    """The business owner id for a company name (matches how keys/deliveries are scoped)."""
    return str(uuid.uuid5(_NS, (company_name or "").strip().lower()))


def _public(c):
    return {"company": c["company_name"], "email": c["email"], "owner_id": c["business_owner_id"]}


def find(company_name):
    return _companies().find_one({"company_name_lower": (company_name or "").strip().lower()})


def signup(company_name, email, password):
    """Create a company account. Returns (public_dict, None) or (None, error_message)."""
    name = (company_name or "").strip()
    email = (email or "").strip()
    if not name or not email or not password:
        return None, "Company name, email and password are all required."
    if find(name):
        return None, "A company with that name already exists — try signing in instead."
    doc = {
        "company_name": name,
        "company_name_lower": name.lower(),
        "email": email,
        "password_hash": make_password(password),
        "business_owner_id": owner_for(name),
        "created_at": datetime.now(timezone.utc),
    }
    _companies().insert_one(doc)
    return _public(doc), None


def login(company_name, password):
    """Check a company name + password. Returns (public_dict, None) or (None, error_message)."""
    c = find(company_name)
    if not c or not check_password(password or "", c["password_hash"]):
        return None, "Wrong company name or password."
    return _public(c), None
