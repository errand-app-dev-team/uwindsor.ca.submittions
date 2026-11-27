from django.test import SimpleTestCase

from aerrands.validators import (
    RequestValidationError,
    validate_contact,
    validate_delivery_details,
    validate_location,
    validate_parcels,
)


def contact(preference="leave_at_door", **extra):
    data = {"name": "Jordan", "phone_number": "+15195550188", "preference": preference}
    data.update(extra)
    return data


def place(preference="leave_at_door", **extra):
    data = {
        "label": "1823 Wyandotte St E",
        "lat": "42.3201",
        "lng": "-83.0187",
        "contact": contact(preference),
    }
    data.update(extra)
    return data


def single():
    return {"pickup": place("pickup"), "dropoff": place()}


def multi(count):
    stop = place(parcels={"small": 2, "large": 0, "xl": 0})
    return {"pickup": place("pickup"), "dropoffs": [dict(stop) for _ in range(count)]}


class DeliveryDetailsTests(SimpleTestCase):
    def assertRejected(self, data):
        with self.assertRaises(RequestValidationError):
            validate_delivery_details(data)

    def test_accepts_documented_single_and_multi_stop(self):
        validate_delivery_details(single())
        validate_delivery_details(multi(1))
        validate_delivery_details(multi(5))

    def test_coordinates_must_be_real_decimal_strings(self):
        for lat, lng in [(42.3, "-83.0"), ("abc", "-83.0"), ("0", "0"), ("95", "10"), ("nan", "10")]:
            data = single()
            data["dropoff"]["lat"], data["dropoff"]["lng"] = lat, lng
            self.assertRejected(data)

    def test_coordinates_are_required(self):
        data = single()
        del data["pickup"]["lat"]
        self.assertRejected(data)

    def test_label_is_required(self):
        data = single()
        del data["dropoff"]["label"]
        self.assertRejected(data)

    def test_contact_is_required_with_name_phone_and_preference(self):
        data = single()
        del data["dropoff"]["contact"]
        self.assertRejected(data)
        for missing in ("name", "phone_number", "preference"):
            data = single()
            del data["dropoff"]["contact"][missing]
            self.assertRejected(data)

    def test_preference_must_match_location_type(self):
        data = single()
        data["dropoff"]["contact"]["preference"] = "pickup"
        self.assertRejected(data)
        data = single()
        data["pickup"]["contact"]["preference"] = "leave_at_door"
        self.assertRejected(data)

    def test_text_limits(self):
        data = single()
        data["dropoff"]["contact"]["instructions"] = "x" * 256
        self.assertRejected(data)

    def test_multi_stop_needs_parcels_and_at_least_one_item(self):
        data = multi(1)
        del data["dropoffs"][0]["parcels"]
        self.assertRejected(data)
        data = multi(1)
        data["dropoffs"][0]["parcels"] = {"small": 0, "xl": 0}
        self.assertRejected(data)

    def test_does_not_modify_the_request(self):
        data = single()
        validate_delivery_details(data)
        self.assertEqual(data["dropoff"]["lat"], "42.3201")   # still a string


class ReusedHelperTests(SimpleTestCase):
    def test_parcel_quantity_of_one_is_valid(self):
        validate_parcels({"small": 1}, 1)

    def test_zero_quantity_only_with_allow_zero(self):
        with self.assertRaises(RequestValidationError):
            validate_parcels({"small": 1, "large": 0}, 1)
        validate_parcels({"large": 0, "small": 2}, 1, allow_zero=True)

    def test_all_zero_parcels_rejected(self):
        with self.assertRaises(RequestValidationError):
            validate_parcels({"small": 0}, 1, allow_zero=True)

    def test_zero_zero_rejected(self):
        with self.assertRaises(RequestValidationError):
            validate_location({"lat": 0, "lng": 0}, "pickup")

    def test_string_coordinates_only_accepted_when_requested(self):
        with self.assertRaises(RequestValidationError):
            validate_location({"lat": "42.3", "lng": "-83.0"}, "pickup")
        validate_location({"lat": "42.3", "lng": "-83.0"}, "pickup",
                          coordinates_as_strings=True)

    def test_old_contact_rules_unchanged(self):
        validate_contact({}, "recipient")                  # still lenient
        validate_contact({"name": "A", "phone": "1"}, "recipient")
        with self.assertRaises(RequestValidationError):
            validate_contact({"name": 5}, "recipient")