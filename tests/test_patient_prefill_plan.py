"""Phase 28 Plan 05: patient_prefill_plan 單元測試（假時鐘）。

涵蓋：
Task 1:
- Test 1: INTENT_TEMPLATES 恰五個意圖、含 {title}、恰一個「？」、不含數字、通過題目四層合規檢核
- Test 2: 列舉已核准推理樹，PrefillTopic 各欄位齊全、中文標題優先、排除 pending 樹
- Test 2b: 標題優先順序 (樹 title -> 種子 title 去掉常見問題 -> 無中文標題略過)
- Test 3: pending/rejected FAQ 不進入 reference
- Test 4: 種子 general 無樹主題以已核准 FAQ 列入，且不與樹主題重複
- Test 5: compute_ref_signature 確定性短雜湊（12字元）、內容變動則變、順序無關
- Test 6: 參考文字價格屏蔽檢核

Task 2:
- Test 1: 全新主題（無預生成列）狀態為 missing，五個意圖全數待生成
- Test 2: 新鮮主題（10 小時、簽章相同）不排入
- Test 3: 過期主題判定（21.5 小時不排入，22.5 小時排入，reason=time_stale）
- Test 4: 版本簽章改變（signature_changed 優先於 time_stale）
- Test 5: 缺題主題（missing_intents，僅排入缺少的意圖）
- Test 6: 排序與上限截斷（max_topics=3，回報 backlog）
- Test 7: rejected 受保護列在簽章未變時不排入，簽章改變才排入
- Test 8: approved 受保護列在簽章未變時不排入且不佔名額（protected_skipped 計數），簽章改變才排入
- Test 8b: manual_edit 受保護列在簽章未變時不排入，簽章改變才排入
- Test 9: metadata 損毀容錯處理
- Test 10: plan_prefill 全程不寫入資料庫
"""

from datetime import datetime, timezone, timedelta
import json
import pytest

from src.batch.patient_prefill_plan import (
    FRESHNESS_HOURS,
    INTENT_TEMPLATES,
    PREFILL_TOPIC_PREFIX,
    REFRESH_GRACE_HOURS,
    compute_ref_signature,
    enumerate_prefill_topics,
    plan_prefill,
)
from src.pageindex.db_writer import upsert_trees
from src.pageindex.faq_writer import upsert_faqs

CLINIC = "3503190424"
NOW_FIXED = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)


# ==============================================================================
# Task 1 測試：模板、主題列舉、簽章與可見性
# ==============================================================================

def test_1_intent_templates_structure_and_compliance():
    """Test 1: INTENT_TEMPLATES 恰五個意圖，含 {title}、恰一個「？」、不含數字，通過四層檢驗。"""
    from src.ingestion.convert_chinese import to_traditional
    from src.ingestion.generate_faq import validate_single_faq

    assert len(INTENT_TEMPLATES) == 5
    assert set(INTENT_TEMPLATES.keys()) == {"what", "suitable", "risk", "recovery", "when_to_see_doctor"}

    for intent, tpl in INTENT_TEMPLATES.items():
        assert "{title}" in tpl
        assert tpl.count("？") == 1
        assert not any(c.isdigit() for c in tpl)

        for sample_title in ("玻尿酸注射", "感冒居家護理", "皮秒雷射療程"):
            q = tpl.format(title=sample_title)
            assert to_traditional(q) == q
            ok, reason = validate_single_faq({"question": q, "answer": "請致電診所確認"})
            assert ok, f"模板合規檢驗失敗: {q}, reason={reason}"


