import hashlib
import hmac
from django.conf import settings

def hash_api_key(raw_key):
    pepper = settings.API_KEY_HASH_PEPPER
    if not pepper:
        raise ValueError("The API Key pepper must be configured.")

    return hmac.new(
        pepper.encode('utf-8'),
        raw_key.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
