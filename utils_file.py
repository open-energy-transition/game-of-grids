#!/usr/bin/env python3
"""
Shared utilities for Osmose processing pipeline
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import logging
import math
from typing import Dict, Optional
from shapely.geometry import Polygon
from config import DB_CONFIG, LOGGING_CONFIG

def setup_logging():
    """Setup logging configuration"""
    logging.basicConfig(
        level=getattr(logging, LOGGING_CONFIG['level']),
        format=LOGGING_CONFIG['format']
    )
    return logging.getLogger(__name__)

def get_db_connection() -> psycopg2.extensions.connection:
    """Get database connection"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        logging.error(f"Database connection failed: {e}")
        raise

def close_db_connection(conn: psycopg2.extensions.connection):
    """Close database connection"""
    if conn:
        conn.close()

def km_to_degrees(km: float, latitude: float) -> float:
    """Convert kilometers to degrees at given latitude"""
    lat_radians = math.radians(latitude)
    km_per_degree_lat = 111.32
    km_per_degree_lon = 111.32 * math.cos(lat_radians)
    
    return km / ((km_per_degree_lat + km_per_degree_lon) / 2)

def calculate_area_km2(polygon: Polygon) -> float:
    """Calculate polygon area in square kilometers"""
    centroid = polygon.centroid
    lat = centroid.y
    
    coords = list(polygon.exterior.coords)
    area = 0.0
    
    for i in range(len(coords) - 1):
        x1, y1 = coords[i]
        x2, y2 = coords[i + 1]
        
        lat_factor = 111.32  
        lon_factor = 111.32 * math.cos(math.radians(lat))  
        
        x1_km = x1 * lon_factor
        y1_km = y1 * lat_factor
        x2_km = x2 * lon_factor
        y2_km = y2 * lat_factor
        
        area += (x1_km * y2_km - x2_km * y1_km)
    
    return abs(area) / 2.0

def calculate_perimeter_km(polygon: Polygon) -> float:
    """Calculate polygon perimeter in kilometers"""
    coords = list(polygon.exterior.coords)
    perimeter = 0.0
    lat = polygon.centroid.y
    
    lat_factor = 111.32  
    lon_factor = 111.32 * math.cos(math.radians(lat))  
    
    for i in range(len(coords) - 1):
        dx = (coords[i+1][0] - coords[i][0]) * lon_factor
        dy = (coords[i+1][1] - coords[i][1]) * lat_factor
        perimeter += math.sqrt(dx**2 + dy**2)
        
    return perimeter

def scale_polygon(polygon: Polygon, factor: float) -> Polygon:
    """Scale polygon by given factor around its centroid"""
    centroid = polygon.centroid
    
    coords = list(polygon.exterior.coords)
    
    scaled_coords = []
    for x, y in coords:
        x_translated = x - centroid.x
        y_translated = y - centroid.y
        
        x_scaled = x_translated * factor
        y_scaled = y_translated * factor
        
        x_final = x_scaled + centroid.x
        y_final = y_scaled + centroid.y
        
        scaled_coords.append((x_final, y_final))
    
    return Polygon(scaled_coords)

def calculate_priority(error_count: int, area_km2: float) -> int:
    """Calculate patch priority based on error density"""
    error_density = error_count / max(area_km2, 1)
    
    if error_density > 5:
        return 9
    elif error_density > 3:
        return 7
    elif error_density > 1:
        return 5
    else:
        return 3

def calculate_difficulty(area_km2: float, error_count: int) -> str:
    """Calculate patch difficulty based on area and error count"""
    if area_km2 > 25 or error_count > 30:
        return 'hard'
    elif area_km2 > 15 or error_count > 15:
        return 'medium'
    else:
        return 'easy'