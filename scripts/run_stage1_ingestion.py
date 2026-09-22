#!/usr/bin/env python3
"""
Taiwan Clinic Medical PageIndex RAG System - Phase 03 文件擷取管線 Stage 1 執行入口
(scripts/run_stage1_ingestion.py)

執行流程：
1. 確保隔離：複製正式 clinic.db 至獨立測試資料庫（如 clinic_test.db），嚴格不污染正式庫。
2. 執行 extract_docx_text() / extract_xlsx_text() 擷取三份優先檔案文字，存入 scripts/ingestion_output/{name}_extracted.json
3. 若文字包含簡體字元，透過 to_traditional() 進行台灣正體在地化轉換。
4. 呼叫 build_faq_prompt()，透過 local_llm_call() 生成病患常見 Q&A。
5. 呼叫 parse_and_validate_faq() 執行四道安全檢驗（繁中、價格屏蔽、立場中立、禁用保證詞），記錄被剔除項目。
6. 組成標準字典結構，透過 faq_writer.upsert_faqs() 寫入隔離測試庫（category='special', clinic_id='3503190424', source_type='clinic_upload'）。
7. 產出執行摘要 scripts/ingestion_output/summary.json。
"""

import argparse
import json
import logging
from pathlib import Path
import shutil
import sqlite3
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion.convert_chinese import to_traditional
from src.ingestion.extract_text import extract_docx_text, extract_xlsx_text
from src.ingestion.generate_faq import (
    build_faq_prompt,
    parse_and_validate_faq,
    _SIMPLIFIED_CHAR_SAMPLE,
)
from src.pageindex.faq_writer import upsert_faqs
from src.pageindex.llm_client import check_llm_health, local_llm_call, LocalLLMUnavailableError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_stage1_ingestion")

CLINIC_ID = "3503190424"
DEFAULT_SOURCE_TYPE = "clinic_upload"
OUTPUT_DIR = PROJECT_ROOT / "scripts" / "ingestion_output"
ORIGINAL_DATA_DIR = PROJECT_ROOT / "OriginalData" / "緻妍外科診所"

PRIORITY_FILES = [
    {
        "filename": "緻妍自費門診手術內容.docx",
        "type": "docx",
        "topic_key": "outpatient-surgery-procedures",
    },
    {
        "filename": "緻妍可自費門診手術 可配合開立診斷書.docx",
        "type": "docx",
        "topic_key": "insurance-diagnosis-certificates",
    },
    {
        "filename": "客服回覆話術.xlsx",
        "type": "xlsx",
        "topic_key": "customer-service-faq",
    },
]


def setup_isolated_db(target_db_path: Path) -> sqlite3.Connection:
    """初始化隔離測試資料庫，並確保套用最新 schema。"""
    prod_db_path = PROJECT_ROOT / "clinic.db"
    if not prod_db_path.exists():
        raise FileNotFoundError(f"正式資料庫不存在: {prod_db_path}，請先執行 seed 腳本建庫。")

    if not target_db_path.exists():
        logger.info(f"複製正式資料庫至隔離測試複本: {target_db_path}")
        shutil.copy2(prod_db_path, target_db_path)

    # 確保 faq_cache 與其 FTS / triggers 結構存在
    schema_sql_path = PROJECT_ROOT / "src" / "db" / "clinic_schema.sql"
    if schema_sql_path.exists():
        sql_text = schema_sql_path.read_text(encoding="utf-8")
        start_marker = "CREATE TABLE IF NOT EXISTS faq_cache"
        end_marker = "-- ========================================\n-- Sample Data"
        start_pos = sql_text.find(start_marker)
        end_pos = sql_text.find(end_marker)
        if start_pos != -1:
            faq_ddl = sql_text[start_pos:end_pos] if end_pos != -1 else sql_text[start_pos:]
            conn = sqlite3.connect(str(target_db_path))
            conn.executescript(faq_ddl)
            conn.close()

    return sqlite3.connect(str(target_db_path))


