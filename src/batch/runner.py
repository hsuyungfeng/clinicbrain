"""
夜間批次執行器核心模組。

串接主題來源 (topic_sources)、FAQ 預生成 (faq_generator) 與臨床推理樹重建 (tree_rebuild)，
提供具備成本防禦、失敗隔離、LLM 狀態優雅跳過與審核閘門防護的夜間批次排程流程。
注意：本模組保證不直接呼叫外部行程、不直接 import 本地 LLM 呼叫函式、不調用退出行程函式。
"""

from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
import sqlite3
import time
from typing import Callable, Optional

from src.batch.faq_generator import (
    TopicGenResult,
    existing_questions,
    generate_topic_faqs,
    settle_regen_flags,
    write_topic_faqs,
)
from src.batch.run_log import RunLogger, content_loggers_silenced
from src.batch.topic_sources import SelectedTopic, load_seed_file, select_topics
from src.batch.tree_rebuild import find_marked_trees, rebuild_tree
from src.pageindex.faq_review import (
    count_by_status,
    has_review_status,
    regen_marked_rows,
)
from src.pageindex.llm_client import LocalLLMUnavailableError


class BatchPreflightError(Exception):
    """批次前置檢查失敗（例如資料庫尚未遷移審核欄位）。"""


@dataclass
class BatchConfig:
    """夜間批次組態參數。"""

    seed_path: Path
    snapshot_dir: Path
    dry_run: bool = False
    skip_faq: bool = False
    skip_trees: bool = False
    enable_soap_distill: bool = True
    soap_clinic_id: str = "3503190424"
    soap_min_occurrences: int = 2
    soap_only: bool = False
    soap_sync_url: Optional[str] = None
    soap_sync_api_key: Optional[str] = field(default=None, repr=False)
    general_only: bool = False
    skip_general: bool = False
    max_faq_topics: int = 5
    max_trees: int = 3
    since_days: int = 14
    min_miss_count: int = 3
    max_pending: int = 200
    time_budget_seconds: float = 3600.0

    def __post_init__(self) -> None:
        # 互斥旗標防護（CLI 之外的程式化呼叫同樣適用；矛盾組合直接拒絕，不靜默擇一）
        if self.general_only and self.soap_only:
            raise ValueError("general_only 與 soap_only 互斥")
        if self.general_only and self.skip_general:
            raise ValueError("general_only 與 skip_general 互斥")
        if self.general_only and self.skip_faq:
            raise ValueError("general_only 與 skip_faq 矛盾（general_only 僅執行 FAQ 預生成）")