def test_2_enumerate_prefill_topics_approved_tree_only(isolated_conn, tmp_path):
    """Test 2: 只列舉已核准推理樹，排除 pending 樹；PrefillTopic 包含完整欄位與中文標題。"""
    doc_approved = "p28-filler-ok"
    doc_pending = "p28-laser-pend"

    trees = [
        {
            "doc_id": doc_approved,
            "clinic_id": CLINIC,
            "category": "special",
            "title": "玻尿酸填充塑形",
            "summary_text": "玻尿酸填充主要用於修飾輪廓與撫平皺紋，費用約 15000 元請致電診所確認。",
            "pre_op": "術前需評估過敏史並告知凝血藥物使用狀況。",
            "pre_op_physician_notes": "",
            "procedure": "採局部精準微量注射，分層塑形。",
            "procedure_physician_notes": "",
            "post_op_short": "術後一週內避免高溫蒸氣，輕微腫脹為正常現象。",
            "post_op_short_physician_notes": "",
            "maintenance": "日常加強保濕，依代謝狀況定期評估補打。",
            "maintenance_physician_notes": "",
            "version": 1,
            "status": "approved",
        },
        {
            "doc_id": doc_pending,
            "clinic_id": CLINIC,
            "category": "special",
            "title": "雷射磨皮療程",
            "summary_text": "待審雷射推理樹內容絕對不可列入預生成。",
            "pre_op": "術前待審。",
            "pre_op_physician_notes": "",
            "procedure": "處置待審。",
            "procedure_physician_notes": "",
            "post_op_short": "術後待審。",
            "post_op_short_physician_notes": "",
            "maintenance": "維持待審。",
            "maintenance_physician_notes": "",
            "version": 1,
            "status": "pending",
        },
    ]
    upsert_trees(isolated_conn, trees, source_type="llm_generated")
    # 將第一棵手動核准
    isolated_conn.execute(
        "UPDATE page_index_trees SET review_status='approved' WHERE doc_id=?", (doc_approved,)
    )
    isolated_conn.commit()

    # 建立空種子清單
    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps({"topics": [], "tree_procedure_names": {}}), encoding="utf-8")

    topics = enumerate_prefill_topics(isolated_conn, seed_file)
    topic_doc_ids = [t.tree_doc_id for t in topics]

    assert doc_approved in topic_doc_ids
    assert doc_pending not in topic_doc_ids

    match = [t for t in topics if t.tree_doc_id == doc_approved][0]
    assert match.topic_key == f"{PREFILL_TOPIC_PREFIX}{doc_approved}"
    assert match.title == "玻尿酸填充塑形"
    assert match.clinic_id == CLINIC
    assert match.category == "special"
    assert "15000" not in match.reference  # 價格遮蔽
    assert len(match.ref_signature) == 12


def test_2b_title_priority_order(isolated_conn, tmp_path):
    """Test 2b: 標題優先順序：樹 title -> 種子 title 去掉常見問題 -> 無中文標題略過。"""
    # 樹 1: title 有值
    t1 = {
        "doc_id": "p28-tree-with-title", "clinic_id": CLINIC, "category": "special",
        "title": "自體脂肪隆乳", "summary_text": "摘要", "pre_op": "術前", "pre_op_physician_notes": "",
        "procedure": "步驟", "procedure_physician_notes": "", "post_op_short": "術後",
        "post_op_short_physician_notes": "", "maintenance": "維持", "maintenance_physician_notes": "",
        "version": 1, "status": "approved",
    }
    # 樹 2: title 為空，但種子 tree_doc_id 符合且 title 為「抽脂手術常見問題」
    t2 = {
        "doc_id": "p28-tree-seed-title", "clinic_id": CLINIC, "category": "special",
        "title": "", "summary_text": "摘要", "pre_op": "術前", "pre_op_physician_notes": "",
        "procedure": "步驟", "procedure_physician_notes": "", "post_op_short": "術後",
        "post_op_short_physician_notes": "", "maintenance": "維持", "maintenance_physician_notes": "",
        "version": 1, "status": "approved",
    }
    # 樹 3: 只有英文 slug、title 為空、種子也沒有
    t3 = {
        "doc_id": "p28-tree-no-title-slug", "clinic_id": CLINIC, "category": "special",
        "title": "", "summary_text": "摘要", "pre_op": "術前", "pre_op_physician_notes": "",
        "procedure": "步驟", "procedure_physician_notes": "", "post_op_short": "術後",
        "post_op_short_physician_notes": "", "maintenance": "維持", "maintenance_physician_notes": "",
        "version": 1, "status": "approved",
    }
    upsert_trees(isolated_conn, [t1, t2, t3], source_type="manual")

    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps({
        "topics": [{
            "topic_key": "liposuction",
            "title": "抽脂手術常見問題",
            "category": "special",
            "clinic_id": CLINIC,
            "keywords": ["抽脂"],
            "always": True,
            "tree_doc_id": "p28-tree-seed-title",
            "questions": ["抽脂是什麼？"],
        }],
        "tree_procedure_names": {},
    }), encoding="utf-8")

    topics = enumerate_prefill_topics(isolated_conn, seed_file)
    topic_map = {t.tree_doc_id: t for t in topics}

    assert "p28-tree-with-title" in topic_map
    assert topic_map["p28-tree-with-title"].title == "自體脂肪隆乳"

    assert "p28-tree-seed-title" in topic_map
    assert topic_map["p28-tree-seed-title"].title == "抽脂手術"  # 去除「常見問題」

    assert "p28-tree-no-title-slug" not in topic_map  # 無可讀中文標題略過


