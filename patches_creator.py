#!/usr/bin/env python3
"""
Patches Creator - Reads Osmose errors from database and creates patches
"""

import json
import hashlib
import math
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from psycopg2.extras import RealDictCursor, Json
import numpy as np
from sklearn.cluster import DBSCAN
from shapely.geometry import Point, Polygon, MultiPoint, box
from shapely.ops import unary_union

from config import OSMOSE_CONFIG, PATCH_CONFIG
from utils import (
    get_db_connection, close_db_connection, setup_logging,
    km_to_degrees, calculate_area_km2, calculate_perimeter_km,
    scale_polygon, calculate_priority, calculate_difficulty
)

logger = setup_logging()

class PatchesCreator:
    """Creates patches from Osmose errors stored in database"""
    
    def __init__(self):
        self.conn = None
        self.batch_id = None
        
    def connect_db(self):
        """Connect to database"""
        self.conn = get_db_connection()
        logger.info("Connected to database")
            
    def close_db(self):
        """Close database connection"""
        if self.conn:
            close_db_connection(self.conn)
            
    def load_unprocessed_errors(self, country_code: Optional[str] = None) -> List[Dict]:
        """Load errors that haven't been assigned to patches yet"""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            query = """
                SELECT 
                    error_id,
                    ST_X(location) as lon,
                    ST_Y(location) as lat,
                    item,
                    class,
                    title,
                    subtitle,
                    username,
                    error_timestamp,
                    osmose_url
                FROM osmose_errors 
                WHERE patch_id IS NULL
            """
            params = []
            
            if country_code:
                # Note: We don't have country_code in osmose_errors table
                # This would need to be added if filtering by country is required
                pass
                
            cur.execute(query, params)
            errors = cur.fetchall()
            
        logger.info(f"Loaded {len(errors)} unprocessed errors")
        return [dict(error) for error in errors]
        
    def create_patches_from_errors(self, errors: List[Dict]) -> List[Dict]:
        """Create patches from error points using grid and clustering approach"""
        if not errors:
            return []
            
        error_points = []
        
        for error in errors:
            lat = error.get('lat')
            lon = error.get('lon')
            error_id = error.get('error_id')
            
            if lat and lon and error_id:
                error_points.append({
                    'id': str(error_id),
                    'lon': lon,
                    'lat': lat,
                    'point': Point(lon, lat),
                    'error': error
                })
                
        if not error_points:
            logger.warning("No valid coordinates found")
            return []
            
        logger.info(f"Creating patches from {len(error_points)} errors")
        
        # Calculate grid size based on target area
        avg_lat = np.mean([p['lat'] for p in error_points])
        grid_size_degrees = km_to_degrees(PATCH_CONFIG['GRID_SIZE_KM'], avg_lat)
        
        patches = self._create_grid_patches(error_points, grid_size_degrees)
        
        logger.info(f"Created {len(patches)} patches")
        return patches
        
    def _create_grid_patches(self, error_points: List[Dict], grid_size: float) -> List[Dict]:
        """Create patches using grid-based and clustering approach"""
        if not error_points:
            return []
            
        lons = [p['lon'] for p in error_points]
        lats = [p['lat'] for p in error_points]
        min_lon, max_lon = min(lons), max(lons)
        min_lat, max_lat = min(lats), max(lats)
        
        patches = []
        
        # Grid-based patches
        lat = min_lat
        while lat < max_lat:
            lon = min_lon
            while lon < max_lon:
                cell_polygon = box(lon, lat, lon + grid_size, lat + grid_size)
                
                cell_errors = []
                for error_point in error_points:
                    if cell_polygon.contains(error_point['point']):
                        cell_errors.append(error_point)
                
                if len(cell_errors) >= PATCH_CONFIG['MIN_ERRORS_PER_PATCH']:
                    patch = self._create_patch_from_errors(cell_errors, cell_polygon)
                    if patch:
                        patches.append(patch)
                
                lon += grid_size
            lat += grid_size
        
        # Clustering-based patches for remaining points
        coordinates = np.array([[p['lon'], p['lat']] for p in error_points])
        eps_degrees = km_to_degrees(PATCH_CONFIG['CLUSTER_DISTANCE_KM'], np.mean(lats))
        
        clustering = DBSCAN(eps=eps_degrees, min_samples=PATCH_CONFIG['MIN_ERRORS_PER_PATCH'])
        labels = clustering.fit_predict(coordinates)
        
        clusters = {}
        for idx, label in enumerate(labels):
            if label >= 0:
                if label not in clusters:
                    clusters[label] = []
                clusters[label].append(error_points[idx])
        
        # Create patches from clusters, avoiding overlaps with grid patches
        for cluster_id, cluster_errors in clusters.items():
            cluster_points = [e['point'] for e in cluster_errors]
            cluster_polygon = MultiPoint(cluster_points).convex_hull
            
            # Check for overlap with existing patches
            overlap = False
            for existing_patch in patches:
                existing_geom = existing_patch['geometry']
                if isinstance(existing_geom, dict):
                    from shapely.geometry import shape
                    existing_polygon = shape(existing_geom)
                else:
                    existing_polygon = existing_geom
                    
                if cluster_polygon.intersects(existing_polygon):
                    intersection_area = cluster_polygon.intersection(existing_polygon).area
                    if intersection_area > 0.5 * cluster_polygon.area:
                        overlap = True
                        break
            
            if not overlap:
                patch = self._create_patch_from_errors(cluster_errors)
                if patch:
                    patches.append(patch)
        
        return patches
        
    def _create_patch_from_errors(self, error_points: List[Dict], 
                                base_polygon: Optional[Polygon] = None) -> Optional[Dict]:
        """Create a single patch from error points"""
        try:
            if len(error_points) < PATCH_CONFIG['MIN_ERRORS_PER_PATCH']:
                return None
                
            points = [e['point'] for e in error_points]
            multipoint = MultiPoint(points)
            
            if base_polygon:
                polygon = base_polygon
            else:
                if len(points) >= 3:
                    polygon = multipoint.convex_hull
                    buffer_degrees = km_to_degrees(
                        PATCH_CONFIG['BUFFER_SIZE_KM'], 
                        multipoint.centroid.y
                    )
                    polygon = polygon.buffer(buffer_degrees)
                else:
                    # Create a box around points
                    bounds = multipoint.bounds
                    center_lon = (bounds[0] + bounds[2]) / 2
                    center_lat = (bounds[1] + bounds[3]) / 2
                    half_size = km_to_degrees(
                        PATCH_CONFIG['DEFAULT_PATCH_SIZE_KM'], 
                        center_lat
                    )
                    polygon = box(
                        center_lon - half_size, center_lat - half_size,
                        center_lon + half_size, center_lat + half_size
                    )
            
            # Adjust polygon size if needed
            area_km2 = calculate_area_km2(polygon)
            
            if area_km2 < PATCH_CONFIG['MIN_PATCH_AREA_KM2']:
                scale_factor = math.sqrt(PATCH_CONFIG['TARGET_PATCH_AREA_KM2'] / area_km2)
                polygon = scale_polygon(polygon, scale_factor)
                area_km2 = calculate_area_km2(polygon)
            elif area_km2 > PATCH_CONFIG['MAX_PATCH_AREA_KM2']:
                scale_factor = math.sqrt(PATCH_CONFIG['TARGET_PATCH_AREA_KM2'] / area_km2)
                polygon = scale_polygon(polygon, scale_factor)
                area_km2 = calculate_area_km2(polygon)
            
            perimeter_km = calculate_perimeter_km(polygon)
            
            error_ids = [e['id'] for e in error_points]
            errors = [e['error'] for e in error_points]
            
            patch = {
                'geometry': polygon.__geo_interface__,
                'osmose_ids': sorted(error_ids),
                'area_km2': round(area_km2, 3),
                'perimeter_km': round(perimeter_km, 3),
                'error_count': len(error_ids),
                'errors': errors,
                'centroid': {
                    'lon': polygon.centroid.x,
                    'lat': polygon.centroid.y
                }
            }
            
            return patch
            
        except Exception as e:
            logger.error(f"Failed to create patch: {e}")
            return None
            
    def create_import_batch(self) -> str:
        """Create a new import batch for patches"""
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO import_batches (
                    imported_by,
                    country_code,
                    source_file
                ) VALUES (
                    %s, %s, %s
                ) RETURNING batch_id
            """, (
                'patches_creator',
                OSMOSE_CONFIG['COUNTRY_CODE'],
                f'patches_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
            ))
            self.batch_id = cur.fetchone()[0]
            self.conn.commit()
            
        logger.info(f"Created patches batch: {self.batch_id}")
        return self.batch_id
        
    def insert_patches(self, patches: List[Dict]) -> Tuple[int, int, int]:
        """Insert patches into database and update error records"""
        success_count = 0
        duplicate_count = 0
        error_count = 0
        
        with self.conn.cursor() as cur:
            for patch in patches:
                try:
                    patch_id = self._generate_patch_id(patch['osmose_ids'])
                    
                    # Check for duplicates
                    cur.execute("""
                        SELECT COUNT(*) FROM osmose_patches 
                        WHERE patch_id = %s
                    """, (patch_id,))
                    
                    if cur.fetchone()[0] > 0:
                        duplicate_count += 1
                        continue
                        
                    # Insert patch
                    cur.execute("""
                        INSERT INTO osmose_patches (
                            patch_id,
                            geometry,
                            country_code,
                            country_name,
                            osmose_ids,
                            area_km2,
                            perimeter_km,
                            error_count,
                            source_file,
                            import_batch,
                            priority,
                            difficulty,
                            metadata
                        ) VALUES (
                            %s,
                            ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326),
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                    """, (
                        patch_id,
                        json.dumps(patch['geometry']),
                        OSMOSE_CONFIG['COUNTRY_CODE'],
                        OSMOSE_CONFIG['COUNTRY_NAME'],
                        patch['osmose_ids'],
                        patch['area_km2'],
                        patch['perimeter_km'],
                        patch['error_count'],
                        f'patches_{OSMOSE_CONFIG["ITEM"]}',
                        self.batch_id,
                        calculate_priority(patch['error_count'], patch['area_km2']),
                        calculate_difficulty(patch['area_km2'], patch['error_count']),
                        Json({
                            'created_date': datetime.now().isoformat(),
                            'centroid': patch['centroid'],
                            'source': 'patches_creator'
                        })
                    ))
                    
                    # Update osmose_errors with patch_id
                    for error_id in patch['osmose_ids']:
                        cur.execute("""
                            UPDATE osmose_errors 
                            SET patch_id = %s, updated_at = CURRENT_TIMESTAMP
                            WHERE error_id = %s
                        """, (patch_id, error_id))
                        
                    success_count += 1
                    self.conn.commit()
                    
                    logger.info(f"Inserted patch {patch_id}: {patch['area_km2']:.1f} km², {patch['error_count']} errors")
                    
                except Exception as e:
                    error_count += 1
                    logger.error(f"Failed to insert patch: {e}")
                    self.conn.rollback()
                    continue
                    
        # Update batch statistics
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE import_batches
                SET patches_count = %s,
                    errors_count = %s,
                    new_patches = %s,
                    duplicate_patches = %s,
                    failed_patches = %s
                WHERE batch_id = %s
            """, (
                success_count + duplicate_count + error_count,
                sum(len(p['osmose_ids']) for p in patches),
                success_count,
                duplicate_count,
                error_count,
                self.batch_id
            ))
            self.conn.commit()
            
        return success_count, duplicate_count, error_count
        
    def _generate_patch_id(self, osmose_ids: List[str]) -> str:
        """Generate unique patch ID from osmose error IDs"""
        sorted_ids = sorted(osmose_ids)
        
        if len(sorted_ids) <= 3:
            short_ids = []
            for id_str in sorted_ids:
                if len(id_str) > 8 and '-' in id_str:  
                    short_ids.append(id_str[:8])
                else:
                    short_ids.append(id_str)
            return f"{OSMOSE_CONFIG['COUNTRY_CODE']}_{'_'.join(short_ids)}"
        else:
            hash_str = hashlib.md5('_'.join(sorted_ids).encode()).hexdigest()[:12]
            return f"{OSMOSE_CONFIG['COUNTRY_CODE']}_MERGED_{len(sorted_ids)}_{hash_str}"
            
    def get_summary_stats(self) -> Dict:
        """Get summary statistics"""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Patch statistics
            cur.execute("""
                SELECT 
                    COUNT(*) as total_patches,
                    AVG(area_km2) as avg_area,
                    AVG(error_count) as avg_errors,
                    SUM(error_count) as total_errors_in_patches
                FROM osmose_patches
            """)
            patch_stats = cur.fetchone()
            
            # Unprocessed errors
            cur.execute("""
                SELECT COUNT(*) as unprocessed_errors 
                FROM osmose_errors 
                WHERE patch_id IS NULL
            """)
            unprocessed = cur.fetchone()
            
            # Recent patches from this batch
            cur.execute("""
                SELECT patch_id, error_count, area_km2, priority, difficulty
                FROM osmose_patches
                WHERE import_batch = %s
                ORDER BY error_count DESC
                LIMIT 5
            """, (self.batch_id,))
            sample_patches = cur.fetchall()
            
            return {
                'patch_stats': dict(patch_stats),
                'unprocessed_errors': unprocessed['unprocessed_errors'],
                'sample_patches': [dict(p) for p in sample_patches]
            }
            
    def run(self, country_code: Optional[str] = None):
        """Run the complete patch creation process"""
        try:
            self.connect_db()
            self.create_import_batch()
            
            # Load unprocessed errors
            errors = self.load_unprocessed_errors(country_code)
            
            if not errors:
                logger.warning("No unprocessed errors found")
                return
                
            # Create patches
            patches = self.create_patches_from_errors(errors)
            
            if not patches:
                logger.warning("No patches created")
                return
                
            # Insert patches
            success, duplicates, failures = self.insert_patches(patches)
            
            # Print summary
            logger.info(f"\nPatches Creation Summary:")
            logger.info(f"  Errors processed: {len(errors)}")
            logger.info(f"  Patches created: {len(patches)}")
            logger.info(f"  Successfully imported: {success}")
            logger.info(f"  Duplicates skipped: {duplicates}")
            logger.info(f"  Failed: {failures}")
            logger.info(f"  Batch ID: {self.batch_id}")
            
            # Get and display stats
            stats = self.get_summary_stats()
            logger.info(f"\nDatabase Stats:")
            logger.info(f"  Total patches: {stats['patch_stats']['total_patches']}")
            logger.info(f"  Average area: {stats['patch_stats']['avg_area']:.2f} km²")
            logger.info(f"  Average errors per patch: {stats['patch_stats']['avg_errors']:.1f}")
            logger.info(f"  Unprocessed errors remaining: {stats['unprocessed_errors']}")
            
            if stats['sample_patches']:
                logger.info("\nSample created patches:")
                for patch in stats['sample_patches']:
                    logger.info(f"  {patch['patch_id']}: {patch['error_count']} errors, "
                              f"{patch['area_km2']} km², priority={patch['priority']}, "
                              f"difficulty={patch['difficulty']}")
            
            return self.batch_id
            
        except Exception as e:
            logger.error(f"Patch creation failed: {e}")
            raise
        finally:
            self.close_db()


def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Create patches from Osmose errors')
    parser.add_argument('--country', help='Country code to filter errors')
    
    args = parser.parse_args()
    
    creator = PatchesCreator()
    batch_id = creator.run(country_code=args.country)
    
    print(f"\nCompleted patch creation with batch ID: {batch_id}")


if __name__ == "__main__":
    main()