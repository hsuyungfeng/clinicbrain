#!/usr/bin/env python3
"""
Taiwan Clinic Medical PageIndex RAG System - 診所層級通用備註管理 (clinic_custom_notes)
Phase 01 Task 7: Integrate clinic database with RAG query

架構核心定位（見 TASK-007-PLAN.md 與 AGENTS.md）：
- clinic_custom_notes：診所層級、橫跨所有療程適用的通則性政策與須知（如「全麻或舒眠療程術前一律禁食8小時」）。
  以 clinic_id + section 為唯一主體，同一 section 只保留最新一筆（增量 UPSERT，不產生重複列）。
- page_index_trees.*_physician_notes：綁定於單一療程 (doc_id) 的專屬醫囑（如肉毒桿菌注射後4小時不可平躺）。
  兩者截然不同，不可混為一談。

CONSTRAINT 遵循：
- 全繁體中文
- 絕對禁止出現具體價格或促銷字樣
- section 嚴格限制在 pre_op, procedure, post_op_short, maintenance 四者之一
"""

import sqlite3
import sys
from pathlib import Path

# 支援直接執行與模組匯入
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "clinic.db"

VALID_SECTIONS = ("pre_op", "procedure", "post_op_short", "maintenance")

# 診所預設政策範例（符合真實醫美門診情境，跨所有療程通用，絕無價格洩漏）
DEFAULT_SAMPLE_NOTES = {
    "pre_op": (
        "【本院術前通用提醒】凡接受各項光電雷射、微整注射或手術療程，請確實詳閱術前衛教單；"
        "施作前一週請停止使用含有酸類、A酸、去角質等刺激性保養品，並暫停服用阿斯匹靈、銀杏等抗凝血藥物或保健品；"
        "若有特殊體質（如蟹足腫、凝血功能異常）、懷孕、哺乳或近期罹患感染性疾病，請務必於就診報到時主動告知醫師與醫護團隊。"
    ),
    "post_op_short": (
        "【本院術後通則照護】治療後一週內請避免前往三溫暖、溫泉、烤箱、游泳池等高溫濕熱場所；"
        "日常清潔請使用溫和無皂鹼產品，並確實做好保濕與物理性防曬（建議SPF50+/PA+++以上）；"
        "若術後部位出現劇烈抽痛、視力模糊、異常大面積瘀青或皮膚缺血發白等警訊，請立即撥打本院24小時急診諮詢專線返院評估。"
    ),
    "maintenance": (
        "【長期療效維持建議】各項醫療美容與皮膚治療之維持期因個人體質、年齡代謝、生活作息及防曬習慣而異；"
        "建議配合主治醫師排定之追蹤回診計畫定期評估膚況，維持健康肌膚屏障與穩定治療成果。"
    ),
}


def upsert_clinic_note(conn: sqlite3.Connection, clinic_id: str, section: str, note: str) -> None:
    """新增或更新指定診所的通用段落備註。
    
    保證「同 clinic_id + section 視為唯一，只保留最新一筆」，使用 UPDATE 避免累積重複列。
    更新時明確將 updated_at 設為 CURRENT_TIMESTAMP。
    """
    if section not in VALID_SECTIONS:
        raise ValueError(f"無效的 section: '{section}'。合法值必須為 {VALID_SECTIONS} 之一。")
    
    clean_note = note.strip()
    if not clean_note:
        raise ValueError("note 內容不可為空。")

    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM clinic_custom_notes WHERE clinic_id = ? AND section = ?",
        (clinic_id, section),
    )
    row = cursor.fetchone()

    if row:
        cursor.execute(
            """
            UPDATE clinic_custom_notes
            SET note = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (clean_note, row[0]),
        )
    else:
        cursor.execute(
            """
            INSERT INTO clinic_custom_notes (clinic_id, section, note, created_at, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (clinic_id, section, clean_note),
        )
    conn.commit()


def get_clinic_custom_notes(conn: sqlite3.Connection, clinic_id: str = "zhiyan-clinic") -> dict[str, str]:
    """回傳指定診所的所有通用備註字典 {section: note}。"""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT section, note
        FROM clinic_custom_notes
        WHERE clinic_id = ?
        ORDER BY id ASC
        """,
        (clinic_id,),
    )
    return {row[0]: row[1] for row in cursor.fetchall()}


def seed_sample_notes(conn: sqlite3.Connection, clinic_id: str = "zhiyan-clinic") -> int:
    """寫入診所通用備註的預設範例資料。"""
    count = 0
    for section, note in DEFAULT_SAMPLE_NOTES.items():
        upsert_clinic_note(conn, clinic_id, section, note)
        count += 1
    return count


def main() -> int:
    db_path = sys.argv[1] if len(sys.argv) > 1 else str(DEFAULT_DB_PATH)
    print(f"連接資料庫：{db_path}")
    conn = sqlite3.connect(db_path)
    count = seed_sample_notes(conn)
    print(f"成功寫入/更新 {count} 筆診所通用備註（zhiyan-clinic）")
    notes = get_clinic_custom_notes(conn)
    for sec, note in notes.items():
        print(f"\n[{sec}]:\n{note}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
