"""
Phase 29 Task 3: 視覺解說卡寫入路徑與審核函式單元測試。
"""

import copy
import json
import sqlite3
import pytest

from tests.conftest import apply_visual_migration

# 待實作模組
try:
    from src.visual.writer import upsert_assets, has_visual_assets_table
    from src.visual.review import set_review_status, visible_assets
except ImportError:
    upsert_assets = None
    has_visual_assets_table = None
    set_review_status = None
    visible_assets = None

SAMPLE_IR = {
    "topic_key": "autologous-fat-grafting",
    "title": "自體脂肪移植手術簡介",
    "keywords": ["自體脂肪", "抽脂填補", "脂肪移植"],
    "scenes": [
        {
            "blueprint": "process_diagram",
            "title": "脂肪抽取與純化",
            "caption": "利用專業抽脂技術自腹部或大腿抽取多餘脂肪，經過離心純化技術篩選出健康完整的脂肪細胞以供後續填補。",
            "labels": [
                {"text": "抽取脂肪", "tone": "neutral"},
                {"text": "離心純化", "tone": "optimal"},
            ],
        },
        {
            "blueprint": "contrast",
            "title": "注射填補方式",
            "caption": "醫師採用多層次微量注射技術將脂肪分散注入目標部位，能使組織均勻吸收營養並減少局部硬塊發生的風險。",
            "labels": [
                {"text": "分層注射", "tone": "optimal"},
                {"text": "過量填補", "tone": "warning"},
            ],
        },
        {
            "blueprint": "timeline",
            "title": "術後照護週期",
            "caption": "術後初期需避免劇烈擠壓填補區域，保持規律作息與均衡營養，通常在數週後組織便會逐步達到一定程度的穩定。",
            "labels": [
                {"text": "避免按壓", "tone": "warning"},
                {"text": "穩定成形", "tone": "optimal"},
            ],
        },
    ],
}


def test_import_writer_and_review():
    """驗證 writer 與 review 模組存在且可匯入。"""
    assert upsert_assets is not None, "src/visual/writer.py 必須定義 upsert_assets"
    assert set_review_status is not None, "src/visual/review.py 必須定義 set_review_status"
    assert visible_assets is not None, "src/visual/review.py 必須定義 visible_assets"


def test_fail_closed_on_unmigrated_db(isolated_conn):
    """驗證未遷移資料庫時，upsert_assets 拋出 RuntimeError，visible_assets 回傳空清單。"""
    assert has_visual_assets_table(isolated_conn) is False

    asset = {
        "topic_key": SAMPLE_IR["topic_key"],
        "title": SAMPLE_IR["title"],
        "keywords": SAMPLE_IR["keywords"],
        "ir": SAMPLE_IR,
    }

    with pytest.raises(RuntimeError):
        upsert_assets(isolated_conn, [asset], source_type="manual")

    # visible_assets 在缺表時安全回傳空清單
    assert visible_assets(isolated_conn) == []


def test_upsert_assets_new_pending_and_invisible(isolated_db_path):
    """驗證新增資產預設為 pending，且 visible_assets 看不到。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))

    asset = {
        "topic_key": SAMPLE_IR["topic_key"],
        "title": SAMPLE_IR["title"],
        "keywords": SAMPLE_IR["keywords"],
        "ir": SAMPLE_IR,
    }

    res = upsert_assets(conn, [asset], source_type="manual")
    assert res == {"inserted": 1, "updated": 0, "unchanged": 0}

    # 檢查資料庫列狀態
    cur = conn.cursor()
    cur.execute("SELECT review_status, content_version, reviewed_at FROM visual_assets WHERE topic_key = ?", (SAMPLE_IR["topic_key"],))
    row = cur.fetchone()
    assert row is not None
    assert row[0] == "pending"
    assert row[1] == 1
    assert row[2] is None

    # visible_assets 只能查到 approved 列
    assert visible_assets(conn) == []
    conn.close()


def test_review_approval_makes_asset_visible(isolated_db_path):
    """驗證審核通過後資產出現在 visible_assets 中，且包含 reviewed_at。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))

    asset = {
        "topic_key": SAMPLE_IR["topic_key"],
        "title": SAMPLE_IR["title"],
        "keywords": SAMPLE_IR["keywords"],
        "ir": SAMPLE_IR,
    }
    upsert_assets(conn, [asset], source_type="manual")

    # 審核通過
    rev_res = set_review_status(conn, SAMPLE_IR["topic_key"], "approved")
    assert rev_res["status"] == "ok"
    assert rev_res["review_status"] == "approved"

    # visible_assets 可見
    vis = visible_assets(conn)
    assert len(vis) == 1
    item = vis[0]
    assert item["topic_key"] == SAMPLE_IR["topic_key"]
    assert item["title"] == SAMPLE_IR["title"]
    assert item["keywords"] == SAMPLE_IR["keywords"]
    assert item["ir"]["topic_key"] == SAMPLE_IR["topic_key"]
    assert "clinic_id" not in item

    conn.close()