def test_3_pending_or_rejected_faq_excluded_from_reference(isolated_conn, tmp_path):
    """Test 3: pending 或 rejected 的 FAQ 內容不會進入任何主題的 reference。"""
    upsert_faqs(
        isolated_conn,
        [
            {
                "clinic_id": None, "topic_key": "p28-cold", "category": "general",
                "question": "感冒該如何多喝水？",
                "answer": "已核准內容：多喝溫開水注意休息保暖。",
            },
            {
                "clinic_id": None, "topic_key": "p28-cold", "category": "general",
                "question": "待審感冒問答？",
                "answer": "機密待審感冒答案絕對不得外洩。",
            },
        ],
        source_type="clinic_upload",
    )
    # 把第二筆設為 pending
    isolated_conn.execute("UPDATE faq_cache SET review_status='pending' WHERE question='待審感冒問答？'")
    isolated_conn.commit()

    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps({
        "topics": [{
            "topic_key": "p28-cold", "title": "感冒照護常見問題", "category": "general",
            "clinic_id": None, "keywords": ["感冒"], "always": True, "tree_doc_id": None,
            "questions": ["感冒是什麼？"],
        }],
        "tree_procedure_names": {},
    }), encoding="utf-8")

    topics = enumerate_prefill_topics(isolated_conn, seed_file)
    cold_topic = [t for t in topics if t.topic_key == f"{PREFILL_TOPIC_PREFIX}p28-cold"][0]

    assert "多喝溫開水" in cold_topic.reference
    assert "機密待審感冒答案" not in cold_topic.reference


def test_5_compute_ref_signature_deterministic():
    """Test 5: compute_ref_signature 輸出 12 字元十六進位，內容變動改變，順序無關。"""
    part1 = ("t1", 1, "文字內容甲")
    part2 = ("t2", 2, "文字內容乙")

    sig1 = compute_ref_signature([part1, part2])
    sig2 = compute_ref_signature([part2, part1])
    assert len(sig1) == 12
    assert sig1 == sig2  # 順序無關

    sig3 = compute_ref_signature([("t1", 2, "文字內容甲"), part2])  # 版號變動
    assert sig1 != sig3

    sig4 = compute_ref_signature([part1, ("t2", 2, "文字內容丙")])  # 內容變動
    assert sig1 != sig4


# ==============================================================================
# Task 2 測試：新鮮度判定、排隊、假時鐘與受保護列
# ==============================================================================

