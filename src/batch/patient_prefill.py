"""24 小時預先生成主體醫學資訊生成與寫入模組 (patient_prefill)。

設計原則（P28-PRE、P28-FRESH、P28-TPL）：
1. 依據 28-05 新鮮度規劃逐題由本機 LLM 生成主體醫學資訊衛教問答。
2. 唯一寫入途徑：一律呼叫 faq_writer.upsert_faqs(source_type='llm_generated')，新列恆為 pending，批次絕不自動核准。
3. 價值回答純淨：預生成 answer 僅保留價值段（2～4 句、含警訊句、結尾完整標點），不含追問與預約 CTA。
4. 預算與容量防禦：支援 time_budget_seconds、max_pending 門檻、max_faq_topics 與 LLM 離線優雅中止；dry_run 僅規劃不呼叫模型、不寫入。
5. 嚴格隱私性：RunLogger 日誌白名單不含問句、答案或提示原文，僅記錄代碼與計數。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Callable, Optional, Sequence, Union

from src.batch.patient_prefill_plan import (
    PrefillItem,
    PrefillPlan,
    PrefillTopic,
    PrefillTopicPlan,
    enumerate_prefill_topics,
    plan_prefill,
)
from src.batch.run_log import RunLogger
from src.general.answer_compose import (
    assemble_answer,
    build_compose_prompt,
    is_complete_ending,
    parse_model_output,
    validate_composed,
)
from src.pageindex.faq_writer import upsert_faqs
from src.pageindex.llm_client import (
    LLMEmptyOutputError,
    LLMTruncatedError,
    LocalLLMUnavailableError,
)
from src.pageindex.tree_review import visible_tree_sql


from dataclasses import dataclass, field


def reject_code_for(reason: str, answer_body: str = "") -> str:
    """將驗證失敗原因歸類為結構化細分剔除碼。"""
    from src.general.patient_compose import looks_insufficient

    if looks_insufficient(answer_body):
        return "insufficient_evidence"

    r = (reason or "").lower()
    if "warn" in r or "警訊" in r:
        return "missing_warning"
    if "price" in r or "金額" in r or "價格" in r:
        return "price_leak"
    if "politic" in r or "立場" in r:
        return "political_phrase"
    if "simp" in r or "簡體" in r:
        return "simplified_chinese"
    if "guarantee" in r or "保證" in r:
        return "guarantee_phrase"
    if "med" in r or "劑量" in r or "處方" in r:
        return "dosage_or_prescription"
    if "sent" in r or "句" in r:
        return "sentence_count"
    return "other_validation"


@dataclass
class PrefillResult:
    """預生成階段執行統計摘要。"""
    topics_planned: int = 0
    topics_processed: int = 0
    generated: int = 0
    refreshed_unchanged: int = 0
    rejected: int = 0
    rejected_warning: int = 0
    rejected_insufficient: int = 0
    rejected_reasons: dict[str, int] = field(default_factory=dict)
    protected_skipped: int = 0
    skipped_budget: int = 0
    skipped_no_title: int = 0
    backlog: int = 0
    errors: int = 0
    status: str = "completed"  # completed, budget_exhausted, llm_unavailable, pending_cap


def run_prefill_stage(
    conn: sqlite3.Connection,
    cfg: Any,
    llm_call: Callable[[str], str],
    now: datetime,
    clock: Callable[[], float] = time.monotonic,
    logger: Optional[RunLogger] = None,
    seed_path: Optional[Union[str, Path]] = None,
    start_time: Optional[float] = None,
) -> PrefillResult:
    """執行 24 小時預生成主體醫學資訊階段。"""
    res = PrefillResult()
    stage_start = start_time if start_time is not None else clock()

    effective_seed_path = seed_path or getattr(cfg, "seed_path", "data/batch/faq_seeds.json")

    # 1. 列舉合格主題
    topics = enumerate_prefill_topics(conn, seed_path=effective_seed_path)
    if getattr(cfg, "skip_general", False):
        topics = [t for t in topics if t.category != "general"]

    # 計算因無可讀中文標題而被略過的樹數
    cur = conn.cursor()
    tree_vis = visible_tree_sql(conn)
    cur.execute(f"SELECT doc_id FROM page_index_trees WHERE {tree_vis}")
    all_tree_docs = {row[0] for row in cur.fetchall()}
    enumerated_tree_docs = {t.tree_doc_id for t in topics if t.tree_doc_id}
    res.skipped_no_title = len(all_tree_docs - enumerated_tree_docs)

    # 2. 新鮮度規劃
    max_topics = getattr(cfg, "max_faq_topics", 5)
    plan = plan_prefill(conn, topics, now=now, max_topics=max_topics, regenerate_all=False)

    res.topics_planned = len(plan.topics) + plan.backlog
    res.backlog = plan.backlog
    res.protected_skipped = plan.protected_skipped

    if logger:
        logger.info(
            "prefill_planned",
            planned=res.topics_planned,
            backlog=res.backlog,
            skipped_protected=res.protected_skipped,
            skipped_no_title=res.skipped_no_title,
        )

    # 3. 若為 dry_run，僅規劃不呼叫模型、不寫入資料庫
    if getattr(cfg, "dry_run", False):
        res.status = "completed"
        return res

    # 4. 檢查 pending 總數上限
    cur.execute("SELECT COUNT(*) FROM faq_cache WHERE review_status = 'pending'")
    pending_count = cur.fetchone()[0]
    max_pending = getattr(cfg, "max_pending", 200)
    if pending_count >= max_pending:
        res.status = "pending_cap"
        if logger:
            logger.warning("prefill_pending_cap_reached", current_count=pending_count, cap_limit=max_pending)
        return res

    time_budget = getattr(cfg, "time_budget_seconds", 3600.0)

    # 5. 逐主題逐意圖生成
    for topic_idx, tp_plan in enumerate(plan.topics):
        if clock() - stage_start >= time_budget:
            res.skipped_budget += (len(plan.topics) - topic_idx)
            res.status = "budget_exhausted"
            if logger:
                logger.warning("budget_exhausted", stage="patient_prefill", topic_key=tp_plan.topic.topic_key)
            return res

        res.topics_processed += 1

        for item in tp_plan.items:
            if clock() - stage_start >= time_budget:
                res.skipped_budget += (len(plan.topics) - topic_idx)
                res.status = "budget_exhausted"
                if logger:
                    logger.warning("budget_exhausted", stage="patient_prefill", topic_key=tp_plan.topic.topic_key)
                return res

            cur.execute("SELECT COUNT(*) FROM faq_cache WHERE review_status = 'pending'")
            if cur.fetchone()[0] >= max_pending:
                res.status = "pending_cap"
                if logger:
                    logger.warning("prefill_pending_cap_reached", cap_limit=max_pending)
                return res

            prompt = build_compose_prompt(
                query=item.question,
                evidence_blocks=[tp_plan.topic.reference],
                intent=item.intent,
            )

            try:
                raw_output = llm_call(prompt)
            except LocalLLMUnavailableError:
                res.skipped_budget += (len(plan.topics) - topic_idx)
                res.status = "llm_unavailable"
                if logger:
                    logger.warning("llm_unavailable", stage="patient_prefill", topic_key=tp_plan.topic.topic_key)
                return res
            except (LLMEmptyOutputError, LLMTruncatedError) as e:
                res.rejected += 1
                if logger:
                    logger.info("prefill_item_rejected", topic_key=tp_plan.topic.topic_key, intent_code=item.intent, reason_code=type(e).__name__)
                continue
            except Exception as exc:
                res.errors += 1
                if logger:
                    logger.error("prefill_item_failed", topic_key=tp_plan.topic.topic_key, intent_code=item.intent, error_type=type(exc).__name__)
                continue

            val_text, _ = parse_model_output(raw_output)
            from src.general.patient_compose import looks_insufficient

            if looks_insufficient(val_text):
                res.rejected += 1
                res.rejected_insufficient += 1
                res.rejected_reasons["insufficient_evidence"] = res.rejected_reasons.get("insufficient_evidence", 0) + 1
                if logger:
                    logger.info("prefill_item_rejected", topic_key=tp_plan.topic.topic_key, intent_code=item.intent, reason_code="insufficient_evidence")
                continue

            if not is_complete_ending(val_text):
                res.rejected += 1
                res.rejected_reasons["incomplete_ending"] = res.rejected_reasons.get("incomplete_ending", 0) + 1
                if logger:
                    logger.info("prefill_item_rejected", topic_key=tp_plan.topic.topic_key, intent_code=item.intent, reason_code="incomplete_ending")
                continue

            # 提取 2～4 句價值段（含就醫警訊句），不含追問與 CTA
            from src.general.answer_compose import (
                MAX_VALUE_SENTENCES,
                MIN_VALUE_SENTENCES,
                split_sentences,
            )
            from src.ingestion.medical_safety import has_doctor_warning

            sents = split_sentences(val_text.strip())
            if len(sents) < MIN_VALUE_SENTENCES:
                res.rejected += 1
                res.rejected_reasons["sentence_count"] = res.rejected_reasons.get("sentence_count", 0) + 1
                if logger:
                    logger.info("prefill_item_rejected", topic_key=tp_plan.topic.topic_key, intent_code=item.intent, reason_code="sentence_count")
                continue

            warn_indices = [i for i, s in enumerate(sents) if has_doctor_warning(s)]
            if len(sents) > MAX_VALUE_SENTENCES:
                if warn_indices:
                    w_idx = warn_indices[-1]
                    chosen = {w_idx}
                    for i, s in enumerate(sents):
                        if len(chosen) >= MAX_VALUE_SENTENCES:
                            break
                        if i != w_idx:
                            chosen.add(i)
                    selected_sents = [sents[i] for i in range(len(sents)) if i in chosen]
                else:
                    selected_sents = sents[:MAX_VALUE_SENTENCES]
            else:
                selected_sents = sents

            if len(selected_sents) < MIN_VALUE_SENTENCES:
                res.rejected += 1
                res.rejected_reasons["sentence_count"] = res.rejected_reasons.get("sentence_count", 0) + 1
                if logger:
                    logger.info("prefill_item_rejected", topic_key=tp_plan.topic.topic_key, intent_code=item.intent, reason_code="sentence_count")
                continue

            clean_value_body = "".join(selected_sents).replace("？", "。").replace("?", "。").strip()

            if looks_insufficient(clean_value_body):
                res.rejected += 1
                res.rejected_insufficient += 1
                res.rejected_reasons["insufficient_evidence"] = res.rejected_reasons.get("insufficient_evidence", 0) + 1
                if logger:
                    logger.info("prefill_item_rejected", topic_key=tp_plan.topic.topic_key, intent_code=item.intent, reason_code="insufficient_evidence")
                continue

            if not is_complete_ending(clean_value_body):
                res.rejected += 1
                res.rejected_reasons["incomplete_ending"] = res.rejected_reasons.get("incomplete_ending", 0) + 1
                if logger:
                    logger.info("prefill_item_rejected", topic_key=tp_plan.topic.topic_key, intent_code=item.intent, reason_code="incomplete_ending")
                continue

            ok, reason = validate_composed(clean_value_body, None)
            if not ok:
                rej_code = reject_code_for(reason or "", clean_value_body)
                res.rejected += 1
                if rej_code == "missing_warning":
                    res.rejected_warning += 1
                elif rej_code == "insufficient_evidence":
                    res.rejected_insufficient += 1
                res.rejected_reasons[rej_code] = res.rejected_reasons.get(rej_code, 0) + 1
                if logger:
                    logger.info("prefill_item_rejected", topic_key=tp_plan.topic.topic_key, intent_code=item.intent, reason_code=rej_code)
                continue

            assembled = clean_value_body

            meta = {
                "origin": "patient_prefill",
                "prefill_topic_key": tp_plan.topic.topic_key,
                "intent": item.intent,
                "generated_at": now.isoformat(),
                "ref_signature": tp_plan.topic.ref_signature,
            }
            faq_row = {
                "clinic_id": tp_plan.topic.clinic_id,
                "topic_key": item.topic_key,
                "question": item.question,
                "answer": assembled,
                "category": tp_plan.topic.category,
                "metadata": json.dumps(meta, ensure_ascii=False),
            }

            try:
                ins, upd, unc = upsert_faqs(conn, [faq_row], source_type="llm_generated")
                conn.commit()
                if ins > 0 or upd > 0:
                    res.generated += (ins + upd)
                if unc > 0:
                    res.refreshed_unchanged += unc
            except Exception as exc:
                conn.rollback()
                res.errors += 1
                if logger:
                    logger.error("prefill_upsert_failed", topic_key=tp_plan.topic.topic_key, intent_code=item.intent, error_type=type(exc).__name__)

    res.status = "completed"
    return res
