import uuid

from django.test import TestCase

from developer.models import ApiAuditLog, ApiKey
from developer.services.audit import log_audit
from developer.services.revocation import (
    KeyAlreadyRevokedError,
    KeyNotFoundError,
    revoke_api_key,
)


def make_key(owner_id):
    return ApiKey.objects.create(
        business_owner_id=owner_id,
        created_by_id=owner_id,
        name="Test integration",
        environment="test",
        key_prefix="aer_test_abc123",
        key_hash=uuid.uuid4().hex + uuid.uuid4().hex,  # 64 chars, fake
        scopes=["quotes:read"],
        status="active",
    )


class RevokeKeyTests(TestCase):
    def setUp(self):
        self.owner = uuid.uuid4()
        self.key = make_key(self.owner)

    def revoke(self, **kwargs):
        return revoke_api_key(api_key_id=self.key.id,
                              business_owner_id=self.owner,
                              revoked_by_id=self.owner, **kwargs)

    def test_revoke_marks_key_revoked(self):
        revoked = self.revoke()
        self.assertEqual(revoked.status, "revoked")
        self.assertIsNotNone(revoked.revoked_at)
        self.assertEqual(revoked.revoked_by, self.owner)

    def test_revoke_writes_audit_row_without_key_material(self):
        self.revoke(reason="leaked")
        row = ApiAuditLog.objects.get(action="key.revoked")
        self.assertEqual(row.target_id, self.key.id)
        self.assertNotIn(self.key.key_hash, str(row.detail))

    def test_other_business_cannot_revoke(self):
        with self.assertRaises(KeyNotFoundError):
            revoke_api_key(api_key_id=self.key.id,
                           business_owner_id=uuid.uuid4(),
                           revoked_by_id=uuid.uuid4())
        self.key.refresh_from_db()
        self.assertEqual(self.key.status, "active")

    def test_revoking_twice_is_rejected(self):
        self.revoke()
        with self.assertRaises(KeyAlreadyRevokedError):
            self.revoke()


class AuditHelperTests(TestCase):
    def test_rejects_key_material_in_detail(self):
        with self.assertRaises(ValueError):
            log_audit(action="key.created", business_owner_id=uuid.uuid4(),
                      detail={"raw_key": "aer_test_secret"})