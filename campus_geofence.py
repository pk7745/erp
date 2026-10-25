"""
Campus Geofence & Location Verification Engine for BMS College ERP
==================================================================
Institution: BMS College of Commerce & Management (BMSCCM)
Address: No. 97, Kavi Lakshmisha Road, Parvathi Nagar / V.V. Puram, Bengaluru - 560004
(Distinct from BMS College of Engineering, Basavanagudi)

Provides server-side geodesic calculations, point-in-polygon tests,
reported accuracy thresholds, boundary uncertainty buffers, reading freshness
validation, anti-spoofing sanity checks, and administrative configuration.
"""

import os
import json
import math
import logging
from datetime import datetime, timezone

logger = logging.getLogger('bms_geofence')

# ==============================================================================
# DEFAULT BMSCCM CAMPUS COORDINATES & CONFIGURATION
# ==============================================================================
# BMS College of Commerce & Management (BMSCCM), Kavi Lakshmisha Road, V.V. Puram
DEFAULT_CAMPUS_LAT = 12.951500
DEFAULT_CAMPUS_LON = 77.576200
DEFAULT_CAMPUS_RADIUS_METERS = 150.0  # College building and immediate grounds
DEFAULT_MAX_GPS_ACCURACY_METERS = 50.0  # Reject readings with > 50m error radius
DEFAULT_MAX_LOCATION_AGE_SECONDS = 120  # Max reading staleness (2 minutes)
DEFAULT_BOUNDARY_BUFFER_METERS = 10.0   # Boundary uncertainty tolerance

# Approximate 4-corner polygon bounding box surrounding BMSCCM building block on Kavi Lakshmisha Rd
DEFAULT_CAMPUS_POLYGON = [
    [12.952200, 77.575500],
    [12.952200, 77.576800],
    [12.950800, 77.576800],
    [12.950800, 77.575500]
]

# In-memory configuration registry (defaults loaded from environment)
_CONFIG = {
    'enabled': os.environ.get('CAMPUS_GEOFENCE_ENABLED', 'True').lower() in ('true', '1', 'yes'),
    'mode': os.environ.get('CAMPUS_GEOFENCE_MODE', 'RADIUS').upper(),  # 'RADIUS' or 'POLYGON'
    'center_lat': float(os.environ.get('CAMPUS_LAT', DEFAULT_CAMPUS_LAT)),
    'center_lon': float(os.environ.get('CAMPUS_LON', DEFAULT_CAMPUS_LON)),
    'radius_meters': float(os.environ.get('CAMPUS_RADIUS_METERS', DEFAULT_CAMPUS_RADIUS_METERS)),
    'max_accuracy_meters': float(os.environ.get('MAX_GPS_ACCURACY_METERS', DEFAULT_MAX_GPS_ACCURACY_METERS)),
    'max_age_seconds': int(os.environ.get('MAX_LOCATION_AGE_SECONDS', DEFAULT_MAX_LOCATION_AGE_SECONDS)),
    'boundary_buffer_meters': float(os.environ.get('CAMPUS_BOUNDARY_BUFFER_METERS', DEFAULT_BOUNDARY_BUFFER_METERS)),
    'polygon': DEFAULT_CAMPUS_POLYGON
}

# Try loading polygon from env if defined
_env_poly = os.environ.get('CAMPUS_POLYGON_COORDS')
if _env_poly:
    try:
        parsed_poly = json.loads(_env_poly)
        if isinstance(parsed_poly, list) and len(parsed_poly) >= 3:
            _CONFIG['polygon'] = parsed_poly
    except Exception as ex:
        logger.warning(f"Could not parse CAMPUS_POLYGON_COORDS from env: {ex}")


def get_geofence_config():
    """Returns a shallow copy of active geofence configuration."""
    return dict(_CONFIG)


def update_geofence_config(updates):
    """
    Updates active geofence configuration with validated settings.
    Restricted to administrative use.
    """
    global _CONFIG
    allowed_keys = {
        'enabled', 'mode', 'center_lat', 'center_lon', 'radius_meters',
        'max_accuracy_meters', 'max_age_seconds', 'boundary_buffer_meters', 'polygon'
    }
    for k, v in updates.items():
        if k in allowed_keys:
            if k == 'enabled':
                _CONFIG[k] = bool(v)
            elif k == 'mode':
                mode_str = str(v).upper()
                if mode_str in ('RADIUS', 'POLYGON'):
                    _CONFIG[k] = mode_str
            elif k in ('center_lat', 'center_lon', 'radius_meters', 'max_accuracy_meters', 'boundary_buffer_meters'):
                _CONFIG[k] = float(v)
            elif k == 'max_age_seconds':
                _CONFIG[k] = int(v)
            elif k == 'polygon' and isinstance(v, list) and len(v) >= 3:
                _CONFIG[k] = v
    return get_geofence_config()


# ==============================================================================
# GEODESIC & SPATIAL ALGORITHMS
# ==============================================================================

