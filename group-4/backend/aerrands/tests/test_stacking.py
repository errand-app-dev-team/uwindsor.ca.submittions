from django.test import SimpleTestCase

from aerrands.services.stacking import (
    format_cents,
    split_price_cents,
    generate_delivery_code,
    generate_unique_codes,
    DELIVERY_CODE_LENGTH,
    DELIVERY_CODE_ALPHABET,
    build_batch
)
from aerrands.validators import RequestValidationError


# ---------- Part 1: price split ----------
class SplitPriceTests(SimpleTestCase):
    def test_documented_example(self):
        # Aerrand's example: 24.92 over two stops -> 12.46 each.
        self.assertEqual(split_price_cents(2492, 2), [1246, 1246])

    def test_leftover_cents_go_on_last_stop(self):
        self.assertEqual(split_price_cents(1000, 3), [333, 333, 334])

    def test_single_stop_gets_everything(self):
        self.assertEqual(split_price_cents(1362, 1), [1362])

    def test_shares_always_add_up_to_total(self):
        for total in (0, 1, 7, 99, 1000, 2492, 123457):
            for stops in range(1, 6):
                shares = split_price_cents(total, stops)
                self.assertEqual(len(shares), stops)
                self.assertEqual(sum(shares), total)

    def test_rejects_bad_input(self):
        for total, stops in [(-1, 2), (10.5, 2), ("10", 2), (True, 2), (100, 0), (100, -1), (100, True)]:
            with self.assertRaises(ValueError):
                split_price_cents(total, stops)

    def test_format_cents(self):
        self.assertEqual(format_cents(1246), "12.46")
        self.assertEqual(format_cents(5), "0.05")
        self.assertEqual(format_cents(2000), "20.00")

    def test_zero_total_across_five_stops(self):
        self.assertEqual(
            split_price_cents(0, 5),
            [0, 0, 0, 0, 0],
        )

    def test_one_cent_across_five_stops(self):
        self.assertEqual(
            split_price_cents(1, 5),
            [0, 0, 0, 0, 1],
        )


# ---------- Part 2: delivery codes ----------
class DeliveryCodeTests(SimpleTestCase):
    def test_code_has_six_allowed_characters(self):
        for _ in range(200):
            code = generate_delivery_code()
            self.assertEqual(len(code), DELIVERY_CODE_LENGTH)
            self.assertTrue(all(c in DELIVERY_CODE_ALPHABET for c in code))

    def test_codes_in_a_batch_are_unique(self):
        for _ in range(300):
            codes = generate_unique_codes(5)
            self.assertEqual(len(codes), 5)
            self.assertEqual(len(set(codes)), 5)




# ---------- Part 3: building the records ----------
def dropoff(name, reference, parcels):
    return {
        "reference": reference,
        "label": f"{reference} Main St",
        "lat": "42.3201",
        "lng": "-83.0187",
        "parcels": parcels,
        "contact": {"name": name, "phone_number": "+15195550188",
                    "preference": "leave_at_door"},
    }


class BuildBatchTests(SimpleTestCase):
    def two_stops(self):
        return [dropoff("Jordan Alvarez", "SHOP-10432", {"small": 2, "medium": 1}),
                dropoff("Priya Raman", "SHOP-10433", {"small": 4})]

    def test_documented_example(self):
        batch = build_batch(self.two_stops(), 2492)
        self.assertEqual(batch["stop_count"], 2)
        self.assertEqual(batch["total"], "24.92")
        self.assertEqual([s["price"] for s in batch["stops"]], ["12.46", "12.46"])
        self.assertEqual([s["index"] for s in batch["stops"]], [0, 1])
        self.assertEqual([s["receiver_name"] for s in batch["stops"]],
                         ["Jordan Alvarez", "Priya Raman"])
        self.assertEqual([s["reference"] for s in batch["stops"]],
                         ["SHOP-10432", "SHOP-10433"])
        self.assertTrue(all(s["status"] == "draft" for s in batch["stops"]))
        self.assertTrue(all(s["payment_status"] is False for s in batch["stops"]))

    def test_stops_share_batch_but_have_own_ids_and_codes(self):
        batch = build_batch(self.two_stops(), 2492)
        stops = batch["stops"]
        self.assertTrue(all(s["batch_id"] == batch["batch_id"] for s in stops))
        self.assertTrue(all(s["batch_size"] == 2 for s in stops))
        self.assertEqual(len({s["errand_id"] for s in stops}), 2)
        self.assertEqual(len({s["delivery_code"] for s in stops}), 2)

    def test_prices_add_up_to_total(self):
        stops = [dropoff(f"P{i}", f"R{i}", {"small": 1}) for i in range(3)]
        batch = build_batch(stops, 1000)
        self.assertEqual(sum(s["price_cents"] for s in batch["stops"]), 1000)
        self.assertEqual(batch["stops"][-1]["price"], "3.34")

    def test_single_dropoff_batch_of_one(self):
        batch = build_batch([dropoff("Jordan", "R1", {"small": 1})], 1362)
        self.assertEqual(batch["stop_count"], 1)
        self.assertEqual(batch["stops"][0]["price"], "13.62")

    def test_five_stops_ok_six_rejected(self):
        five = [dropoff(f"P{i}", f"R{i}", {"small": 1}) for i in range(5)]
        self.assertEqual(build_batch(five, 5000)["stop_count"], 5)
        six = five + [dropoff("P6", "R6", {"small": 1})]
        with self.assertRaises(RequestValidationError) as ctx:
            build_batch(six, 6000)
        self.assertEqual(ctx.exception.code, "too_many_stops")

    def test_empty_or_wrong_type_rejected(self):
        for bad in ([], None, "x", {}):
            with self.assertRaises(RequestValidationError):
                build_batch(bad, 1000)

    def test_does_not_modify_the_request(self):
        stops = self.two_stops()
        before = [dict(s, parcels=dict(s["parcels"])) for s in stops]
        batch = build_batch(stops, 2492)
        batch["stops"][0]["parcels"]["small"] = 99  # change the copy
        self.assertEqual(stops, before)