def test_upsert_content_change_increments_version_and_resets_pending(isolated_db_path):
    """驗證已核准資產於內容實質變更後，content_version 遞增且 review_status 回重設為 pending。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))

    asset = {
        "topic_key": SAMPLE_IR["topic_key"],
        "title": SAMPLE_IR["title"],
        "keywords": SAMPLE_IR["keywords"],
        "ir": SAMPLE_IR,
    }
    upsert_assets(conn, [asset], source_type="manual")
    set_review_status(conn, SAMPLE_IR["topic_key"], "approved")
    assert len(visible_assets(conn)) == 1

    # 內容實質變更（修改其中一個 caption）
    modified_ir = copy.deepcopy(SAMPLE_IR)
    modified_ir["scenes"][0]["caption"] = "利用全新專業抽脂技術自腹部抽取多餘脂肪，經過離心純化技術篩選出健康完整細胞以供後續填補。"
    modified_asset = {
        "topic_key": modified_ir["topic_key"],
        "title": modified_ir["title"],
        "keywords": modified_ir["keywords"],
        "ir": modified_ir,
    }

    res2 = upsert_assets(conn, [modified_asset], source_type="manual")
    assert res2 == {"inserted": 0, "updated": 1, "unchanged": 0}

    # 檢查狀態回退為 pending，content_version 為 2，reviewed_at 清空
    cur = conn.cursor()
    cur.execute("SELECT review_status, content_version, reviewed_at FROM visual_assets WHERE topic_key = ?", (SAMPLE_IR["topic_key"],))
    row = cur.fetchone()
    assert row[0] == "pending"
    assert row[1] == 2
    assert row[2] is None

    # visible_assets 再次變為空
    assert visible_assets(conn) == []

    conn.close()


def test_upsert_unchanged_is_idempotent(isolated_db_path):
    """驗證內容未變時跳過更新（unchanged=1），不遞增版本號也不重置審核狀態。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))

    asset = {
        "topic_key": SAMPLE_IR["topic_key"],
        "title": SAMPLE_IR["title"],
        "keywords": SAMPLE_IR["keywords"],
        "ir": SAMPLE_IR,
    }
    upsert_assets(conn, [asset], source_type="manual")
    set_review_status(conn, SAMPLE_IR["topic_key"], "approved")

    # 相同內容再次 upsert
    res = upsert_assets(conn, [asset], source_type="manual")
    assert res == {"inserted": 0, "updated": 0, "unchanged": 1}

    # 狀態仍為 approved，content_version 仍為 1
    cur = conn.cursor()
    cur.execute("SELECT review_status, content_version FROM visual_assets WHERE topic_key = ?", (SAMPLE_IR["topic_key"],))
    row = cur.fetchone()
    assert row[0] == "approved"
    assert row[1] == 1

    conn.close()


def test_upsert_invalid_ir_rejects_batch(isolated_db_path):
    """驗證整批只要有一筆非法 IR，整批拒絕不寫入資料庫。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))

    valid_asset = {
        "topic_key": SAMPLE_IR["topic_key"],
        "title": SAMPLE_IR["title"],
        "keywords": SAMPLE_IR["keywords"],
        "ir": SAMPLE_IR,
    }

    bad_ir = copy.deepcopy(SAMPLE_IR)
    bad_ir["topic_key"] = "bad-item"
    bad_ir["scenes"][0]["caption"] = "利用抽脂技術抽取多餘脂肪，保證無痕效果極佳，適合各類局部填補需求。"  # 含「保證」
    bad_asset = {
        "topic_key": "bad-item",
        "title": bad_ir["title"],
        "keywords": bad_ir["keywords"],
        "ir": bad_ir,
    }


    with pytest.raises(ValueError) as excinfo:
        upsert_assets(conn, [valid_asset, bad_asset], source_type="manual")

    assert "forbidden_phrase" in str(excinfo.value)

    # 確認資料庫內連第一筆合格的都未寫入
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM visual_assets")
    assert cur.fetchone()[0] == 0

    conn.close()


def test_tamper_detection_in_visible_and_review(isolated_db_path):
    """驗證直接竄改資料庫 ir_json 時，visible_assets 略過不輸出，且審核時拒絕核准。"""
    apply_visual_migration(isolated_db_path)
    conn = sqlite3.connect(str(isolated_db_path))

    asset = {
        "topic_key": SAMPLE_IR["topic_key"],
        "title": SAMPLE_IR["title"],
        "keywords": SAMPLE_IR["keywords"],
        "ir": SAMPLE_IR,
    }
    upsert_assets(conn, [asset], source_type="manual")

    # 惡意直接竄改資料庫中的 ir_json 插入 <script>
    cur = conn.cursor()
    tampered_ir = copy.deepcopy(SAMPLE_IR)
    tampered_ir["scenes"][0]["caption"] = "利用抽脂技術<script>alert('pwned')</script>抽取多餘脂肪以供填補使用。"
    cur.execute("UPDATE visual_assets SET ir_json = ? WHERE topic_key = ?", (json.dumps(tampered_ir), SAMPLE_IR["topic_key"]))
    conn.commit()

    # 1. 嘗試審核通過遭竄改的資料：應回報 text_unsafe 且不改狀態
    res = set_review_status(conn, SAMPLE_IR["topic_key"], "approved")
    assert res["status"] == "validation_failed"
    assert res["code"] == "text_unsafe"

    cur.execute("SELECT review_status FROM visual_assets WHERE topic_key = ?", (SAMPLE_IR["topic_key"],))
    assert cur.fetchone()[0] == "pending"

    # 2. 假設手動在 DB 把 review_status 改成 approved，visible_assets 讀取時應攔截並略過
    cur.execute("UPDATE visual_assets SET review_status = 'approved' WHERE topic_key = ?", (SAMPLE_IR["topic_key"],))
    conn.commit()

    vis = visible_assets(conn)
    assert vis == [], "遭到竄改的非法資產在 visible_assets 中必須被略過！"

    conn.close()
