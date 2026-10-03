"""
診所資料優先檢索（Phase 11 CF-01, CF-02, CF-03）量測驗收測試（設計題 G）。

本模組提供獨立可重跑之量測驗收，驗證：
1. 正式庫 40 筆真實診所 FAQ 原文自查短路率由舊流程 24/40 提升至 38/40。
2. 原本被 classify 分流為 general 的 16 筆中，除 id 4 與 id 19 兩筆歧義外，其餘 14 筆全數達成短路。
3. 2 筆未短路者恰為同一問句（「痣、疣或皮膚小贅生物可以如何處理？」）之不同答案，
   觸發 clinic_reason == 'ambiguous' 邊界保護，而非缺陷或門檻放寬。
4. 全程支援 CLINICBRAIN_ACCEPT_DB 指向之獨立複本（以 mode=ro 唯讀開啟），
   並嚴格拒絕直接指向正式 clinic.db（解析後相等即 fail）。
"""

import os
from pathlib import Path
import sqlite3
from typing import Generator
import pytest
from _pytest.outcomes import Failed

from tests.conftest import PROD_DB_PATH
from src.pageindex.faq_review import visible_faq_sql
from src.query.router import (
    handle_query,
    classify,
    extract_search_terms,
    _search_terms_merged,
    _STOPWORD_SPLIT_PATTERN,
)
from src.query.search import search_faq_cache
from src.query.faq_shortcut import (
    select_confident_faq_tiered,
    SHORTCUT_CANDIDATE_LIMIT,
)


def _open_acceptance_connection(accept_env: str) -> sqlite3.Connection:
    """解析並唯讀開啟驗收用資料庫複本；若指向正式庫則引發 pytest.fail。"""
    accept_path = Path(accept_env).resolve()
    if accept_path == PROD_DB_PATH.resolve():
        pytest.fail("驗收測試拒絕直接量測正式庫 clinic.db，請使用複本")
    if not accept_path.exists():
        pytest.fail(f"指定之複本資料庫不存在：{accept_path}")
    return sqlite3.connect(f"file:{accept_path.as_posix()}?mode=ro", uri=True)


@pytest.fixture
def acceptance_conn(isolated_conn) -> Generator[sqlite3.Connection, None, None]:
    """取得驗收用資料庫連線。

    若環境變數 CLINICBRAIN_ACCEPT_DB 有值，以 mode=ro 唯讀開啟該路徑（拒絕正式庫）；
    若未設定則使用 isolated_conn fixture（正式庫複本）。
    """
    accept_env = os.environ.get("CLINICBRAIN_ACCEPT_DB")
    if accept_env:
        connection = _open_acceptance_connection(accept_env)
        try:
            yield connection
        finally:
            connection.close()
    else:
        yield isolated_conn


def test_acceptance_guard_rejects_direct_prod_db():
    """安全防線測試：驗收測試必須拒絕直接量測正式 clinic.db。"""
    with pytest.raises(Failed, match="驗收測試拒絕直接量測正式庫"):
        _open_acceptance_connection(str(PROD_DB_PATH))


