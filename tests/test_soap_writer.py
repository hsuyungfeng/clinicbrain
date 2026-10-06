"""
Taiwan Clinic Medical PageIndex RAG System - SOAP 寫入與全文檢索測試
涵蓋 Phase 14 Plan 01 (D-01, D-02, D-03):
- upsert_soap_records 基本寫入與欄位驗證
- 冪等 UPSERT 與內容異動比對
- soap_records_fts 之 trigram 中文全文檢索
- 三個觸發器 (INSERT, DELETE, UPDATE) 同步校驗
- 參數缺漏防護
"""

import sqlite3
import pytest
from src.soap.soap_writer import upsert_soap_records


def test_soap_writer_basic_insertion(isolated_conn: sqlite3.Connection):
    """測試正常推播單筆 SOAP 紀錄入庫與欄位讀取完整性。"""
    clinic_id = "3503190424"
    record = {
        "external_id": "REC-2026-001",
        "patient_token": "PTK-TEST001",
        "subjective": "主訴咽喉腫痛，吞嚥困難伴隨微熱發燒。",
        "objective": "理學檢查喉頭黏膜紅腫充血，無化膿性分泌物，體溫37.8度。",
        "assessment": "急性咽喉炎 (J02.9)",
        "plan": "給予抗發炎消腫藥物與止痛退燒藥物，衛教多飲溫水多休息。",
        "raw_text": "S: 主訴咽喉痛 O: 喉頭紅腫 A: 急性咽喉炎 P: 給抗發炎藥物",
        "tags": "耳鼻喉科,急性咽喉炎,感冒",
    }

    inserted, updated, unchanged = upsert_soap_records(isolated_conn, [record], clinic_id)
    assert inserted == 1
    assert updated == 0
    assert unchanged == 0

    cur = isolated_conn.cursor()
    cur.execute(
        "SELECT clinic_id, external_id, patient_token, subjective, objective, assessment, plan, raw_text, tags "
        "FROM soap_records WHERE external_id = ?",
        ("REC-2026-001",),
    )
    row = cur.fetchone()
    assert row is not None
    assert row[0] == clinic_id
    assert row[1] == "REC-2026-001"
    assert row[2] == "PTK-TEST001"
    assert "吞嚥困難" in row[3]
    assert "喉頭黏膜紅腫" in row[4]
    assert "急性咽喉炎" in row[5]
    assert "給予抗發炎" in row[6]
    assert row[7] == record["raw_text"]
    assert row[8] == record["tags"]


def test_soap_writer_idempotent_and_update(isolated_conn: sqlite3.Connection):
    """測試相同內容重推冪等跳過 (unchanged=1)，內容異動正確更新 (updated=1)。"""
    clinic_id = "3503190424"
    record = {
        "external_id": "REC-2026-002",
        "patient_token": "PTK-TEST002",
        "subjective": "頭痛頭暈疲倦。",
        "objective": "血壓 120/80 mmHg。",
        "assessment": "偏頭痛評估",
        "plan": "觀察並追蹤。",
        "raw_text": "頭痛頭暈原始紀錄",
        "tags": "神經內科",
    }

    # 第一次寫入
    ins, upd, unc = upsert_soap_records(isolated_conn, [record], clinic_id)
    assert (ins, upd, unc) == (1, 0, 0)

    cur = isolated_conn.cursor()
    cur.execute("SELECT updated_at FROM soap_records WHERE external_id = ?", ("REC-2026-002",))
    orig_updated_at = cur.fetchone()[0]

    # 第二次推播完全相同內容 -> 冪等不變
    ins, upd, unc = upsert_soap_records(isolated_conn, [record], clinic_id)
    assert (ins, upd, unc) == (0, 0, 1)

    cur.execute("SELECT updated_at FROM soap_records WHERE external_id = ?", ("REC-2026-002",))
    assert cur.fetchone()[0] == orig_updated_at

    # 第三次推播異動 assessment 內容
    updated_rec = dict(record)
    updated_rec["assessment"] = "緊縮型頭痛修正評估"
    ins, upd, unc = upsert_soap_records(isolated_conn, [updated_rec], clinic_id)
    assert (ins, upd, unc) == (0, 1, 0)

    cur.execute("SELECT assessment FROM soap_records WHERE external_id = ?", ("REC-2026-002",))
    assert cur.fetchone()[0] == "緊縮型頭痛修正評估"


