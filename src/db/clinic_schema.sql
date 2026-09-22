-- Taiwan Clinic Medical PageIndex RAG System - SQLite Schema
-- Phase 01: Foundation - SQLite clinic schema + seed from OriginalData CSV/ODS

-- Enable WAL mode for better concurrent access
PRAGMA journal_mode=WAL;

-- ========================================
-- General Layer Tables (Read-only, auto-updated from NHI)
-- ========================================

-- Drugs table - 377K+ Taiwan NHI drug items
CREATE TABLE IF NOT EXISTS drugs (
    code TEXT PRIMARY KEY,           -- 藥品代碼 (e.g., AC55556100)
    atc_code TEXT,                   -- ATC代碼 (e.g., N05AL05)
    classification TEXT,             -- 分類分組名稱 (e.g., "AMISULPRIDE , 一般錠劑膠囊劑 , 200.00 MG")
    dosage_form TEXT,                -- 劑型 (e.g., 錠劑)
    compound_type TEXT,              -- 單複方 (e.g., 單方)
    ingredient TEXT,                 -- 成分 (e.g., AMISULPRIDE 200 MG)
    payment_price TWN,               -- 支付價 (e.g., 13.5)
    effective_start DATE,            -- 有效起日 (e.g., 1140401)
    effective_end DATE,              -- 有效迄日 (e.g., 9991231)
    change_indicator TEXT,           -- 異動
    chinese_name TEXT,               -- 藥品中文名稱 (e.g., "信東"安復寧錠 200 毫克)
    fda_link TEXT,                   -- 藥品代碼超連結
    drug_category TEXT,              -- 藥品分類 (e.g., BA/BE學名藥)
    english_name TEXT,               -- 藥品英文名稱 (e.g., Amsulpin Tablets 200mg)
    manufacturer TEXT,               -- 藥商 (e.g., 信東生技股份有限公司)
    specification_unit TEXT,         -- 規格單位
    specification_quantity TEXT,     -- 規格量
    coverage_rules TEXT,             -- 給付規定
    ai_note TEXT,                    -- AI-note (from drug CSV)
    otc_name_chinese TEXT,           -- 台灣俗名 (derived: 乙醯胺酚→普拿疼的乙醯胺酚)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Service items table - 42K+ Taiwan medical service items
CREATE TABLE IF NOT EXISTS service_items (
    code TEXT PRIMARY KEY,           -- 診療項目代碼 (e.g., 00304C)
    points INTEGER,                  -- 健保支付點數 (e.g., 200)
    effective_start DATE,            -- 生效起日 (e.g., 20160401)
    effective_end DATE,              -- 生效迄日 (e.g., 29101231)
    english_name TEXT,               -- 英文項目名稱
    chinese_name TEXT,               -- 中文項目名稱
    payment_rules TEXT,              -- 支付規定
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ICD-10-PCS codes table (from ICD ODS file)
CREATE TABLE IF NOT EXISTS icd10_pcs (
    code TEXT PRIMARY KEY,           -- ICD-10-PCS code
    description TEXT,                -- Code description
    category TEXT,                   -- Category (e.g., 環境, 伤害)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ========================================
-- Clinic-Specific Layer Tables (Writeable, per-clinic data)
-- ========================================

-- Clinic information table
CREATE TABLE IF NOT EXISTS clinic_info (
    clinic_id TEXT PRIMARY KEY,      -- Unique clinic identifier (e.g., "zhiyan-clinic")
    name TEXT NOT NULL,              -- Clinic name (e.g., 緻妍外科診所)
    phone TEXT,                      -- Phone number
    address TEXT,                    -- Full address
    website TEXT,                    -- Website URL
    opening_date DATE,              -- Opening date
    clinic_type TEXT,                -- Type (e.g., 醫美診所, 牙科診所, 復健科診所)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Clinic hours table (weekly schedule)
CREATE TABLE IF NOT EXISTS clinic_hours (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clinic_id TEXT NOT NULL,
    day_of_week TEXT NOT NULL,       -- 星期一 to 星期日
    morning_start TEXT,              -- 早上開始時間 (e.g., 09:00)
    morning_end TEXT,                -- 早上結束時間
    afternoon_start TEXT,            -- 下午開始時間
    afternoon_end TEXT,              -- 下午結束時間
    evening_start TEXT,              -- 晚上開始時間 (if applicable)
    evening_end TEXT,                -- 晚上結束時間
    is_open BOOLEAN DEFAULT 1,       -- 是否開診
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (clinic_id) REFERENCES clinic_info(clinic_id)
);

-- Clinic custom notes table (for clinical reasoning trees)
CREATE TABLE IF NOT EXISTS clinic_custom_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clinic_id TEXT NOT NULL,
    section TEXT NOT NULL,           -- pre_op, procedure, post_op_short, maintenance
    note TEXT NOT NULL,              -- Physician's custom note
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (clinic_id) REFERENCES clinic_info(clinic_id)
);

-- ========================================
-- PageIndex Tables (Clinical Reasoning Trees)
-- ========================================

-- PageIndex trees table - Clinical reasoning trees for medical procedures
CREATE TABLE IF NOT EXISTS page_index_trees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT UNIQUE,              -- Document identifier (e.g., procedure name slug)
    clinic_id TEXT REFERENCES clinic_info(clinic_id),  -- 所屬診所（2026-09-22 Phase 04 新增；原本診所身份只靠 doc_id 字串前綴表達，是技術債）
    category TEXT NOT NULL,          -- 'special' or 'general'
    pre_op TEXT,                     -- 術前須知與禁忌 (Pre-op instructions)
    pre_op_physician_notes TEXT,     -- 醫師權威指令 (Pre-op physician notes)
    procedure TEXT,                  -- 療程步驟與原理 (Procedure steps)
    procedure_physician_notes TEXT,  -- 醫師權威指令 (Procedure physician notes)
    post_op_short TEXT,              -- 術後立即照護 (Immediate post-op care)
    post_op_short_physician_notes TEXT, -- 醫師權威指令 (Post-op physician notes)
    maintenance TEXT,                -- 長期維持與保養 (Long-term maintenance)
    maintenance_physician_notes TEXT, -- 醫師權威指令 (Maintenance physician notes)
    summary_text TEXT,               -- Combined summary for FTS
    version TEXT DEFAULT '2.0',      -- Schema version (format version, not content revision)
    source_type TEXT DEFAULT 'manual', -- 'manual'（人工手寫）| 'llm_generated'（LLM 生成）| 'clinic_upload'（診所上傳擷取）
    content_version INTEGER NOT NULL DEFAULT 1, -- 內容修訂版本號，每次實質內容變更遞增
    needs_regeneration BOOLEAN NOT NULL DEFAULT 0, -- 標記為過時/待夜間批次重新生成
    indexed_at TIMESTAMP,            -- When indexed
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ========================================
-- FTS5 Virtual Tables (Full-Text Search)
-- ========================================

-- FTS5 for drugs table (trigram tokenizer: only CJK-viable option in FTS5,
-- since unicode61 does not segment Chinese text into meaningful tokens)
CREATE VIRTUAL TABLE IF NOT EXISTS drugs_fts USING fts5(
    code,
    chinese_name,
    english_name,
    ingredient,
    otc_name_chinese,
    content='drugs',
    content_rowid='rowid',
    tokenize='trigram'
);

-- FTS5 for service items
CREATE VIRTUAL TABLE IF NOT EXISTS service_items_fts USING fts5(
    code,
    chinese_name,
    english_name,
    content='service_items',
    content_rowid='rowid',
    tokenize='trigram'
);

-- FTS5 for page_index_trees (clinical reasoning trees)
CREATE VIRTUAL TABLE IF NOT EXISTS page_index_fts USING fts5(
    summary_text,
    content='page_index_trees',
    content_rowid='id',
    tokenize='trigram'
);

-- ========================================
-- Indexes for Performance
-- ========================================

-- Drug table indexes
CREATE INDEX IF NOT EXISTS idx_drugs_atc ON drugs(atc_code);
CREATE INDEX IF NOT EXISTS idx_drugs_ingredient ON drugs(ingredient);
CREATE INDEX IF NOT EXISTS idx_drugs_chinese_name ON drugs(chinese_name);

-- Service items indexes
CREATE INDEX IF NOT EXISTS idx_service_items_chinese_name ON service_items(chinese_name);

-- Clinic hours index
CREATE INDEX IF NOT EXISTS idx_clinic_hours_clinic_id ON clinic_hours(clinic_id);

-- PageIndex trees indexes
CREATE INDEX IF NOT EXISTS idx_page_index_category ON page_index_trees(category);
CREATE INDEX IF NOT EXISTS idx_page_index_doc_id ON page_index_trees(doc_id);
CREATE INDEX IF NOT EXISTS idx_page_index_needs_regeneration ON page_index_trees(needs_regeneration);

-- ========================================
-- Triggers for FTS Updates
-- ========================================

-- Trigger for drugs FTS updates
CREATE TRIGGER IF NOT EXISTS drugs_ai AFTER INSERT ON drugs BEGIN
    INSERT INTO drugs_fts(rowid, code, chinese_name, english_name, ingredient, otc_name_chinese)
    VALUES (new.rowid, new.code, new.chinese_name, new.english_name, new.ingredient, new.otc_name_chinese);
END;

CREATE TRIGGER IF NOT EXISTS drugs_ad AFTER DELETE ON drugs BEGIN
    INSERT INTO drugs_fts(drugs_fts, rowid, code, chinese_name, english_name, ingredient, otc_name_chinese)
    VALUES ('delete', old.rowid, old.code, old.chinese_name, old.english_name, old.ingredient, old.otc_name_chinese);
END;

CREATE TRIGGER IF NOT EXISTS drugs_au AFTER UPDATE ON drugs BEGIN
    INSERT INTO drugs_fts(drugs_fts, rowid, code, chinese_name, english_name, ingredient, otc_name_chinese)
    VALUES ('delete', old.rowid, old.code, old.chinese_name, old.english_name, old.ingredient, old.otc_name_chinese);
    INSERT INTO drugs_fts(rowid, code, chinese_name, english_name, ingredient, otc_name_chinese)
    VALUES (new.rowid, new.code, new.chinese_name, new.english_name, new.ingredient, new.otc_name_chinese);
END;

-- Trigger for service_items FTS updates
CREATE TRIGGER IF NOT EXISTS service_items_ai AFTER INSERT ON service_items BEGIN
    INSERT INTO service_items_fts(rowid, code, chinese_name, english_name)
    VALUES (new.rowid, new.code, new.chinese_name, new.english_name);
END;

CREATE TRIGGER IF NOT EXISTS service_items_ad AFTER DELETE ON service_items BEGIN
    INSERT INTO service_items_fts(service_items_fts, rowid, code, chinese_name, english_name)
    VALUES ('delete', old.rowid, old.code, old.chinese_name, old.english_name);
END;

CREATE TRIGGER IF NOT EXISTS service_items_au AFTER UPDATE ON service_items BEGIN
    INSERT INTO service_items_fts(service_items_fts, rowid, code, chinese_name, english_name)
    VALUES ('delete', old.rowid, old.code, old.chinese_name, old.english_name);
    INSERT INTO service_items_fts(rowid, code, chinese_name, english_name)
    VALUES (new.rowid, new.code, new.chinese_name, new.english_name);
END;

-- Trigger for page_index_trees FTS updates
-- 注意：updated_at 刻意不用 trigger 自動維護（避免 UPDATE trigger 內再次
-- UPDATE 自身資料表造成的遞迴風險），改由應用層寫入時明確帶入 CURRENT_TIMESTAMP。
CREATE TRIGGER IF NOT EXISTS page_index_ai AFTER INSERT ON page_index_trees BEGIN
    INSERT INTO page_index_fts(rowid, summary_text)
    VALUES (new.id, new.summary_text);
END;

CREATE TRIGGER IF NOT EXISTS page_index_ad AFTER DELETE ON page_index_trees BEGIN
    INSERT INTO page_index_fts(page_index_fts, rowid, summary_text)
    VALUES ('delete', old.id, old.summary_text);
END;

CREATE TRIGGER IF NOT EXISTS page_index_au AFTER UPDATE ON page_index_trees BEGIN
    INSERT INTO page_index_fts(page_index_fts, rowid, summary_text)
    VALUES ('delete', old.id, old.summary_text);
    INSERT INTO page_index_fts(rowid, summary_text)
    VALUES (new.id, new.summary_text);
END;

-- ========================================
-- Sample Data (for testing)
-- ========================================

-- clinic_info 的種子資料唯一權威來源是 src/pageindex/seed_clinic_info.py
-- （2026-09-22 Phase 04 修正：這裡原本也有一份重複的 INSERT OR IGNORE，
-- 跟 seed_clinic_info.py 各自維護同一筆資料，違反 AGENTS.md 2.2 節的
-- 單一寫入路徑原則——TASK-003 時 scripts/seed_database.py 與
-- seed_trees.py 就踩過這個雷。schema.sql 只保留表結構，不再內嵌資料）

-- Sample clinic hours (for testing)
INSERT OR IGNORE INTO clinic_hours (clinic_id, day_of_week, morning_start, morning_end, afternoon_start, afternoon_end)
VALUES 
('3503190424', '星期一', '09:00', '12:00', '13:30', '17:30'),
('3503190424', '星期二', '09:00', '12:00', '13:30', '17:30'),
('3503190424', '星期三', '09:00', '12:00', '13:30', '17:30'),
('3503190424', '星期四', '09:00', '12:00', '13:30', '17:30'),
('3503190424', '星期五', '09:00', '12:00', '13:30', '17:30'),
('3503190424', '星期六', '09:00', '12:00', NULL, NULL),
('3503190424', '星期日', NULL, NULL, NULL, NULL);