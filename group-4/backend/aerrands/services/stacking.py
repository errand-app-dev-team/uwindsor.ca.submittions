"""
Delivery stacking helpers: one pickup with up to five drop-offs.

A stacked delivery is ONE job for the driver but N delivery records, one per
stop. Each record has its own errand_id, handover code and share of the price,
and all records share one batch_id (see Aerrand's request/response shapes).

These functions only prepare data. They do not touch the database, so they are
easy to test and can be called from whichever service creates the records.
"""
import secrets
import string
import uuid

from aerrands.validators import RequestValidationError, validate_stop_count


# ----------------------------------------------------------------------
# Part 1: splitting the route price across the stops
# ----------------------------------------------------------------------

def split_price_cents(total_cents, stop_count):
    """
    Split a route price (in cents) equally across the stops.

    Money is handled in whole cents (integers) because floats can drift, e.g.
    0.1 + 0.2 != 0.3. Any leftover cents go on the LAST stop, so the shares
    always add up exactly to the total.

        split_price_cents(2492, 2) -> [1246, 1246]
        split_price_cents(1000, 3) -> [333, 333, 334]
    """
    if isinstance(total_cents, bool) or not isinstance(total_cents, int) or total_cents < 0:
        raise ValueError("total_cents must be a non-negative whole number.")
    if isinstance(stop_count, bool) or not isinstance(stop_count, int) or stop_count < 1:
        raise ValueError("stop_count must be at least 1.")

    share = total_cents // stop_count
    shares = [share] * stop_count
    shares[-1] += total_cents - share * stop_count  # the leftover cents
    return shares


def format_cents(cents):
    """Show whole cents as a decimal string, e.g. 1246 -> "12.46"."""
    return f"{cents // 100}.{cents % 100:02d}"


# ----------------------------------------------------------------------
# Part 2: handover codes
# ----------------------------------------------------------------------

DELIVERY_CODE_LENGTH = 6
DELIVERY_CODE_ALPHABET = string.ascii_uppercase + string.digits


def generate_delivery_code():
    """
    Make one 6-character handover code such as "4F7K2Q".

    The receiver tells this code to the driver, so it must be unpredictable:
    we use the `secrets` module (never `random`, which is guessable).
    """
    return "".join(
        secrets.choice(DELIVERY_CODE_ALPHABET) for _ in range(DELIVERY_CODE_LENGTH)
    )


def generate_unique_codes(count):
    """Make `count` handover codes that are all different from each other."""
    codes = set()
    while len(codes) < count:
        codes.add(generate_delivery_code())
    return list(codes)


# ----------------------------------------------------------------------
# Part 3: building one record per stop
# ----------------------------------------------------------------------

def build_batch(dropoffs, total_cents):
    """
    Turn the drop-offs of a create request into one record per stop.

    `dropoffs` is the already-validated list of drop-off objects (for a single
    delivery, pass [data["dropoff"]]). `total_cents` is the tax-included route
    price calculated by the SERVER, never a client-supplied amount.

    The records follow the documented response shape. delivery_code is the
    handover code, so keep it out of anything a customer can reach (public
    tracking links must never show it).
    """
    if not isinstance(dropoffs, list) or not dropoffs:
        raise RequestValidationError("dropoffs must be a non-empty list.")

    # Reuse the existing rule: at most five stops (code "too_many_stops").
    validate_stop_count(dropoffs)

    stop_count = len(dropoffs)
    shares = split_price_cents(total_cents, stop_count)
    codes = generate_unique_codes(stop_count)
    batch_id = str(uuid.uuid4())

    stops = []
    for index, dropoff in enumerate(dropoffs):
        contact = dropoff.get("contact", {})
        stops.append(
            {
                "errand_id": str(uuid.uuid4()),
                "batch_id": batch_id,
                "index": index,
                "batch_size": stop_count,
                "reference": dropoff.get("reference"),
                "label": dropoff.get("label"),
                "lat": dropoff.get("lat"),
                "lng": dropoff.get("lng"),
                "receiver_name": contact.get("name"),
                "parcels": dict(dropoff.get("parcels", {})),  # a copy
                "status": "draft",
                "price": format_cents(shares[index]),
                "price_cents": shares[index],
                "payment_status": False,
                "delivery_code": codes[index],
            }
        )

    return {
        "batch_id": batch_id,
        "stop_count": stop_count,
        "total": format_cents(total_cents),
        "stops": stops,
    }