def _make_dummy_topic(key="test-topic", sig="sig123456789") -> "PrefillTopic":
    from src.batch.patient_prefill_plan import PrefillTopic
    return PrefillTopic(
        topic_key=f"{PREFILL_TOPIC_PREFIX}{key}",
        title="測試療程項目",
        category="special",
        clinic_id=CLINIC,
        tree_doc_id=key,
        reference="參考內容",
        ref_signature=sig,
        source_kind="tree",
    )


def test_task2_1_missing_topic_all_intents_queued(isolated_conn):
    """Test 1（全新）: 主題尚無任何預生成列，狀態為 missing_intents，五個意圖全數待生成。"""
    topic = _make_dummy_topic("new-topic")
    plan = plan_prefill(isolated_conn, [topic], now=NOW_FIXED, max_topics=5)

    assert len(plan.topics) == 1
    t_plan = plan.topics[0]
    assert t_plan.reason == "missing_intents"
    assert len(t_plan.items) == 5
    assert len(t_plan.missing_intents) == 5


def test_task2_2_fresh_topic_not_queued(isolated_conn):
    """Test 2（新鮮）: 五列皆存在、generated_at 距假時鐘 10 小時、簽章相同 -> 不排入。"""
    topic = _make_dummy_topic("fresh-topic", sig="freshsig1234")
    gen_time = (NOW_FIXED - timedelta(hours=10)).isoformat()

    faqs = []
    for intent in INTENT_TEMPLATES.keys():
        faqs.append({
            "clinic_id": CLINIC,
            "topic_key": f"{topic.topic_key}-{intent}",
            "category": "special",
            "question": f"測試{intent}問題？",
            "answer": "答案說明。",
            "metadata": json.dumps({
                "origin": "patient_prefill",
                "prefill_topic_key": topic.topic_key,
                "intent": intent,
                "generated_at": gen_time,
                "ref_signature": "freshsig1234",
            }),
        })
    upsert_faqs(isolated_conn, faqs, source_type="llm_generated")

    plan = plan_prefill(isolated_conn, [topic], now=NOW_FIXED, max_topics=5)
    assert len(plan.topics) == 0
    assert plan.stale_total == 0


def test_task2_3_time_stale_boundary_21_5_vs_22_5_hours(isolated_conn):
    """Test 3（過期邊界）: 21.5 小時不排入，22.5 小時（>=24-2 寬限）排入，reason=time_stale。"""
    # 1. 21.5 小時前：不排入
    time_21_5 = (NOW_FIXED - timedelta(hours=21, minutes=30)).isoformat()
    topic_not_stale = _make_dummy_topic("stale-boundary-1", sig="samesig1111")
    faqs_not_stale = [
        {
            "clinic_id": CLINIC, "topic_key": f"{topic_not_stale.topic_key}-{it}",
            "category": "special", "question": f"問{it}？", "answer": "答。",
            "metadata": json.dumps({
                "origin": "patient_prefill", "prefill_topic_key": topic_not_stale.topic_key,
                "intent": it, "generated_at": time_21_5, "ref_signature": "samesig1111",
            }),
        }
        for it in INTENT_TEMPLATES.keys()
    ]
    upsert_faqs(isolated_conn, faqs_not_stale, source_type="llm_generated")

    plan1 = plan_prefill(isolated_conn, [topic_not_stale], now=NOW_FIXED, max_topics=5)
    assert len(plan1.topics) == 0

    # 2. 22.5 小時前：排入
    time_22_5 = (NOW_FIXED - timedelta(hours=22, minutes=30)).isoformat()
    topic_stale = _make_dummy_topic("stale-boundary-2", sig="samesig2222")
    faqs_stale = [
        {
            "clinic_id": CLINIC, "topic_key": f"{topic_stale.topic_key}-{it}",
            "category": "special", "question": f"問{it}？", "answer": "答。",
            "metadata": json.dumps({
                "origin": "patient_prefill", "prefill_topic_key": topic_stale.topic_key,
                "intent": it, "generated_at": time_22_5, "ref_signature": "samesig2222",
            }),
        }
        for it in INTENT_TEMPLATES.keys()
    ]
    upsert_faqs(isolated_conn, faqs_stale, source_type="llm_generated")

    plan2 = plan_prefill(isolated_conn, [topic_stale], now=NOW_FIXED, max_topics=5)
    assert len(plan2.topics) == 1
    assert plan2.topics[0].reason == "time_stale"
    assert len(plan2.topics[0].items) == 5