def test_soap_writer_parameter_validation(isolated_conn: sqlite3.Connection):
    """測試必要欄位缺漏時拋出明確 ValueError。"""
    # 缺少 clinic_id
    with pytest.raises(ValueError, match="clinic_id 必須為非空字串"):
        upsert_soap_records(isolated_conn, [{"external_id": "1", "patient_token": "2", "raw_text": "3"}], "")

    # 缺少 external_id
    with pytest.raises(ValueError, match="缺少必填欄位 'external_id'"):
        upsert_soap_records(isolated_conn, [{"patient_token": "2", "raw_text": "3"}], "3503190424")

    # 缺少 patient_token
    with pytest.raises(ValueError, match="缺少必填欄位 'patient_token'"):
        upsert_soap_records(isolated_conn, [{"external_id": "1", "raw_text": "3"}], "3503190424")

    # 缺少 raw_text
    with pytest.raises(ValueError, match="缺少必填欄位 'raw_text'"):
        upsert_soap_records(isolated_conn, [{"external_id": "1", "patient_token": "2"}], "3503190424")


def test_soap_fts_trigram_and_triggers_sync(isolated_conn: sqlite3.Connection):
    """測試 FTS5 trigram 中文分詞檢索與觸發器同步（INSERT、UPDATE、DELETE）。"""
    clinic_id = "3503190424"
    record = {
        "external_id": "REC-FTS-001",
        "patient_token": "PTK-FTS-001",
        "subjective": "病患主訴嚴重咳嗽合併黃濃鼻涕與胸口緊繃悶脹。",
        "objective": "雙側肺部聽診有輕微哮鳴音與囉音。",
        "assessment": "急性支氣管炎併細菌感染可能",
        "plan": "開立化痰止咳藥物並衛教蒸氣吸入療法。",
        "raw_text": "咳嗽胸悶哮鳴音原始錄音文字",
        "tags": "胸腔內科,呼吸道感染",
    }

    # 1. 寫入並驗證 INSERT 觸發器同步至 FTS
    upsert_soap_records(isolated_conn, [record], clinic_id)

    cur = isolated_conn.cursor()
    # 測試 S 欄位中文檢索 (3字以上 trigram)
    cur.execute("SELECT rowid FROM soap_records_fts WHERE soap_records_fts MATCH '胸口緊繃'")
    rows = cur.fetchall()
    assert len(rows) == 1

    # 測試 A 欄位中文檢索
    cur.execute("SELECT rowid FROM soap_records_fts WHERE soap_records_fts MATCH '急性支氣管炎'")
    assert len(cur.fetchall()) == 1

    # 測試 tags 檢索
    cur.execute("SELECT rowid FROM soap_records_fts WHERE soap_records_fts MATCH '胸腔內科'")
    assert len(cur.fetchall()) == 1

    # 2. 測試 UPDATE 觸發器同步至 FTS
    rec_update = dict(record)
    rec_update["subjective"] = "病患主訴呼吸困難喘不過氣。"
    upsert_soap_records(isolated_conn, [rec_update], clinic_id)

    # 舊詞應搜不到，新詞應搜到
    cur.execute("SELECT rowid FROM soap_records_fts WHERE soap_records_fts MATCH '胸口緊繃'")
    assert len(cur.fetchall()) == 0
    cur.execute("SELECT rowid FROM soap_records_fts WHERE soap_records_fts MATCH '呼吸困難'")
    assert len(cur.fetchall()) == 1

    # 3. 測試 DELETE 觸發器同步至 FTS
    cur.execute("DELETE FROM soap_records WHERE external_id = 'REC-FTS-001'")
    isolated_conn.commit()

    cur.execute("SELECT rowid FROM soap_records_fts WHERE soap_records_fts MATCH '呼吸困難'")
    assert len(cur.fetchall()) == 0
