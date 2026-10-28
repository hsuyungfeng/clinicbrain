"""病患諮詢回應附上互動追問膠囊（followup_chips）：只在有回答時附上，紅旗不附。"""

import sqlite3
from pathlib import Path

from src.general import answer_compose as ac
from src.general import patient_consult as pc
from src.pageindex.faq_writer import upsert_faqs

WARNING = "若出現持續性疼痛或異常腫脹，請立即回診尋求醫師評估。"


def test_red_flag_result_has_no_chips(isolated_db_path: Path):
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        res = pc.patient_consult(conn, "我突然胸痛而且呼吸困難")
        assert res.status == "red_flag"
        assert res.followup_chips == []
    finally:
        conn.close()


def test_answered_result_carries_two_compliant_chips(isolated_db_path: Path):
    q = "請問自體脂肪移植術後如何照護？"
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        upsert_faqs(
            conn,
            [{
                "clinic_id": None,
                "topic_key": "chip-fat-faq",
                "category": "general",
                "question": q,
                "answer": f"自體脂肪移植術後請保持正常作息並避免按壓。{WARNING}",
            }],
            source_type="manual",
        )
        res = pc.patient_consult(conn, q)
        assert res.status == "answered"
        assert len(res.followup_chips) == 2
        allowed = set(ac.GENERAL_FOLLOWUPS.values()) | set(ac.DEFAULT_FOLLOWUPS.values())
        assert all(c in allowed for c in res.followup_chips)
    finally:
        conn.close()