@dataclass
class BatchSummary:
    """夜間批次執行結果摘要。"""

    status: str = "completed"
    soap_distilled_count: int = 0
    soap_conditions: list[str] = field(default_factory=list)
    soap_sync_status: str = "skipped"
    general_generated_count: int = 0
    general_skipped_count: int = 0
    faq_topics_planned: int = 0
    faq_topics_processed: int = 0
    faq_inserted: int = 0
    faq_rejected: int = 0
    faq_skipped_existing: int = 0
    faq_regen_regenerated: int = 0
    faq_regen_unchanged: int = 0
    faq_regen_failed: int = 0
    trees_planned: int = 0
    trees_rebuilt: int = 0
    trees_unchanged: int = 0
    trees_rejected: int = 0
    trees_skipped: int = 0
    trees_overwrote_handwritten: int = 0
    errors: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def run_batch(
    conn: sqlite3.Connection,
    cfg: BatchConfig,
    *,
    llm_call: Callable[[str], str],
    health_check: Callable[[], Optional[str]],
    logger: RunLogger,
    clock: Callable[[], float] = time.monotonic,
) -> BatchSummary:
    """執行完整夜間批次流程。"""
    summary = BatchSummary()
    start_time = clock()

    with content_loggers_silenced():
        logger.info(
            "batch_start",
            dry_run=cfg.dry_run,
            skip_faq=cfg.skip_faq,
            skip_trees=cfg.skip_trees,
            enable_soap_distill=cfg.enable_soap_distill,
            soap_only=cfg.soap_only,
            max_faq_topics=cfg.max_faq_topics,
            max_trees=cfg.max_trees,
            max_pending=cfg.max_pending,
            time_budget_seconds=cfg.time_budget_seconds,
        )

        # ---------------------------------------------------------------------
        # 0. SOAP 臨床居家照護衛教提煉階段
        # ---------------------------------------------------------------------
        soap_stage = (cfg.enable_soap_distill or cfg.soap_only) and not cfg.general_only

        # 0a. 前置增量同步：失敗只降級（沿用本機既有病歷繼續提煉），不中斷批次、不影響後續階段
        if soap_stage and cfg.soap_sync_url and not cfg.dry_run:
            try:
                from src.sync.soap_sync_runner import sync_soap_records_before_batch
                sync_res = sync_soap_records_before_batch(
                    conn,
                    cfg.soap_clinic_id,
                    remote_url=cfg.soap_sync_url,
                    api_key=cfg.soap_sync_api_key,
                )
                summary.soap_sync_status = sync_res.status
                if sync_res.status != "completed":
                    summary.errors += 1
                logger.info(
                    "soap_presync_done",
                    status=sync_res.status,
                    inserted=sync_res.inserted,
                    updated=sync_res.updated,
                    unchanged=sync_res.unchanged,
                    skipped_unsafe=sync_res.skipped_unsafe,
                )
            except Exception as e:
                conn.rollback()
                summary.soap_sync_status = "failed"
                summary.errors += 1
                logger.error("soap_presync_failed", error_type=type(e).__name__)

        if soap_stage:
            try:
                from src.soap.distiller import distill_soap_records
                distill_res = distill_soap_records(
                    conn,
                    clinic_id=cfg.soap_clinic_id,
                    min_occurrences=cfg.soap_min_occurrences,
                    dry_run=cfg.dry_run,
                )
                summary.soap_distilled_count = distill_res.get("distilled_count", 0)
                summary.soap_conditions = distill_res.get("conditions", [])
                logger.info(
                    "soap_distill_done",
                    distilled_count=summary.soap_distilled_count,
                    conditions=summary.soap_conditions,
                    dry_run=cfg.dry_run,
                )
            except Exception as e:
                conn.rollback()  # 提煉中途失敗不得留下未提交交易給後續階段一併提交
                summary.errors += 1
                logger.error("soap_distill_failed", error_type=type(e).__name__)

        if cfg.soap_only:
            logger.info("soap_only_complete", **summary.as_dict())
            return summary

        seed = load_seed_file(cfg.seed_path)

        # ---------------------------------------------------------------------
        # 1. FAQ 規劃階段
        # ---------------------------------------------------------------------
        planned_topics = []
        if not cfg.skip_faq:
            has_review = has_review_status(conn)
            if not has_review:
                if not cfg.dry_run:
                    raise BatchPreflightError(
                        "資料庫尚未完成審核欄位遷移，請先執行 scripts/migrate_faq_review_status.py"
                    )
                else:
                    logger.warning("unmigrated_database_dry_run", reason="missing_review_status")

            pending_count = count_by_status(conn).get("pending", 0) if has_review else 0
            if pending_count >= cfg.max_pending:
                logger.warning(
                    "faq_backlog_skip",
                    pending_count=pending_count,
                    max_pending=cfg.max_pending,
                )
            else:
                selection = select_topics(
                    seed,
                    conn,
                    since_days=cfg.since_days,
                    min_miss_count=cfg.min_miss_count,
                    max_topics=None,
                )
                logger.info(
                    "topic_selection_info",
                    stats_available=selection.stats_available,
                    unmapped_count=len(selection.unmapped_keywords),
                )
                if selection.unmapped_keywords:
                    logger.info(
                        "unmapped_keywords",
                        keywords=[kw for kw, _ in selection.unmapped_keywords[:10]],
                    )

                # 規劃階段在 select_topics 後，以 regen_marked_rows 取得被標記 (clinic_id, topic_key) 集合
                marked_rows = regen_marked_rows(conn) if has_review else []
                marked_keys = {(r["clinic_id"], r["topic_key"]) for r in marked_rows}
                seed_topic_map = {(t.clinic_id, t.topic_key): t for t in seed.topics}

                unmatched_marked_count = 0
                marked_selected_topics = []
                for clinic_id, topic_key in marked_keys:
                    if (clinic_id, topic_key) in seed_topic_map:
                        marked_selected_topics.append(
                            SelectedTopic(
                                topic=seed_topic_map[(clinic_id, topic_key)],
                                reason="regen_marked",
                                hot_count=0,
                            )
                        )
                    else:
                        unmatched_marked_count += 1

                if unmatched_marked_count > 0:
                    logger.warning("unmatched_regen_marked_topics", count=unmatched_marked_count)

                # 合併標記主題與既有選題（標記主題排在最前並依 (clinic_id, topic_key) 去重）
                seen_topic_idents = set()
                all_candidate_topics = []
                for st in marked_selected_topics:
                    ident = (st.topic.clinic_id, st.topic.topic_key)
                    if ident not in seen_topic_idents:
                        seen_topic_idents.add(ident)
                        all_candidate_topics.append(st)

                for st in selection.topics:
                    ident = (st.topic.clinic_id, st.topic.topic_key)
                    if ident not in seen_topic_idents:
                        seen_topic_idents.add(ident)
                        all_candidate_topics.append(st)

                # 依據 general_only / skip_general 過濾主題
                if cfg.general_only:
                    all_candidate_topics = [
                        st for st in all_candidate_topics if st.topic.category == "general"
                    ]
                elif cfg.skip_general:
                    all_candidate_topics = [
                        st for st in all_candidate_topics if st.topic.category != "general"
                    ]

                # 遍歷候選主題，過濾所有問題已存在者（排除被標記重生成題目），再截斷至 max_faq_topics
                for st in all_candidate_topics:
                    topic = st.topic
                    existing = existing_questions(conn, topic.clinic_id, topic.topic_key, exclude_regen_marked=True)
                    pending_q = [q for q in topic.questions if q.strip() not in existing]
                    skipped_count = len(topic.questions) - len(pending_q)
                    if topic.category == "general":
                        summary.general_skipped_count += skipped_count
                    if not pending_q:
                        continue
                    planned_topics.append((st, pending_q))
                    logger.info(
                        "faq_plan",
                        topic_key=topic.topic_key,
                        reason=st.reason,
                        pending_questions_count=len(pending_q),
                    )
                    if len(planned_topics) >= cfg.max_faq_topics:
                        break

            summary.faq_topics_planned = len(planned_topics)

        # ---------------------------------------------------------------------
        # 2. 樹重建規劃階段
        # ---------------------------------------------------------------------
        planned_trees = []
        if not cfg.skip_trees and not cfg.general_only:
            marked_trees = find_marked_trees(conn, limit=cfg.max_trees)
            summary.trees_planned = len(marked_trees)
            for tree_info in marked_trees:
                doc_id = tree_info["doc_id"]
                proc_name = seed.tree_procedure_names.get(doc_id)
                has_name = proc_name is not None
                logger.info("tree_plan", doc_id=doc_id, has_procedure_name=has_name)
                planned_trees.append((tree_info, proc_name))

        # ---------------------------------------------------------------------
        # 3. Dry-Run 判定
        # ---------------------------------------------------------------------
        if cfg.dry_run:
            logger.info("dry_run_done", llm_status="dry-run 未檢查")
            summary.status = "dry_run"
            logger.info("batch_summary", **summary.as_dict())
            return summary

        # ---------------------------------------------------------------------
        # 4. 非 dry-run：LLM 健康檢查
        # ---------------------------------------------------------------------
        try:
            health_check()
        except LocalLLMUnavailableError as e:
            logger.warning("llm_unavailable", error_type=type(e).__name__)
            summary.status = "llm_unavailable"
            logger.info("batch_summary", **summary.as_dict())
            return summary

        # ---------------------------------------------------------------------
        # 5. FAQ 生成與寫入階段
        # ---------------------------------------------------------------------
        if not cfg.skip_faq:
            for st, _ in planned_topics:
                if clock() - start_time >= cfg.time_budget_seconds:
                    logger.warning("budget_exhausted", stage="faq", topic_key=st.topic.topic_key)
                    summary.status = "budget_exhausted"
                    logger.info("batch_summary", **summary.as_dict())
                    return summary

                topic = st.topic
                try:
                    gen_res = generate_topic_faqs(conn, topic, llm_call)
                    ins, upd, unc = write_topic_faqs(conn, gen_res.valid)
                    summary.faq_topics_processed += 1
                    summary.faq_inserted += ins
                    summary.faq_rejected += len(gen_res.rejected)
                    summary.faq_skipped_existing += gen_res.skipped_existing

                    if topic.category == "general":
                        summary.general_generated_count += ins + upd  # 含重生成後更新的題目

                    # 清算重生成旗標
                    settle_details: dict = {}
                    settle = settle_regen_flags(conn, topic, gen_res, details=settle_details)
                    summary.faq_regen_regenerated += settle["regenerated"]
                    summary.faq_regen_unchanged += settle["unchanged"]
                    summary.faq_regen_failed += settle["failed"]

                    reason_counts = dict(Counter(rej.get("code", "other") for rej in gen_res.rejected))
                    logger.info(
                        "faq_topic_done",
                        topic_key=topic.topic_key,
                        inserted=ins,
                        rejected_count=len(gen_res.rejected),
                        rejected_reasons=reason_counts,
                        skipped_existing=gen_res.skipped_existing,
                        faq_regen_regenerated=settle["regenerated"],
                        faq_regen_unchanged=settle["unchanged"],
                        faq_regen_failed=settle["failed"],
                        faq_regen_unchanged_ids=settle_details.get("unchanged_ids", []),
                        faq_regen_failed_ids=settle_details.get("failed_ids", []),
                    )
                except LocalLLMUnavailableError as e:
                    logger.warning(
                        "llm_unavailable",
                        error_type=type(e).__name__,
                        topic_key=topic.topic_key,
                    )
                    summary.status = "llm_unavailable"
                    logger.info("batch_summary", **summary.as_dict())
                    return summary
                except Exception as e:
                    summary.errors += 1
                    logger.error(
                        "faq_topic_failed",
                        topic_key=topic.topic_key,
                        error_type=type(e).__name__,
                    )
                    # 依「一次標記一次嘗試」原則，例外時亦對被標記列清算為 failed
                    try:
                        marked_for_this_topic = [
                            r["question"] for r in regen_marked_rows(conn)
                            if r["clinic_id"] == topic.clinic_id and r["topic_key"] == topic.topic_key
                        ]
                        if marked_for_this_topic:
                            dummy_res = TopicGenResult(
                                topic_key=topic.topic_key,
                                requested=len(topic.questions),
                                skipped_existing=0,
                                valid=[],
                                rejected=[],
                                regen_questions=marked_for_this_topic,
                            )
                            settle = settle_regen_flags(conn, topic, dummy_res)
                            summary.faq_regen_failed += settle["failed"]
                    except Exception:
                        pass

        # ---------------------------------------------------------------------
        # 6. 樹重建階段
        # ---------------------------------------------------------------------
        if not cfg.skip_trees:
            for tree_info, proc_name in planned_trees:
                doc_id = tree_info["doc_id"]
                if not proc_name:
                    summary.trees_skipped += 1
                    logger.info("tree_skipped", doc_id=doc_id, reason="missing_procedure_name")
                    continue

                if clock() - start_time >= cfg.time_budget_seconds:
                    logger.warning("budget_exhausted", stage="trees", doc_id=doc_id)
                    summary.status = "budget_exhausted"
                    logger.info("batch_summary", **summary.as_dict())
                    return summary

                try:
                    rebuild_res = rebuild_tree(
                        conn,
                        doc_id,
                        proc_name,
                        llm_call,
                        snapshot_dir=cfg.snapshot_dir,
                    )

                    if rebuild_res.status == "rebuilt":
                        summary.trees_rebuilt += 1
                        if rebuild_res.previous_source_type in ("manual", "clinic_upload"):
                            summary.trees_overwrote_handwritten += 1
                            logger.warning(
                                "tree_overwrote_handwritten",
                                doc_id=doc_id,
                                previous_source_type=rebuild_res.previous_source_type,
                            )
                    elif rebuild_res.status == "unchanged":
                        summary.trees_unchanged += 1
                    elif rebuild_res.status == "rejected":
                        summary.trees_rejected += 1
                    elif rebuild_res.status == "error":
                        summary.errors += 1

                    snapshot_name = (
                        Path(rebuild_res.snapshot_path).name
                        if rebuild_res.snapshot_path
                        else None
                    )
                    logger.info(
                        "tree_done",
                        doc_id=doc_id,
                        status=rebuild_res.status,
                        reason=rebuild_res.reason,
                        changed_fields=rebuild_res.changed_fields,
                        snapshot_name=snapshot_name,
                    )
                except LocalLLMUnavailableError as e:
                    logger.warning(
                        "llm_unavailable",
                        error_type=type(e).__name__,
                        doc_id=doc_id,
                    )
                    summary.status = "llm_unavailable"
                    logger.info("batch_summary", **summary.as_dict())
                    return summary
                except Exception as e:
                    summary.errors += 1
                    logger.error(
                        "tree_failed",
                        doc_id=doc_id,
                        error_type=type(e).__name__,
                    )

        summary.status = "completed"
        logger.info("batch_summary", **summary.as_dict())
        return summary