def test_task2_4_signature_changed_priority_over_time_stale(isolated_conn):
    """Test 4（簽章改變）: 簽章改變時 reason=signature_changed，且排序在 time_stale 之前。"""
    # 主題 A: 剛生成 1 小時但簽章變更
    topic_sig = _make_dummy_topic("sig-changed", sig="newsig999999")
    faqs_a = [
        {
            "clinic_id": CLINIC, "topic_key": f"{topic_sig.topic_key}-{it}",
            "category": "special", "question": f"問{it}？", "answer": "答。",
            "metadata": json.dumps({
                "origin": "patient_prefill", "prefill_topic_key": topic_sig.topic_key,
                "intent": it, "generated_at": (NOW_FIXED - timedelta(hours=1)).isoformat(),
                "ref_signature": "oldsig000000",
            }),
        }
        for it in INTENT_TEMPLATES.keys()
    ]
    upsert_faqs(isolated_conn, faqs_a, source_type="llm_generated")

    # 主題 B: 時間過期（48小時）
    topic_stale = _make_dummy_topic("time-stale", sig="stalesig1111")
    faqs_b = [
        {
            "clinic_id": CLINIC, "topic_key": f"{topic_stale.topic_key}-{it}",
            "category": "special", "question": f"問{it}？", "answer": "答。",
            "metadata": json.dumps({
                "origin": "patient_prefill", "prefill_topic_key": topic_stale.topic_key,
                "intent": it, "generated_at": (NOW_FIXED - timedelta(hours=48)).isoformat(),
                "ref_signature": "stalesig1111",
            }),
        }
        for it in INTENT_TEMPLATES.keys()
    ]
    upsert_faqs(isolated_conn, faqs_b, source_type="llm_generated")

    plan = plan_prefill(isolated_conn, [topic_stale, topic_sig], now=NOW_FIXED, max_topics=5)
    assert len(plan.topics) == 2
    assert plan.topics[0].topic.topic_key == topic_sig.topic_key
    assert plan.topics[0].reason == "signature_changed"
    assert plan.topics[1].topic.topic_key == topic_stale.topic_key
    assert plan.topics[1].reason == "time_stale"


def test_task2_5_missing_intents_partial(isolated_conn):
    """Test 5（缺題）: 五列僅有四列 -> 排入 missing_intents，僅排入缺少的意圖。"""
    topic = _make_dummy_topic("partial-topic", sig="sigpart12345")
    # 僅寫入 4 筆意圖（缺少 when_to_see_doctor）
    faqs = [
        {
            "clinic_id": CLINIC, "topic_key": f"{topic.topic_key}-{it}",
            "category": "special", "question": f"問{it}？", "answer": "答。",
            "metadata": json.dumps({
                "origin": "patient_prefill", "prefill_topic_key": topic.topic_key,
                "intent": it, "generated_at": (NOW_FIXED - timedelta(hours=5)).isoformat(),
                "ref_signature": "sigpart12345",
            }),
        }
        for it in ("what", "suitable", "risk", "recovery")
    ]
    upsert_faqs(isolated_conn, faqs, source_type="llm_generated")

    plan = plan_prefill(isolated_conn, [topic], now=NOW_FIXED, max_topics=5)
    assert len(plan.topics) == 1
    t_plan = plan.topics[0]
    assert t_plan.reason == "missing_intents"
    assert len(t_plan.items) == 1
    assert t_plan.items[0].intent == "when_to_see_doctor"
    assert t_plan.missing_intents == ["when_to_see_doctor"]


