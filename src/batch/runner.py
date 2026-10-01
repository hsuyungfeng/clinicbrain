"""
夜間批次執行器核心模組。

串接主題來源 (topic_sources)、FAQ 預生成 (faq_generator) 與臨床推理樹重建 (tree_rebuild)，
提供具備成本防禦、失敗隔離、LLM 狀態優雅跳過與審核閘門防護的夜間批次排程流程。
注意：本模組保證不直接呼叫外部行程、不直接 import 本地 LLM 呼叫函式、不調用退出行程函式。
"""

from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
import sqlite3
import time
from typing import Callable, Optional

from src.batch.faq_generator import (
    existing_questions,
    generate_topic_faqs,
    write_topic_faqs,
)
from src.batch.run_log import RunLogger, content_loggers_silenced
from src.batch.topic_sources import load_seed_file, select_topics
from src.batch.tree_rebuild import find_marked_trees, rebuild_tree
from src.pageindex.faq_review import count_by_status, has_review_status
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
    max_faq_topics: int = 5
    max_trees: int = 3
    since_days: int = 14
    min_miss_count: int = 3
    max_pending: int = 200
    time_budget_seconds: float = 3600.0


@dataclass
class BatchSummary:
    """夜間批次執行結果摘要。"""

    status: str = "completed"
    faq_topics_planned: int = 0
    faq_topics_processed: int = 0
    faq_inserted: int = 0
    faq_rejected: int = 0
    faq_skipped_existing: int = 0
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
            max_faq_topics=cfg.max_faq_topics,
            max_trees=cfg.max_trees,
            max_pending=cfg.max_pending,
            time_budget_seconds=cfg.time_budget_seconds,
        )

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

                # 遍歷候選主題，過濾所有問題已存在者，再截斷至 max_faq_topics
                for st in selection.topics:
                    topic = st.topic
                    existing = existing_questions(conn, topic.clinic_id, topic.topic_key)
                    pending_q = [q for q in topic.questions if q not in existing]
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
        if not cfg.skip_trees:
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

                    reason_counts = dict(Counter(rej.reason for rej in gen_res.rejected))
                    logger.info(
                        "faq_topic_done",
                        topic_key=topic.topic_key,
                        inserted=ins,
                        rejected_count=len(gen_res.rejected),
                        rejected_reasons=reason_counts,
                        skipped_existing=gen_res.skipped_existing,
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