def chunk_docx_text(full_text: str, max_chunk_chars: int = 1600) -> list[str]:
    """將 docx 長文字依段落或邏輯區塊切分成適合 LLM 推理的區塊，避免一次性 prompt 過大逾時。"""
    paragraphs = [p.strip() for p in full_text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current_chunk: list[str] = []
    current_len = 0

    for p in paragraphs:
        if current_len + len(p) > max_chunk_chars and current_chunk:
            chunks.append("\n\n".join(current_chunk))
            current_chunk = [p]
            current_len = len(p)
        else:
            current_chunk.append(p)
            current_len += len(p)

    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    return chunks


def format_xlsx_sheet_chunk(sheet_name: str, rows: list[dict], max_rows: int = 40) -> list[str]:
    """將 xlsx 工作表列格式化為 LLM 容易理解的情境對話區塊。"""
    if not rows:
        return []

    chunks: list[str] = []
    for i in range(0, len(rows), max_rows):
        sub_rows = rows[i : i + max_rows]
        lines = [f"工作表名稱：{sheet_name}（第 {i + 1} 至 {i + len(sub_rows)} 筆話術）"]
        for r_idx, row in enumerate(sub_rows, start=i + 1):
            formatted_row = " | ".join(
                f"{k}: {v}" if not k.startswith("col_") else str(v)
                for k, v in row.items()
                if v is not None and str(v).strip()
            )
            if formatted_row:
                lines.append(f"[{r_idx}] {formatted_row}")
        chunks.append("\n".join(lines))
    return chunks


def process_single_file(
    file_cfg: dict,
    conn: sqlite3.Connection,
    dry_run: bool = False,
) -> dict:
    """處理單一檔案的擷取、生成、驗證與入庫。"""
    filename = file_cfg["filename"]
    file_type = file_cfg["type"]
    topic_key = file_cfg["topic_key"]
    file_path = ORIGINAL_DATA_DIR / filename

    if not file_path.exists():
        logger.warning(f"檔案不存在，略過: {file_path}")
        return {"filename": filename, "status": "missing"}

    logger.info(f"===> 開始處理檔案: {filename} ({file_type})")

    # 1. 擷取文字
    extracted_json_path = OUTPUT_DIR / f"{filename}_extracted.json"
    chunks_to_process: list[str] = []

    if file_type == "docx":
        raw_text = extract_docx_text(file_path)
        extracted_data = {
            "filename": filename,
            "char_count": len(raw_text),
            "text": raw_text,
        }
        extracted_json_path.write_text(
            json.dumps(extracted_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"Docx 文字擷取完成，字數: {len(raw_text)}，已存入 {extracted_json_path.name}")
        chunks_to_process = chunk_docx_text(raw_text)

    elif file_type == "xlsx":
        sheets_data = extract_xlsx_text(file_path)
        extracted_data = {
            "filename": filename,
            "sheet_count": len(sheets_data),
            "sheets": {s: len(rows) for s, rows in sheets_data.items()},
            "data": sheets_data,
        }
        extracted_json_path.write_text(
            json.dumps(extracted_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"Xlsx 工作表擷取完成，工作表: {list(sheets_data.keys())}，已存入 {extracted_json_path.name}")
        for s_name, rows in sheets_data.items():
            sheet_chunks = format_xlsx_sheet_chunk(s_name, rows)
            chunks_to_process.extend(sheet_chunks)

    # 2. 簡體中文檢查與轉換
    all_valid_faqs: list[dict[str, Any]] = []
    all_rejected_faqs: list[dict[str, Any]] = []

    logger.info(f"共切分為 {len(chunks_to_process)} 個推理區塊，開始 LLM 問答生成...")

    for chunk_idx, chunk_text in enumerate(chunks_to_process, 1):
        # 檢測簡體字
        has_simplified = any(c in _SIMPLIFIED_CHAR_SAMPLE for c in chunk_text)
        if has_simplified:
            chunk_text = to_traditional(chunk_text)

        prompt = build_faq_prompt(chunk_text, f"{filename} (區塊 {chunk_idx})")

        logger.info(f"正在生成區塊 {chunk_idx}/{len(chunks_to_process)} (提示詞長度: {len(prompt)} 字)...")
        t0 = time.time()
        try:
            raw_llm_reply = local_llm_call(prompt, timeout=120)
            elapsed = time.time() - t0
            logger.info(f"區塊 {chunk_idx} 推理完成，耗時 {elapsed:.2f}s")
        except LocalLLMUnavailableError as e:
            logger.error(f"區塊 {chunk_idx} LLM 呼叫失敗: {e}")
            all_rejected_faqs.append({
                "chunk_index": chunk_idx,
                "error": f"LocalLLMUnavailableError: {e}",
            })
            continue

        # 3. 輸出解析與驗證（先以 opencc s2twp 轉換台灣正體，再經四道防線嚴格檢核）
        clean_llm_reply = to_traditional(raw_llm_reply)
        valid_items, rejected_items = parse_and_validate_faq(clean_llm_reply, return_rejected=True)
        logger.info(f"區塊 {chunk_idx} 驗證結果: 合格 {len(valid_items)} 筆，剔除 {len(rejected_items)} 筆")

        for item in valid_items:
            all_valid_faqs.append({
                "clinic_id": CLINIC_ID,
                "topic_key": topic_key,
                "question": item["question"],
                "answer": item["answer"],
                "category": "special",
            })

        for rej in rejected_items:
            all_rejected_faqs.append({
                "chunk_index": chunk_idx,
                **rej,
            })

    # 4. 儲存 Q&A 中繼記錄
    faqs_json_path = OUTPUT_DIR / f"{filename}_faqs.json"
    faq_record = {
        "filename": filename,
        "topic_key": topic_key,
        "valid_count": len(all_valid_faqs),
        "rejected_count": len(all_rejected_faqs),
        "valid_faqs": all_valid_faqs,
        "rejected_faqs": all_rejected_faqs,
    }
    faqs_json_path.write_text(
        json.dumps(faq_record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"Q&A 結果已寫入: {faqs_json_path.name}")

    # 5. 寫入資料庫
    inserted, updated, unchanged = (0, 0, 0)
    if not dry_run and all_valid_faqs:
        inserted, updated, unchanged = upsert_faqs(
            conn,
            all_valid_faqs,
            source_type=DEFAULT_SOURCE_TYPE,
        )
        logger.info(f"資料庫寫入統計: 新增 {inserted} 筆，更新 {updated} 筆，未變更 {unchanged} 筆")

    return {
        "filename": filename,
        "topic_key": topic_key,
        "chunks": len(chunks_to_process),
        "valid_count": len(all_valid_faqs),
        "rejected_count": len(all_rejected_faqs),
        "db_inserted": inserted,
        "db_updated": updated,
        "db_unchanged": unchanged,
    }


def main():
    parser = argparse.ArgumentParser(description="Phase 03 Stage 1 文件擷取與 FAQ 生成管線")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=PROJECT_ROOT / "clinic_test.db",
        help="隔離測試資料庫路徑（預設 clinic_test.db，絕對不寫入正式 clinic.db）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="僅生成與驗證 Q&A，不寫入資料庫",
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("檢查本地 LLM (llama-server) 狀態...")
    try:
        model_name = check_llm_health(timeout=5)
        logger.info(f"本地 LLM 運作正常，模型: {model_name}")
    except LocalLLMUnavailableError as err:
        logger.error(f"本地 LLM 服務未就緒: {err}")
        sys.exit(1)

    conn = setup_isolated_db(args.db_path)
    logger.info(f"已連接隔離資料庫: {args.db_path}")

    summary_results = []
    total_t0 = time.time()

    for file_cfg in PRIORITY_FILES:
        res = process_single_file(file_cfg, conn, dry_run=args.dry_run)
        summary_results.append(res)

    conn.close()

    summary_path = OUTPUT_DIR / "summary.json"
    summary_data = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_elapsed_seconds": round(time.time() - total_t0, 2),
        "files_processed": summary_results,
    }
    summary_path.write_text(
        json.dumps(summary_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info(f"==================================================")
    logger.info(f"Stage 1 全部處理完成！耗時: {summary_data['total_elapsed_seconds']} 秒")
    logger.info(f"摘要記錄已儲存至: {summary_path}")
    logger.info(f"==================================================")


if __name__ == "__main__":
    main()
