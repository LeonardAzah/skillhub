

from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1, lng1, lat2, lng2):
    """Great-circle distance in km between two (lat, lng) points."""
    lat1, lng1, lat2, lng2 = map(radians, (lat1, lng1, lat2, lng2))
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


def bounding_box(lat, lng, radius_km):
    """
    Return (lat_min, lat_max, lng_min, lng_max) for a box that fully
    contains the circle of `radius_km` around (lat, lng).

    This is intentionally a loose approximation (a square that circumscribes
    the circle) -- the point isn't precision, it's letting the database
    throw away the vast majority of rows with an indexed range query before
    we run exact haversine math on whatever's left in Python.
    """
    lat_delta = radius_km / 111.0
    # Guard against cos(90deg) -> 0 near the poles.
    lng_delta = radius_km / max(111.320 * cos(radians(lat)), 0.0001)
    return (
        lat - lat_delta,
        lat + lat_delta,
        lng - lng_delta,
        lng + lng_delta,
    )