#!/usr/bin/env python3
"""
Taiwan Clinic Medical PageIndex RAG System - Database Seeding Script
Phase 01: Foundation - SQLite clinic schema + seed from OriginalData CSV/ODS
"""

import sqlite3
import csv
import os
import sys
from pathlib import Path
from datetime import datetime
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
DATA_DIR = PROJECT_ROOT / "OriginalData"
DB_PATH = PROJECT_ROOT / "clinic.db"
SCHEMA_PATH = PROJECT_ROOT / "src" / "db" / "clinic_schema.sql"

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
    """Update OTC drug names with Taiwan localization."""
    logger.info("Updating OTC drug names with Taiwan localization...")
    
    cursor = conn.cursor()
    
    # OTC localization mapping
    otc_mapping = {
        'ACETAMINOPHEN': '俗稱普拿疼的乙醯胺酚',
        'IBUPROFEN': '常見的布洛芬',
        'ASPIRIN': '阿斯匹靈',
        'DIPHENHYDRAMINE': '抗組織胺（撲爾敏）',
        'LORATADINE': '抗組織胺（開瑞坦）',
        'CETIRIZINE': '抗組織胺（適利達）',
        'OMEPRAZOLE': '胃藥（奧美拉唑）',
        'RANITIDINE': '胃藥（雷尼替丁）',
        'FAMOTIDINE': '胃藥（法莫替丁）',
        'METFORMIN': '糖尿病藥（二甲雙胍）',
        'AMLODIPINE': '降壓藥（氨氯地平）',
        'LOSARTAN': '降壓藥（纈沙坦）',
        'ATORVASTATIN': '降膽固醇藥（阿托伐他汀）',
        'SIMVASTATIN': '降膽固醇藥（辛伐他汀）',
    }
    
    updated_count = 0
    
    for ingredient, otc_name in otc_mapping.items():
        try:
            cursor.execute("""
                UPDATE drugs 
                SET otc_name_chinese = ? 
                WHERE ingredient LIKE ? 
                AND otc_name_chinese IS NULL
            """, (otc_name, f'%{ingredient}%'))
            
            updated_count += cursor.rowcount
            
        except Exception as e:
            logger.warning(f"Error updating OTC name for {ingredient}: {e}")
            continue
    
    conn.commit()
    logger.info(f"Updated {updated_count} drug records with OTC names")
    return updated_count

def create_sample_page_index(conn):
    """Create sample PageIndex trees for testing."""
    logger.info("Creating sample PageIndex trees...")
    
    cursor = conn.cursor()
    
    # Sample clinical reasoning trees
    sample_trees = [
        {
            'doc_id': 'zhiyan-clinic-laser-skin-resurfacing',
            'category': 'special',
            'pre_op': '術前須知：1. 過敏體質需告知醫師 2. 術前2週停止使用A酸 3. 術前1週避免日曬 4. 術前洗臉清潔',
            'procedure': '療程步驟：皮秒雷射利用極短脈衝光束擊碎黑色素，刺激膠原蛋白增生。過程約15-30分鐘，依治療範圍而定。麻醉方式：局部麻醉膏。',
            'post_op_short': '術後照護：1. 術後立即冰敷15-20分鐘 2. 3天內避免化妝 3. 1週內避免日曬 4. 使用醫師指定保養品 5. 避免摳抓結痂',
            'maintenance': '長期維持：1. 每月回診追蹤 2. 加強防曬SPF50+ 3. 定期保濕 4. 維持良好生活作息 5. 效果可維持6-12個月',
            'summary_text': '皮秒雷射術前注意過敏體質、停用A酸、避免日曬。療程利用短脈衝光束擊碎黑色素，約15-30分鐘。術後冰敷、3天內避免化妝、1週避免日曬。每月回診，效果維持6-12個月。'
        },
        {
            'doc_id': 'zhiyan-clinic-botox-injection',
            'category': 'special',
            'pre_op': '術前須知：1. 告知醫師用藥史 2. 術前2週停止服用阿斯匹靈 3. 術前洗臉清潔 4. 避免懷孕或哺乳',
            'procedure': '療程步驟：肉毒桿菌素注射使用極細針頭將藥物注入目標肌肉，放鬆肌肉減少皺紋。過程約10-20分鐘，無需麻醉。',
            'post_op_short': '術後照護：1. 術後4小時避免平躺 2. 24小時內避免按摩注射部位 3. 1週內避免劇烈運動 4. 避免高溫環境（三溫暖、烤箱）',
            'maintenance': '長期維持：1. 每3-6個月回診補打 2. 保持良好表情習慣 3. 配合保養品使用 4. 效果可維持4-6個月',
            'summary_text': '肉毒桿菌素注射術前停止服用阿斯匹靈、洗臉清潔。療程用極細針頭注入目標肌肉，約10-20分鐘。術後4小時避免平躺、24小時避免按摩、1週避免劇烈運動。每3-6個月回診，效果維持4-6個月。'
        }
    ]
    
    inserted_count = 0
    
    for tree in sample_trees:
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO page_index_trees (
                    doc_id, category, pre_op, procedure, post_op_short, maintenance,
                    summary_text, version, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                tree['doc_id'],
                tree['category'],
                tree['pre_op'],
                tree['procedure'],
                tree['post_op_short'],
                tree['maintenance'],
                tree['summary_text'],
                '2.0',
                datetime.now().isoformat()
            ))
            
            inserted_count += 1
            
        except Exception as e:
            logger.warning(f"Error inserting PageIndex tree: {e}")
            continue
    
    conn.commit()
    logger.info(f"Created {inserted_count} sample PageIndex trees")
    return inserted_count

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
        
        # Create sample PageIndex trees
        page_index_count = create_sample_page_index(conn)
        
        # Verify import
        stats = verify_import(conn)
        
        # Close connection
        conn.close()
        
        logger.info("Database seeding completed successfully!")
        logger.info(f"Summary:")
        logger.info(f"  - Drugs: {stats['drugs']:,} records")
        logger.info(f"  - Service items: {stats['service_items']:,} records")
        logger.info(f"  - Clinics: {stats['clinics']} records")
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