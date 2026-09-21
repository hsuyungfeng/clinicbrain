"""
Taiwan Clinic Medical PageIndex RAG System - OTC 藥品本地化與別名測試
涵蓋 TASK-008 測試範疇：
- 類別 4：OTC 同義詞機制（ASPIRIN / ACETYLSALICYLIC ACID、MAGNESIUM HYDROXIDE / MAGNESIUM OXIDE）
  與 otc_mappings.json 全量規則合規性檢查（無價格、無簡體字）
"""

import json
import re
from pathlib import Path
import pytest
from src.query.search import search_drugs, format_drug_display_name
from src.query.router import _PRICE_PATTERN
from src.pageindex.prompt_template import _SIMPLIFIED_CHAR_SAMPLE

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAPPINGS_FILE = PROJECT_ROOT / "src" / "db" / "otc_mappings.json"


def test_otc_mappings_file_exists_and_valid():
    """驗證 otc_mappings.json 存在且為合法 JSON，至少包含 60 筆以上對照規則。"""
    assert MAPPINGS_FILE.exists(), f"找不到對照表：{MAPPINGS_FILE}"
    with open(MAPPINGS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "mappings" in data
    assert len(data["mappings"]) >= 60


def test_otc_mappings_all_rules_compliance():
    """合規性掃描：逐筆檢查 otc_mappings.json 裡所有 68 筆對照規則。
    1. otc_name_chinese 絕對不得含有任何價格資訊
    2. otc_name_chinese 絕對不得含有簡體字（繁體中文專用 CONSTRAINT）
    3. pattern 與 category 必須為非空字串
    """
    with open(MAPPINGS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    for item in data["mappings"]:
        pattern = item.get("pattern")
        otc = item.get("otc_name_chinese", "")
        category = item.get("category", "")

        assert pattern, "pattern 不可為空"
        assert category, f"pattern {pattern} 缺少 category"
        assert otc, f"pattern {pattern} 缺少 otc_name_chinese"

        # 價格檢查
        price_matches = _PRICE_PATTERN.findall(otc)
        assert not price_matches, f"合規違規：{pattern} 的 otc_name_chinese 含有價格 {price_matches}"

        # 簡體字檢查
        simplified_hits = [c for c in _SIMPLIFIED_CHAR_SAMPLE if c in otc]
        assert not simplified_hits, f"合規違規：{pattern} 的 otc_name_chinese 含有疑似簡體字 {simplified_hits}"


def test_alias_aspirin_acetylsalicylic_acid(conn):
    """驗證 ASPIRIN 同義詞 ACETYLSALICYLIC ACID 機制：
    資料庫中存在僅以 ACETYLSALICYLIC ACID 登記成分而未寫 ASPIRIN 的藥品（如 BC25326100），
    透過別名機制必須能被補上正確的 OTC 俗名，且查詢時能被順利檢索。
    """
    # 1. 驗證資料庫底層確實有此成分藥品被命中並賦予正確 OTC 俗名
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT code, chinese_name, english_name, ingredient, otc_name_chinese
        FROM drugs
        WHERE ingredient LIKE '%ACETYLSALICYLIC ACID%'
          AND ingredient NOT LIKE '%ASPIRIN%'
        """
    )
    rows = cursor.fetchall()
    assert len(rows) >= 1, "預期至少有一筆僅標記 ACETYLSALICYLIC ACID 的品項"

    expected_otc = "阿斯匹靈（解熱鎮痛/抗血栓）"
    for row in rows:
        assert row[4] == expected_otc, f"藥品 {row[0]} 未正確套用別名 OTC 本地化名稱"

    # 2. 透過 search_drugs 查詢別名
    hits = search_drugs(conn, "ACETYLSALICYLIC", limit=5)
    assert len(hits) > 0, "查詢別名 ACETYLSALICYLIC 應有命中結果"
    found_expected = any(h.fields.get("otc_name_chinese") == expected_otc for h in hits)
    assert found_expected, f"查詢 ACETYLSALICYLIC 未找到具有 '{expected_otc}' 的藥品"

    # 3. 驗證 format_drug_display_name 正確帶出【俗名】
    for hit in hits:
        if hit.fields.get("otc_name_chinese") == expected_otc:
            assert f"【{expected_otc}】" in hit.fields["display_name"]


def test_alias_magnesium_hydroxide_oxide(conn):
    """驗證 MAGNESIUM HYDROXIDE 同義詞 MAGNESIUM OXIDE 機制：
    資料庫中存在以 MAGNESIUM OXIDE 登記成分的藥品（共12筆）：
    1. 純氧化鎂單方藥品（6筆，無氫氧化鋁複合）被賦予「常見胃藥/制酸與軟便劑（氫氧化鎂/氧化鎂）」。
    2. 含有氫氧化鋁的複方藥品（6筆）亦皆獲得胃藥 OTC 本地化名稱。
    3. 透過 search_drugs 查詢別名 MAGNESIUM OXIDE 時，能正確檢索出氧化鎂藥品並帶出俗名。
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT code, chinese_name, english_name, ingredient, otc_name_chinese
        FROM drugs
        WHERE ingredient LIKE '%MAGNESIUM OXIDE%'
          AND ingredient NOT LIKE '%MAGNESIUM HYDROXIDE%'
        """
    )
    rows = cursor.fetchall()
    assert len(rows) == 12, f"預期有 12 筆氧化鎂品項，實際找到 {len(rows)} 筆"

    expected_otc = "常見胃藥/制酸與軟便劑（氫氧化鎂/氧化鎂）"
    # 所有 12 筆均應具有 OTC 俗名
    for row in rows:
        assert row[4] is not None, f"藥品 {row[0]} 缺少 OTC 本地化名稱"

    # 純氧化鎂單方藥品（未含氫氧化鋁複方）應完全吻合 expected_otc
    pure_mg_rows = [r for r in rows if "ALUMINUM HYDROXIDE" not in (r[3] or "")]
    assert len(pure_mg_rows) >= 5
    for row in pure_mg_rows:
        assert row[4] == expected_otc, f"單方氧化鎂藥品 {row[0]} 未正確套用俗名"

    # 透過 search_drugs 查詢
    hits = search_drugs(conn, "MAGNESIUM OXIDE", limit=5)
    assert len(hits) > 0, "查詢 MAGNESIUM OXIDE 應有命中結果"
    assert any(h.fields.get("otc_name_chinese") == expected_otc for h in hits)
    # 驗證 display_name 格式化包含【俗名】
    for hit in hits:
        if hit.fields.get("otc_name_chinese") == expected_otc:
            assert f"【{expected_otc}】" in hit.fields["display_name"]



def test_format_drug_display_name_formatting():
    """測試 format_drug_display_name 各種欄位組合的格式化表現。"""
    # 1. 中文名 + OTC
    f1 = {"chinese_name": "普拿疼膜衣錠", "english_name": "PANADOL", "otc_name_chinese": "乙醯胺酚"}
    assert format_drug_display_name(f1) == "普拿疼膜衣錠【乙醯胺酚】"

    # 2. 僅英文名 + OTC
    f2 = {"chinese_name": None, "english_name": "ASPIRIN TABLETS", "otc_name_chinese": "阿斯匹靈"}
    assert format_drug_display_name(f2) == "ASPIRIN TABLETS【阿斯匹靈】"

    # 3. 無 OTC 但有中文名
    f3 = {"chinese_name": "抗生素軟膏", "english_name": "ANTIBIOTIC", "otc_name_chinese": None}
    assert format_drug_display_name(f3) == "抗生素軟膏"

    # 4. 無 OTC、無中文名、僅英文名
    f4 = {"chinese_name": "", "english_name": "AMYCIN", "otc_name_chinese": None}
    assert format_drug_display_name(f4) == "AMYCIN"

    # 5. 全空兜底
    f5 = {"chinese_name": "", "english_name": "", "otc_name_chinese": None}
    assert format_drug_display_name(f5) == "未具名藥品"


def test_database_drugs_otc_coverage_and_traditional_chinese(conn):
    """驗證正式資料庫複本中 drugs 表的 OTC 覆蓋率與繁體中文合規。
    1. 有 otc_name_chinese 的筆數應維持在 2400 筆以上（TASK-006 擴充後成果）。
    2. 全表所有 otc_name_chinese 欄位均不得含有簡體字。
    """
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM drugs WHERE otc_name_chinese IS NOT NULL")
    count = cursor.fetchone()[0]
    assert count >= 2400, f"OTC 覆蓋筆數過低：{count} < 2400"

    # 簡體字掃描
    cursor.execute("SELECT DISTINCT otc_name_chinese FROM drugs WHERE otc_name_chinese IS NOT NULL")
    distinct_names = [row[0] for row in cursor.fetchall()]
    for name in distinct_names:
        simplified = [c for c in _SIMPLIFIED_CHAR_SAMPLE if c in name]
        assert not simplified, f"資料庫中發現簡體字：{name} (字元: {simplified})"
