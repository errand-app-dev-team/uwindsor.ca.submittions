
"""Quote calculation utilities for the test environment."""
import math
from decimal import Decimal, ROUND_HALF_UP


DEMO_BASE_FARE = Decimal("5.00")
DEMO_RATE_PER_KM = Decimal("1.50")
DEMO_PARCEL_RATES = {
    "small": Decimal("1.00"),
    "medium": Decimal("2.00"),
    "large": Decimal("3.00"),
    "xl": Decimal("4.00"),
}


def calculate_distance_km(start, end):
    """Calculate straight-line distance between two coordinates."""
    lat1 = math.radians(start["lat"])
    lng1 = math.radians(start["lng"])
    lat2 = math.radians(end["lat"])
    lng2 = math.radians(end["lng"])

    delta_lat = lat2 - lat1
    delta_lng = lng2 - lng1

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2)
        * math.sin(delta_lng / 2) ** 2
    )
    a = min(1.0, max(0.0, a))

    return 6371.0 * 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a),
    )


def calculate_demo_quote(validated_data):
    """Calculate a quote using test pricing configuration."""
    pickup = validated_data["pickup"]
    stops = validated_data["stops"]

    locations = [pickup, *stops]

    # Demo calculations require coordinates; address geocoding is not available.
    for location in locations:
        if "lat" not in location or "lng" not in location:
            raise ValueError(
                "Demo quotes require lat/lng coordinates for every location."
            )

    route_distance = sum(
        calculate_distance_km(start, end)
        for start, end in zip(locations, locations[1:])
    )

    route_km = Decimal(str(route_distance)).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    distance_fee = (
        route_km * DEMO_RATE_PER_KM
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    parcel_fee = sum(
        (
            DEMO_PARCEL_RATES[size] * quantity
            for stop in stops
            for size, quantity in stop["parcels"].items()
        ),
        Decimal("0.00"),
    )

    total = DEMO_BASE_FARE + distance_fee + parcel_fee

    breakdown = {
        "pricing_source": "demo_simulation",
        "distance_type": "straight_line",
        "currency": "CAD",
        "base_fare": str(DEMO_BASE_FARE),
        "distance_fee": str(distance_fee),
        "parcel_fee": str(parcel_fee),
        "total": str(total),
    }

    resolved_stops = [
        {
            "lat": stop["lat"],
            "lng": stop["lng"],
        }
        for stop in stops
    ]

    return {
        "route_km": route_km,
        "breakdown": breakdown,
        "total": total,
        "resolved_stops": resolved_stops,
    }