def test_clinic_first_acceptance_measurement(acceptance_conn):
    """設計題 G 量測驗收：40 筆診所 FAQ 原文自查，逐筆量測並輸出表格。

    驗證：
    - 總筆數 >= 40（正式庫基線）
    - 短路命中數 >= 38
    - 未短路集合恰為 {4, 19}，且兩筆 clinic_reason 均為 'ambiguous'
    - 原 16 筆 general 路由中 14 筆短路、2 筆歧義
    - 短路回應之 data_level 均為 'clinic'，且 route 欄位維持原本 classify 結果
    - 測試前後複本筆數完全一致（唯讀保護證明）
    """
    conn = acceptance_conn

    # 1. 唯讀證明基線：紀錄測試前筆數
    count_before = conn.execute("SELECT count(*) FROM faq_cache").fetchone()[0]

    # 2. 以原生 SQL 讀取 clinic_id='3503190424' 且通過審核閘門的可見列
    vis_sql = visible_faq_sql(conn)
    cur = conn.cursor()
    rows = cur.execute(
        f"""
        SELECT id, question, answer
        FROM faq_cache
        WHERE clinic_id = '3503190424' AND ({vis_sql})
        ORDER BY id
        """
    ).fetchall()

    if len(rows) < 40:
        pytest.skip(f"正式庫複本診所 FAQ 筆數不足 40 筆（實得 {len(rows)}），跳過量測。")

    cand_limit = max(5, SHORTCUT_CANDIDATE_LIMIT)

    # 3. 逐筆以原文自查呼叫 handle_query
    results = []
    shortcircuited_count = 0
    unshortcircuited_records = []
    general_route_shortcircuited = 0

    print("\n" + "=" * 115)
    print(f"{'ID':<4} | {'舊路由 (classify)':<17} | {'回應 source':<11} | {'data_level':<10} | {'短路決策 reason':<21} | 問句")
    print("-" * 115)

    for row_id, question, answer in rows:
        cls_route = classify(question).route
        resp = handle_query(conn, question, clinic_id="3503190424")

        if resp.source == "cache":
            shortcircuited_count += 1
            reason = "confident"
            clinic_reason = "confident"
            if cls_route == "general":
                general_route_shortcircuited += 1
        else:
            # 針對未短路者，以 select_confident_faq_tiered 重算精確原因
            search_terms = extract_search_terms(question)
            raw_clinic = _search_terms_merged(
                search_faq_cache,
                conn,
                search_terms,
                cand_limit,
                clinic_id="3503190424",
                category="special",
            )
            clinic_candidates = [h for h in raw_clinic if h.fields.get("clinic_id") == "3503190424"]

            raw_gen = _search_terms_merged(
                search_faq_cache,
                conn,
                search_terms,
                cand_limit,
                clinic_id=None,
                category="general",
            )
            general_candidates = [h for h in raw_gen if h.fields.get("clinic_id") is None]

            decision = select_confident_faq_tiered(
                query=question,
                clinic_hits=clinic_candidates,
                general_hits=general_candidates,
                clinic_id="3503190424",
                stopword_pattern=_STOPWORD_SPLIT_PATTERN,
            )
            reason = decision.reason
            clinic_reason = decision.clinic_reason
            unshortcircuited_records.append((row_id, question, cls_route, reason, clinic_reason, resp))

        results.append((row_id, cls_route, resp.source, str(resp.data_level), reason, question))
        print(f"{row_id:<4} | {cls_route:<17} | {resp.source:<11} | {str(resp.data_level):<10} | {reason:<21} | {question}")

    # 4. 舊行為基準計算
    general_route_total = sum(1 for _, q, _ in rows if classify(q).route == "general")
    legacy_ceiling = len(rows) - general_route_total

    print("-" * 115)
    print(f"總筆數 (Total Visible Clinic FAQs): {len(rows)}")
    print(f"舊式被 classify 分流為 general 筆數: {general_route_total}（舊流程皆無法短路）")
    print(f"舊式可短路上限: {legacy_ceiling} / {len(rows)} (60.00%)")
    print(f"Phase 11 新流程實測短路數: {shortcircuited_count} / {len(rows)} ({shortcircuited_count/len(rows):.2%})")
    print(f"原 16 筆 general 路由對照: {general_route_shortcircuited} 筆短路、{len(unshortcircuited_records)} 筆歧義")
    print("=" * 115 + "\n")

    # 5. 斷言檢核
    assert len(rows) >= 40, f"總筆數應 >= 40，實得 {len(rows)}"
    assert shortcircuited_count >= 38, f"短路數應 >= 38，實得 {shortcircuited_count}"

    # 未短路集合必須恰為 {4, 19}
    unshortcircuited_ids = {r[0] for r in unshortcircuited_records}
    assert unshortcircuited_ids == {4, 19}, (
        f"未短路 id 集合預期恰為 {{4, 19}}，實得 {unshortcircuited_ids}"
    )

    # 兩筆未短路者之問句與 clinic_reason 檢核
    for r in unshortcircuited_records:
        r_id, r_q, r_route, r_reason, r_clinic_reason, r_resp = r
        assert r_q == "痣、疣或皮膚小贅生物可以如何處理？", (
            f"未短路問句不符預期：id={r_id}, q='{r_q}'"
        )
        assert r_clinic_reason == "ambiguous", (
            f"未短路 reason 預期 'ambiguous'，實得 '{r_clinic_reason}'（完整 reason='{r_reason}'）"
        )

    # 16 筆 general 分流對照：14 筆短路
    assert general_route_shortcircuited == 14, (
        f"原 general 分流短路數預期 14，實得 {general_route_shortcircuited}"
    )

    # 短路筆之 data_level 與 route 檢核
    for r_id, q, a in rows:
        if r_id not in unshortcircuited_ids:
            resp = handle_query(conn, q, clinic_id="3503190424")
            assert resp.data_level == "clinic", f"id={r_id} 短路但 data_level 不是 'clinic': {resp.data_level}"
            assert resp.route == classify(q).route, f"id={r_id} route 欄位應與 classify 一致"

    # 唯讀證明：資料庫筆數未改變
    count_after = conn.execute("SELECT count(*) FROM faq_cache").fetchone()[0]
    assert count_before == count_after, (
        f"唯讀違規：測試前後 faq_cache 筆數改變（前={count_before}, 後={count_after}）"
    )
