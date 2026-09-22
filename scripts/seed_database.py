#!/usr/bin/env python3
"""
Taiwan Clinic Medical PageIndex RAG System - Database Seeding Script
Phase 01: Foundation - SQLite clinic schema + seed from OriginalData CSV/ODS
"""

import sqlite3
import csv
import json
import os
import sys
from pathlib import Path
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('seed_database.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
# OriginalData/ 已於 2026-09-22 重新整理，NHI 藥品/服務項目 CSV 移至「一般醫學/健保相關/」
DATA_DIR = PROJECT_ROOT / "OriginalData" / "一般醫學" / "健保相關"
DB_PATH = PROJECT_ROOT / "clinic.db"
SCHEMA_PATH = PROJECT_ROOT / "src" / "db" / "clinic_schema.sql"
OTC_MAPPINGS_PATH = PROJECT_ROOT / "src" / "db" / "otc_mappings.json"

# Ensure project root is in sys.path for relative imports
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from src.clinic.custom_notes import seed_sample_notes
    from src.pageindex.seed_clinic_info import seed_clinic_info
except ImportError:
    from clinic.custom_notes import seed_sample_notes
    from pageindex.seed_clinic_info import seed_clinic_info

def create_database():
    """Create database and apply schema."""
    logger.info(f"Creating database at {DB_PATH}")
    
    # Remove existing database if it exists
    if DB_PATH.exists():
        logger.warning(f"Removing existing database: {DB_PATH}")
        DB_PATH.unlink()
    
    # Create database connection
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    # Apply schema
    logger.info("Applying schema...")
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        schema_sql = f.read()
        cursor.executescript(schema_sql)
    
    conn.commit()
    logger.info("Schema applied successfully")
    return conn

def import_drugs(conn):
    """Import drugs from CSV file."""
    logger.info("Importing drugs from CSV...")
    
    # Find drug CSV file
    drug_csv_path = DATA_DIR / "藥品項查詢項目檔260101.csv"
    if not drug_csv_path.exists():
        logger.error(f"Drug CSV not found: {drug_csv_path}")
        return 0
    
    cursor = conn.cursor()
    count = 0
    
    try:
        with open(drug_csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                try:
                    # Extract relevant fields
                    code = row.get('藥品代號', '').strip()
                    if not code:
                        continue
                    
                    # Insert drug record
                    cursor.execute("""
                        INSERT OR IGNORE INTO drugs (
                            code, atc_code, classification, dosage_form, compound_type,
                            ingredient, payment_price, effective_start, effective_end,
                            change_indicator, chinese_name, fda_link, drug_category,
                            english_name, manufacturer, specification_unit,
                            specification_quantity, coverage_rules, ai_note
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        code,
                        row.get('ATC代碼', '').strip(),
                        row.get('分類分組名稱', '').strip(),
                        row.get('劑型', '').strip(),
                        row.get('單複方', '').strip(),
                        row.get('成分', '').strip(),
                        float(row.get('支付價', '0') or '0'),
                        row.get('有效起日', '').strip(),
                        row.get('有效迄日', '').strip(),
                        row.get('異動', '').strip(),
                        row.get('藥品中文名稱', '').strip(),
                        row.get('藥品代碼超連結', '').strip(),
                        row.get('藥品分類', '').strip(),
                        row.get('藥品英文名稱', '').strip(),
                        row.get('藥商', '').strip(),
                        row.get('規格單位', '').strip(),
                        row.get('規格量', '').strip(),
                        row.get('給付規定', '').strip(),
                        row.get('AI-note', '').strip()
                    ))
                    
                    count += 1
                    if count % 10000 == 0:
                        logger.info(f"Imported {count} drugs...")
                        
                except Exception as e:
                    logger.warning(f"Error importing drug row: {e}")
                    continue
        
        conn.commit()
        logger.info(f"Successfully imported {count} drugs")
        
    except Exception as e:
        logger.error(f"Error importing drugs: {e}")
        raise
    
    return count

def import_service_items(conn):
    """Import service items from CSV file."""
    logger.info("Importing service items from CSV...")
    
    # Find service items CSV file
    service_csv_path = DATA_DIR / "醫療服務給付項目251027準確板_已填入支付規定.csv"
    if not service_csv_path.exists():
        logger.error(f"Service items CSV not found: {service_csv_path}")
        return 0
    
    cursor = conn.cursor()
    count = 0
    
    try:
        with open(service_csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                try:
                    # Extract relevant fields
                    code = row.get('診療項目代碼', '').strip()
                    if not code:
                        continue
                    
                    # Insert service item record
                    cursor.execute("""
                        INSERT OR IGNORE INTO service_items (
                            code, points, effective_start, effective_end,
                            english_name, chinese_name, payment_rules
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        code,
                        int(row.get('健保支付點數', '0') or '0'),
                        row.get('生效起日', '').strip(),
                        row.get('生效迄日', '').strip(),
                        row.get('英文項目名稱', '').strip(),
                        row.get('中文項目名稱', '').strip(),
                        row.get('支付規定', '').strip()
                    ))
                    
                    count += 1
                    if count % 5000 == 0:
                        logger.info(f"Imported {count} service items...")
                        
                except Exception as e:
                    logger.warning(f"Error importing service item row: {e}")
                    continue
        
        conn.commit()
        logger.info(f"Successfully imported {count} service items")
        
    except Exception as e:
        logger.error(f"Error importing service items: {e}")
        raise
    
    return count

def update_otc_names(conn):
    """Update OTC drug names with Taiwan localization from JSON configuration."""
    logger.info("Updating OTC drug names with Taiwan localization...")
    
    cursor = conn.cursor()
    
    if not OTC_MAPPINGS_PATH.exists():
        logger.error(f"OTC mappings file not found: {OTC_MAPPINGS_PATH}")
        return 0
    
    with open(OTC_MAPPINGS_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    mappings = config.get("mappings", [])
    logger.info(f"Loaded {len(mappings)} OTC mapping rules from {OTC_MAPPINGS_PATH.name}")
    
    updated_count = 0
    
    for item in mappings:
        otc_name = item["otc_name_chinese"]
        patterns = [item["pattern"]] + item.get("aliases", [])
        for pattern in patterns:
            try:
                cursor.execute("""
                    UPDATE drugs 
                    SET otc_name_chinese = ? 
                    WHERE ingredient LIKE ? 
                    AND otc_name_chinese IS NULL
                """, (otc_name, f'%{pattern}%'))
                
                updated_count += cursor.rowcount
            except Exception as e:
                logger.warning(f"Error updating OTC name for {pattern}: {e}")
                continue
    
    conn.commit()
    logger.info(f"Updated {updated_count} drug records with OTC names")
    return updated_count

def verify_import(conn):
    """Verify the import was successful."""
    logger.info("Verifying import...")
    
    cursor = conn.cursor()
    
    # Count drugs
    cursor.execute("SELECT COUNT(*) FROM drugs")
    drug_count = cursor.fetchone()[0]
    logger.info(f"Drugs: {drug_count:,} records")
    
    # Count service items
    cursor.execute("SELECT COUNT(*) FROM service_items")
    service_count = cursor.fetchone()[0]
    logger.info(f"Service items: {service_count:,} records")
    
    # Count clinic info
    cursor.execute("SELECT COUNT(*) FROM clinic_info")
    clinic_count = cursor.fetchone()[0]
    logger.info(f"Clinics: {clinic_count} records")

    # Count clinic custom notes
    cursor.execute("SELECT COUNT(*) FROM clinic_custom_notes")
    custom_notes_count = cursor.fetchone()[0]
    logger.info(f"Clinic custom notes: {custom_notes_count} records")
    
    # Count PageIndex trees
    cursor.execute("SELECT COUNT(*) FROM page_index_trees")
    page_index_count = cursor.fetchone()[0]
    logger.info(f"PageIndex trees: {page_index_count} records")
    
    # Test FTS search
    logger.info("Testing FTS search...")
    cursor.execute("SELECT COUNT(*) FROM drugs_fts")
    drugs_fts_count = cursor.fetchone()[0]
    logger.info(f"Drugs FTS entries: {drugs_fts_count:,}")
    
    cursor.execute("SELECT COUNT(*) FROM service_items_fts")
    service_fts_count = cursor.fetchone()[0]
    logger.info(f"Service items FTS entries: {service_fts_count:,}")
    
    cursor.execute("SELECT COUNT(*) FROM page_index_fts")
    page_index_fts_count = cursor.fetchone()[0]
    logger.info(f"PageIndex FTS entries: {page_index_fts_count:,}")
    
    return {
        'drugs': drug_count,
        'service_items': service_count,
        'clinics': clinic_count,
        'clinic_custom_notes': custom_notes_count,
        'page_index_trees': page_index_count,
        'drugs_fts': drugs_fts_count,
        'service_items_fts': service_fts_count,
        'page_index_fts': page_index_fts_count
    }

def main():
    """Main function to seed the database."""
    logger.info("Starting database seeding...")
    
    try:
        # Create database and apply schema
        conn = create_database()
        
        # Import data
        drug_count = import_drugs(conn)
        service_count = import_service_items(conn)
        
        # Update OTC names
        otc_count = update_otc_names(conn)

        # Seed clinic info (basic clinic profile)
        clinic_info_count = seed_clinic_info(conn)
        logger.info(f"Seeded {clinic_info_count} clinic info records")

        # Seed clinic custom notes (clinic-level general notes)
        notes_count = seed_sample_notes(conn)
        logger.info(f"Seeded {notes_count} clinic custom notes")

        # PageIndex trees are seeded separately by src/pageindex/seed_trees.py
        # (incremental upsert — see CONTENT_FIELDS/content_version logic there)

        # Verify import
        stats = verify_import(conn)
        
        # Close connection
        conn.close()
        
        logger.info("Database seeding completed successfully!")
        logger.info(f"Summary:")
        logger.info(f"  - Drugs: {stats['drugs']:,} records")
        logger.info(f"  - Service items: {stats['service_items']:,} records")
        logger.info(f"  - Clinics: {stats['clinics']} records")
        logger.info(f"  - Clinic custom notes: {stats['clinic_custom_notes']} records")
        logger.info(f"  - PageIndex trees: {stats['page_index_trees']} records")
        logger.info(f"  - Drugs FTS: {stats['drugs_fts']:,} entries")
        logger.info(f"  - Service items FTS: {stats['service_items_fts']:,} entries")
        logger.info(f"  - PageIndex FTS: {stats['page_index_fts']:,} entries")
        logger.info(f"  - OTC names updated: {otc_count} records")
        logger.info(f"Database saved to: {DB_PATH}")
        
        return 0
        
    except Exception as e:
        logger.error(f"Database seeding failed: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())