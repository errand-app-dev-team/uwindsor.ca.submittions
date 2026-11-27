from django.test import SimpleTestCase, override_settings
from developer.keys import hash_api_key

@override_settings(API_KEY_HASH_PEPPER="test_only_pepper")
class ApiKeyHashTests(SimpleTestCase):
    def test_same_key_produces_same_hash(self):
        first = hash_api_key("my_test_api_key")
        second = hash_api_key("my_test_api_key")
        self.assertEqual(first, second)

    def test_different_keys_produce_different_hashes(self):
        first = hash_api_key("my_test_api_key")
        second = hash_api_key("different_test_api_key")
        self.assertNotEqual(first, second)

    def test_hash_is_64_hex_characters(self):
        result = hash_api_key("my_test_api_key")

        self.assertRegex(result, r"^[0-9a-f]{64}$")

    @override_settings(API_KEY_HASH_PEPPER="")
    def test_empty_pepper_is_rejected(self):
        with self.assertRaises(ValueError):
            hash_api_key("my_test_api_key")

    def test_changing_pepper_changes_hash(self):
        first = hash_api_key("my_test_api_key")
        with override_settings(API_KEY_HASH_PEPPER="new_pepper"):
            second = hash_api_key("my_test_api_key")
        self.assertNotEqual(first, second)