def test_task2_6_max_topics_truncation_and_backlog(isolated_conn):
    """Test 6（排序與上限）: 6 個過期主題，max_topics=3 -> 回傳 3 個，backlog 為 3。"""
    topics = [_make_dummy_topic(f"batch-t{i}", sig=f"sig{i:08d}") for i in range(1, 7)]
    for i, t in enumerate(topics, 1):
        # 建立 30+i 小時前的列
        t_gen = (NOW_FIXED - timedelta(hours=30 + i)).isoformat()
        faqs = [
            {
                "clinic_id": CLINIC, "topic_key": f"{t.topic_key}-{it}",
                "category": "special", "question": f"問{it}？", "answer": "答。",
                "metadata": json.dumps({
                    "origin": "patient_prefill", "prefill_topic_key": t.topic_key,
                    "intent": it, "generated_at": t_gen, "ref_signature": t.ref_signature,
                }),
            }
            for it in INTENT_TEMPLATES.keys()
        ]
        upsert_faqs(isolated_conn, faqs, source_type="llm_generated")

    plan = plan_prefill(isolated_conn, topics, now=NOW_FIXED, max_topics=3)
    assert len(plan.topics) == 3
    assert plan.stale_total == 6
    assert plan.backlog == 3
    # 最舊的排在最前 (36 小時前 > 35 > 34)
    assert plan.topics[0].topic.topic_key == topics[5].topic_key


def test_task2_7_rejected_row_protected_until_signature_changes(isolated_conn):
    """Test 7: 某意圖列為 rejected、簽章未變、時間過期 -> 該意圖不排入；簽章改變才排入。"""
    topic = _make_dummy_topic("rej-topic", sig="origsig11111")
    t_gen = (NOW_FIXED - timedelta(hours=48)).isoformat()

    faqs = [
        {
            "clinic_id": CLINIC, "topic_key": f"{topic.topic_key}-{it}",
            "category": "special", "question": f"問{it}？", "answer": "答。",
            "metadata": json.dumps({
                "origin": "patient_prefill", "prefill_topic_key": topic.topic_key,
                "intent": it, "generated_at": t_gen, "ref_signature": "origsig11111",
            }),
        }
        for it in INTENT_TEMPLATES.keys()
    ]
    upsert_faqs(isolated_conn, faqs, source_type="llm_generated")
    # 將 what 設為 rejected
    isolated_conn.execute(
        "UPDATE faq_cache SET review_status='rejected' WHERE topic_key=?",
        (f"{topic.topic_key}-what",)
    )
    isolated_conn.commit()

    # 1. 簽章未變：what 不排入，其餘 4 個排入
    plan1 = plan_prefill(isolated_conn, [topic], now=NOW_FIXED, max_topics=5)
    assert len(plan1.topics) == 1
    intents1 = [it.intent for it in plan1.topics[0].items]
    assert "what" not in intents1
    assert len(intents1) == 4
    assert plan1.protected_skipped >= 1

    # 2. 簽章改變：what 重新排入
    topic_new_sig = _make_dummy_topic("rej-topic", sig="newsig22222")
    plan2 = plan_prefill(isolated_conn, [topic_new_sig], now=NOW_FIXED, max_topics=5)
    assert len(plan2.topics) == 1
    intents2 = [it.intent for it in plan2.topics[0].items]
    assert "what" in intents2
    assert len(intents2) == 5


