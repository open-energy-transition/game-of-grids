#!/usr/bin/env python3
"""
Configuration file for Osmose processing pipeline
"""

# Database Configuration
DB_CONFIG = {
    'host': 'db.teumppdbhbrozswbpond.supabase.co',
    'port': 5432,
    'database': 'postgres',
    'user': 'postgres',
    'password': '9%%XJMVWB&ELyre'
}

# Osmose API Configuration
OSMOSE_CONFIG = {
    'API_BASE': "https://osmose.openstreetmap.fr/api/0.3",
    'COUNTRY_CODE': "KZ",
    'COUNTRY_NAME': "kazakhstan",
    'ITEM': 7040,
    'CLASS': 2,
    'FETCH_LIMIT': 500,  # Per API request
    'REQUEST_TIMEOUT': 30,
    'REQUEST_DELAY': 0.5  # Seconds between requests
}

# Patch Creation Configuration
PATCH_CONFIG = {
    'TARGET_PATCH_AREA_KM2': 15.0,
    'MIN_PATCH_AREA_KM2': 5.0,
    'MAX_PATCH_AREA_KM2': 30.0,
    'CLUSTER_DISTANCE_KM': 3.0,
    'MIN_ERRORS_PER_PATCH': 3,
    'GRID_SIZE_KM': 4.0,
    'BUFFER_SIZE_KM': 1.0,
    'DEFAULT_PATCH_SIZE_KM': 2.0
}

# Logging Configuration
LOGGING_CONFIG = {
    'level': 'INFO',
    'format': '%(asctime)s - %(levelname)s - %(message)s'
}