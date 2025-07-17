# Osmose Processing Pipeline

A modular Python pipeline for fetching Osmose QA errors from the API and creating geographical patches for mapping projects.

## Overview

The pipeline is split into separate, reusable components:

1. **Database Schema Creation** - Sets up required tables
2. **Osmose Issues Loading** - Fetches errors from Osmose API and stores in database
3. **Patches Creation** - Reads errors from database and creates geographical patches
4. **Pipeline Orchestration** - Runs components in sequence
5. **Maintenance Tools** - Database cleanup and monitoring

## Prerequisites

```bash
pip install requests psycopg2-binary shapely numpy scikit-learn
```

Ensure you have a PostgreSQL database with PostGIS extension enabled.

## Quick Start

### 1. Setup Database Schema

```bash
# Create all required tables
python create_database_schema.py

# Or reset everything and recreate
python create_database_schema.py --drop
```

### 2. Configure Database Connection

Edit `config.py` with your database connection details:

```python
DB_CONFIG = {
    'host': 'your-host',
    'port': 5432,
    'database': 'your-database',
    'user': 'your-username',
    'password': 'your-password'
}
```

### 3. Run the Pipeline

```bash
# Run complete pipeline (recommended)
python run_pipeline.py --full

# Run with data limit for testing
python run_pipeline.py --full --test

# Check database status
python run_pipeline.py --status
```

## Detailed Usage

### Individual Components

#### Load Osmose Issues Only
```bash
# Load all available errors
python osmose_issues_loader.py

# Load with limit
python osmose_issues_loader.py --limit 1000

# Test mode (100 errors)
python osmose_issues_loader.py --test
```

#### Create Patches Only
```bash
# Process all unprocessed errors
python patches_creator.py

# Filter by country (if implemented)
python patches_creator.py --country KZ
```

#### Pipeline Orchestration
```bash
# Full pipeline
python run_pipeline.py --full --limit 5000

# Individual steps
python run_pipeline.py --issues-only --limit 1000
python run_pipeline.py --patches-only

# Database status check
python run_pipeline.py --status
```

### Maintenance and Cleanup

```bash
# Generate database report
python maintenance.py --report

# Clean up old data
python maintenance.py --operations cleanup_old_batches vacuum

# Reset all errors to unprocessed (DESTRUCTIVE)
python maintenance.py --operations reset_errors --confirm

# Delete all patches (DESTRUCTIVE)
python maintenance.py --operations delete_patches --confirm
```

## Configuration

### API Settings (`config.py`)
- `OSMOSE_CONFIG`: API endpoints, country settings, request limits
- `PATCH_CONFIG`: Patch creation parameters (area, clustering, etc.)
- `DB_CONFIG`: Database connection settings

### Key Parameters

**Patch Creation:**
- `TARGET_PATCH_AREA_KM2`: Desired patch size (default: 15 km²)
- `MIN_ERRORS_PER_PATCH`: Minimum errors to create a patch (default: 3)
- `CLUSTER_DISTANCE_KM`: Distance for clustering nearby errors (default: 3 km)

**API Fetching:**
- `FETCH_LIMIT`: Errors per API request (default: 500)
- `REQUEST_DELAY`: Delay between API calls (default: 0.5 seconds)

## Database Schema

### Tables Created

1. **`import_batches`** - Tracks import operations
2. **`osmose_errors`** - Individual QA errors from Osmose
3. **`osmose_patches`** - Generated patches containing multiple errors

### Key Relationships

- `osmose_errors.patch_id` → `osmose_patches.patch_id`
- `osmose_patches.import_batch` → `import_batches.batch_id`

## File Structure

```
├── config.py                  # Configuration settings
├── utils.py                   # Shared utilities and functions
├── create_database_schema.py  # Database table creation
├── osmose_issues_loader.py    # API fetching and error storage
├── patches_creator.py         # Patch creation from errors
├── run_pipeline.py           # Pipeline orchestration
├── maintenance.py            # Database maintenance tools
└── README.md                 # This file
```

## Workflow Examples

### Development/Testing Workflow
```bash
# 1. Setup database
python create_database_schema.py

# 2. Test with small dataset
python run_pipeline.py --full --test

# 3. Check results
python run_pipeline.py --status

# 4. Clean up for next test
python maintenance.py --operations reset_errors delete_patches --confirm
```

### Production Workflow
```bash
# 1. Setup database (one time)
python create_database_schema.py

# 2. Run regular imports
python run_pipeline.py --full --limit 10000

# 3. Monitor and maintain
python maintenance.py --report
python maintenance.py --operations cleanup_old_batches vacuum
```

### Recovery Workflow
```bash
# 1. Check current state
python run_pipeline.py --status

# 2. Re-create patches from existing errors
python run_pipeline.py --patches-only

# 3. Or reload everything
python maintenance.py --operations reset_errors delete_patches --confirm
python run_pipeline.py --full
```

## Monitoring and Troubleshooting

### Check Database Status
```bash
python run_pipeline.py --status
```

### View Detailed Statistics
```bash
python maintenance.py --report
```

### Common Issues

1. **No patches created**: Check if errors have valid coordinates
2. **Duplicate patches**: Normal behavior - duplicates are skipped
3. **Database connection errors**: Verify `config.py` settings
4. **API timeouts**: Reduce `FETCH_LIMIT` or increase `REQUEST_TIMEOUT`

### Logging

All scripts use Python logging. Log levels can be adjusted in `config.py`:

```python
LOGGING_CONFIG = {
    'level': 'DEBUG',  # Change to DEBUG for verbose output
    'format': '%(asctime)s - %(levelname)s - %(message)s'
}
```

## Extending the Pipeline

### Adding New Countries
1. Update `OSMOSE_CONFIG['COUNTRY_CODE']` and `COUNTRY_NAME` in `config.py`
2. Run the pipeline normally

### Custom Patch Creation Logic
Modify the `PatchesCreator` class in `patches_creator.py`:
- `_create_grid_patches()` for grid-based logic
- `_create_patch_from_errors()` for individual patch creation

### Additional Data Sources
Create new loader scripts following the pattern of `osmose_issues_loader.py`

## Performance Considerations

- **Large datasets**: Use `--limit` parameter to process data in chunks
- **Database performance**: Regular VACUUM operations help maintain performance
- **API rate limiting**: Adjust `REQUEST_DELAY` if hitting rate limits
- **Memory usage**: Clustering large datasets may require significant RAM