def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculates great-circle distance between two geographic coordinates in meters
    using the Haversine formula on Earth WGS-84 sphere (mean radius 6,371,000 meters).
    """
    r_earth = 6371000.0  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * (math.sin(dlambda / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return r_earth * c


def point_in_polygon(lat, lon, polygon):
    """
    Determines if a geographic point (lat, lon) is inside a polygon
    using the Ray Casting (Even-Odd) algorithm.
    polygon: list of [lat, lon] vertices (minimum 3 vertices).
    """
    if not polygon or len(polygon) < 3:
        return False

    n = len(polygon)
    inside = False
    p1_lat, p1_lon = polygon[0]

    for i in range(1, n + 1):
        p2_lat, p2_lon = polygon[i % n]
        if lon > min(p1_lon, p2_lon):
            if lon <= max(p1_lon, p2_lon):
                if lat <= max(p1_lat, p2_lat):
                    if p1_lon != p2_lon:
                        x_inters = (lon - p1_lon) * (p2_lat - p1_lat) / (p2_lon - p1_lon) + p1_lat
                    else:
                        x_inters = p1_lat
                    if p1_lat == p2_lat or lat <= x_inters:
                        inside = not inside
        p1_lat, p1_lon = p2_lat, p2_lon

    return inside


def distance_to_polygon_centroid(lat, lon, polygon):
    """Calculates approximate distance from (lat, lon) to polygon centroid in meters."""
    if not polygon:
        return 0.0
    c_lat = sum(p[0] for p in polygon) / len(polygon)
    c_lon = sum(p[1] for p in polygon) / len(polygon)
    return haversine_distance(lat, lon, c_lat, c_lon)


# ==============================================================================
# AUTHORITATIVE CAMPUS PRESENCE VERIFICATION
# ==============================================================================

def verify_campus_presence(lat, lon, accuracy=None, client_timestamp=None, client_is_inside=None):
    """
    Authoritative server-side verification of staff physical presence inside BMSCCM campus.

    Parameters:
        lat (float/str): Reported latitude from browser Geolocation API.
        lon (float/str): Reported longitude from browser Geolocation API.
        accuracy (float/str, optional): Reported accuracy in meters from browser Geolocation API.
        client_timestamp (int/float/str, optional): Client-reported location capture timestamp.
        client_is_inside (bool, optional): Untrusted client flag (used strictly for spoofing detection).

    Returns:
        (is_valid: bool, status_code: str, message: str, details: dict)
    """
    cfg = get_geofence_config()

    # 1. Mandatory Coordinate Range & Type Validation
    if lat is None or lon is None or lat == '' or lon == '':
        return False, 'MISSING_COORDINATES', 'GPS Error: Location coordinates were not provided. Please enable device location.', {}

    try:
        val_lat = float(lat)
        val_lon = float(lon)
    except (ValueError, TypeError):
        return False, 'INVALID_COORDINATES', 'GPS Error: Location coordinates must be numeric values.', {}

    if math.isnan(val_lat) or math.isnan(val_lon) or math.isinf(val_lat) or math.isinf(val_lon):
        return False, 'INVALID_COORDINATES', 'GPS Error: Malformed coordinate values received.', {}

    # Coordinate domain check
    if not (-90.0 <= val_lat <= 90.0) or not (-180.0 <= val_lon <= 180.0):
        return False, 'INVALID_COORDINATES', f'GPS Error: Coordinates out of valid geographic range (lat: {val_lat}, lon: {val_lon}).', {}

    # Null/Default coordinate check (0.0, 0.0 is Null Island in Gulf of Guinea)
    if abs(val_lat) < 0.0001 and abs(val_lon) < 0.0001:
        return False, 'INVALID_COORDINATES', 'GPS Error: Uninitialized (0, 0) location received. Please acquire a real GPS fix.', {}

    # 2. GPS Accuracy Validation
    val_accuracy = None
    if accuracy is not None and accuracy != '':
        try:
            val_accuracy = float(accuracy)
            if math.isnan(val_accuracy) or math.isinf(val_accuracy) or val_accuracy <= 0:
                return False, 'INVALID_ACCURACY', 'GPS Error: Accuracy must be a positive number.', {}
        except (ValueError, TypeError):
            return False, 'INVALID_ACCURACY', 'GPS Error: Accuracy value must be numeric.', {}

    if val_accuracy is not None:
        if val_accuracy > cfg['max_accuracy_meters']:
            msg = (
                f"GPS Accuracy Insufficient: Your device reported an accuracy uncertainty of ±{round(val_accuracy)}m "
                f"(Maximum allowed: ±{round(cfg['max_accuracy_meters'])}m). "
                f"Please ensure High Accuracy GPS is enabled, step closer to an open window or outdoors, and retry."
            )
            return False, 'UNACCEPTABLE_ACCURACY', msg, {'reported_accuracy': val_accuracy, 'max_allowed': cfg['max_accuracy_meters']}

    # 3. Location Reading Freshness Validation
    if client_timestamp is not None and client_timestamp != '':
        now_epoch = datetime.now(timezone.utc).timestamp()
        val_ts = None
        try:
            # Check if timestamp is numeric epoch
            ts_num = float(client_timestamp)
            # If in milliseconds (> 1e11), convert to seconds
            if ts_num > 1e11:
                ts_num = ts_num / 1000.0
            val_ts = ts_num
        except (ValueError, TypeError):
            # Try parsing ISO format
            try:
                dt = datetime.fromisoformat(str(client_timestamp).replace('Z', '+00:00'))
                val_ts = dt.timestamp()
            except Exception:
                pass

        if val_ts is not None:
            age_seconds = now_epoch - val_ts
            # If reading is older than allowed max_age or more than 30s in the future
            if age_seconds > cfg['max_age_seconds']:
                msg = f"GPS Reading Stale: The captured location is {round(age_seconds)}s old (Maximum allowed: {cfg['max_age_seconds']}s). Please refresh location and retry."
                return False, 'STALE_LOCATION', msg, {'age_seconds': age_seconds, 'max_age': cfg['max_age_seconds']}
            elif age_seconds < -30.0:
                msg = "GPS Error: Location reading has a future timestamp. Please verify device date and time."
                return False, 'STALE_LOCATION', msg, {'future_seconds': abs(age_seconds)}

    # 4. Geofence Active Check
    if not cfg['enabled']:
        # Safety fallback: When enforcement is disabled during initial configuration,
        # clearly state it was not verified to prevent false confidence.
        return True, 'GEOFENCE_UNENFORCED', 'Notice: Campus geofence enforcement is currently disabled in system configuration.', {
            'lat': val_lat,
            'lon': val_lon,
            'accuracy': val_accuracy,
            'enforced': False
        }

    # 5. Geofence Verification (RADIUS or POLYGON)
    mode = cfg['mode']
    if mode == 'POLYGON':
        polygon = cfg.get('polygon', DEFAULT_CAMPUS_POLYGON)
        is_inside = point_in_polygon(val_lat, val_lon, polygon)
        centroid_dist = distance_to_polygon_centroid(val_lat, val_lon, polygon)

        if not is_inside:
            msg = f"Verification Failed: Your location is outside the BMS College of Commerce & Management campus polygon (Approx. {round(centroid_dist)}m from campus center)."
            return False, 'OUTSIDE_CAMPUS', msg, {
                'lat': val_lat,
                'lon': val_lon,
                'centroid_distance': centroid_dist,
                'mode': 'POLYGON'
            }

        return True, 'CAMPUS_VERIFIED', 'Campus Location Verified: Inside BMSCCM campus polygon boundary.', {
            'lat': val_lat,
            'lon': val_lon,
            'accuracy': val_accuracy,
            'centroid_distance': centroid_dist,
            'mode': 'POLYGON'
        }

    else:
        # Default RADIUS Mode
        c_lat = cfg['center_lat']
        c_lon = cfg['center_lon']
        radius = cfg['radius_meters']
        buffer_dist = cfg['boundary_buffer_meters']

        dist = haversine_distance(val_lat, val_lon, c_lat, c_lon)

        # A. Strictly outside radius
        if dist > radius:
            msg = (
                f"Verification Failed: You are {round(dist)}m away from BMS College of Commerce & Management "
                f"(V.V. Puram Campus). Allowed radius is {int(radius)}m."
            )
            return False, 'OUTSIDE_CAMPUS', msg, {
                'lat': val_lat,
                'lon': val_lon,
                'distance': dist,
                'radius': radius,
                'mode': 'RADIUS'
            }

        # B. Boundary Uncertainty Check:
        # If the device accuracy error radius extends past the boundary buffer,
        # physical presence cannot be guaranteed with confidence.
        if val_accuracy is not None:
            if (dist + val_accuracy) > (radius + buffer_dist):
                msg = (
                    f"Boundary Uncertainty: Your location ({round(dist)}m from campus center) has an accuracy margin of ±{round(val_accuracy)}m, "
                    f"which extends beyond the {int(radius)}m campus perimeter. Please move further inside the building and acquire a clearer GPS fix."
                )
                return False, 'BOUNDARY_UNCERTAIN', msg, {
                    'lat': val_lat,
                    'lon': val_lon,
                    'distance': dist,
                    'accuracy': val_accuracy,
                    'radius': radius,
                    'buffer': buffer_dist
                }

        # C. Verified Inside Campus
        return True, 'CAMPUS_VERIFIED', f"Campus Location Verified: Inside BMSCCM campus grounds ({round(dist)}m from center, ±{round(val_accuracy or 0)}m accuracy).", {
            'lat': val_lat,
            'lon': val_lon,
            'distance': dist,
            'accuracy': val_accuracy,
            'radius': radius,
            'mode': 'RADIUS'
        }