def test_task2_8_approved_rows_do_not_starve_others(isolated_conn):
    """Test 8: 某主題五列皆 approved、簽章未變、過期 100 小時 -> 完全不排入且不佔名額；簽章改變才排入。"""
    topic_approved = _make_dummy_topic("app-topic", sig="appsig111111")
    t_gen = (NOW_FIXED - timedelta(hours=100)).isoformat()

    faqs = [
        {
            "clinic_id": CLINIC, "topic_key": f"{topic_approved.topic_key}-{it}",
            "category": "special", "question": f"問{it}？", "answer": "答。",
            "metadata": json.dumps({
                "origin": "patient_prefill", "prefill_topic_key": topic_approved.topic_key,
                "intent": it, "generated_at": t_gen, "ref_signature": "appsig111111",
            }),
        }
        for it in INTENT_TEMPLATES.keys()
    ]
    upsert_faqs(isolated_conn, faqs, source_type="llm_generated")
    isolated_conn.execute(
        "UPDATE faq_cache SET review_status='approved' WHERE topic_key LIKE ?",
        (f"{topic_approved.topic_key}-%",)
    )
    isolated_conn.commit()

    # 1. 簽章未變：完全不排入
    plan1 = plan_prefill(isolated_conn, [topic_approved], now=NOW_FIXED, max_topics=5)
    assert len(plan1.topics) == 0
    assert plan1.protected_skipped == 5

    # 2. 簽章改變：排入重新生成
    topic_new = _make_dummy_topic("app-topic", sig="newappsig222")
    plan2 = plan_prefill(isolated_conn, [topic_new], now=NOW_FIXED, max_topics=5)
    assert len(plan2.topics) == 1
    assert plan2.topics[0].reason == "signature_changed"


def test_task2_8b_manual_edit_protected(isolated_conn):
    """Test 8b: pending 但 metadata.answer_source='manual_edit'、簽章未變、過期 -> 不排入；簽章變 -> 排入。"""
    topic = _make_dummy_topic("manual-edit-topic", sig="meditsig111")
    t_gen = (NOW_FIXED - timedelta(hours=50)).isoformat()

    faqs = [
        {
            "clinic_id": CLINIC, "topic_key": f"{topic.topic_key}-what",
            "category": "special", "question": "問？", "answer": "答。",
            "metadata": json.dumps({
                "origin": "patient_prefill", "prefill_topic_key": topic.topic_key,
                "intent": "what", "generated_at": t_gen, "ref_signature": "meditsig111",
                "answer_source": "manual_edit",
            }),
        }
    ]
    upsert_faqs(isolated_conn, faqs, source_type="llm_generated")

    # 簽章未變：不排入
    plan1 = plan_prefill(isolated_conn, [topic], now=NOW_FIXED, max_topics=5)
    what_items1 = [it for t in plan1.topics for it in t.items if it.intent == "what"]
    assert len(what_items1) == 0

    # 簽章改變：排入
    topic_new = _make_dummy_topic("manual-edit-topic", sig="meditsig222")
    plan2 = plan_prefill(isolated_conn, [topic_new], now=NOW_FIXED, max_topics=5)
    what_items2 = [it for t in plan2.topics for it in t.items if it.intent == "what"]
    assert len(what_items2) == 1


def test_task2_9_corrupt_metadata_fallback_gracefully(isolated_conn):
    """Test 9: metadata 損毀或缺少 generated_at 視為最舊過期列，不拋出例外。"""
    topic = _make_dummy_topic("corrupt-topic", sig="corruptsig11")
    faqs = [
        {
            "clinic_id": CLINIC, "topic_key": f"{topic.topic_key}-what",
            "category": "special", "question": "問？", "answer": "答。",
            "metadata": "INVALID_JSON_CORRUPTED",
        }
    ]
    upsert_faqs(isolated_conn, faqs, source_type="llm_generated")

    plan = plan_prefill(isolated_conn, [topic], now=NOW_FIXED, max_topics=5)
    assert len(plan.topics) == 1
    # 損毀的 what 應被視為過期排入
    what_items = [it for it in plan.topics[0].items if it.intent == "what"]
    assert len(what_items) == 1


def test_task2_10_plan_prefill_is_strictly_read_only(isolated_conn):
    """Test 10: plan_prefill 全程不寫入資料庫（total_changes 不變）。"""
    topic = _make_dummy_topic("readonly-topic")
    initial_changes = isolated_conn.total_changes

    plan = plan_prefill(isolated_conn, [topic], now=NOW_FIXED, max_topics=5)
    assert isolated_conn.total_changes == initial_changes
