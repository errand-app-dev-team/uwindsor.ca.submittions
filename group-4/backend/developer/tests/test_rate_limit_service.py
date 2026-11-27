from uuid import uuid4
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from developer.services.rate_limit_service import check_rate_limit


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "rate-limit-tests",
        }
    }
)
class RateLimitServiceTests(SimpleTestCase):

    def setUp(self):
        cache.clear()
        self.api_key_id = uuid4()

    @patch("developer.services.rate_limit_service.time.time", return_value=120)
    def test_first_request_is_allowed(self, mock_time):
        allowed, retry_after = check_rate_limit(self.api_key_id, limit=3)

        self.assertTrue(allowed)
        self.assertEqual(retry_after, 60)

    @patch("developer.services.rate_limit_service.time.time", return_value=120)
    def test_requests_within_limit_are_allowed(self, mock_time):
        for _ in range(3):
            allowed, _ = check_rate_limit(self.api_key_id, limit=3)
            self.assertTrue(allowed)

    @patch("developer.services.rate_limit_service.time.time", return_value=120)
    def test_request_exceeding_limit_is_rejected(self, mock_time):
        for _ in range(3):
            check_rate_limit(self.api_key_id, limit=3)

        allowed, retry_after = check_rate_limit(self.api_key_id, limit=3)

        self.assertFalse(allowed)
        self.assertEqual(retry_after, 60)

    @patch("developer.services.rate_limit_service.time.time", return_value=120)
    def test_api_keys_have_separate_limits(self, mock_time):
        other_api_key_id = uuid4()

        check_rate_limit(self.api_key_id, limit=1)
        allowed, _ = check_rate_limit(other_api_key_id, limit=1)

        self.assertTrue(allowed)

    @patch("developer.services.rate_limit_service.time.time")
    def test_counter_resets_in_new_window(self, mock_time):
        mock_time.return_value = 120

        check_rate_limit(self.api_key_id, limit=1)
        allowed, _ = check_rate_limit(self.api_key_id, limit=1)
        self.assertFalse(allowed)

        mock_time.return_value = 180

        allowed, _ = check_rate_limit(self.api_key_id, limit=1)
        self.assertTrue(allowed)

    @patch("developer.services.rate_limit_service.time.time", return_value=150)
    def test_retry_after_matches_remaining_window(self, mock_time):
        check_rate_limit(self.api_key_id, limit=1)

        allowed, retry_after = check_rate_limit(self.api_key_id, limit=1)

        self.assertFalse(allowed)
        self.assertEqual(retry_after, 30)
