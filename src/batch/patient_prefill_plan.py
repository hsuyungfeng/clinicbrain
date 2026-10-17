"""台灣緻妍外科診所 - 24 小時預先生成主體醫學資訊規劃層 (patient_prefill_plan)。

本模組為純唯讀規劃層（P28-PRE、P28-FRESH）：
1. 主題列舉：以 visible_tree_sql 列舉已核准且具中文標題之決策樹，並納入已核准之 general 種子主題。
2. 題目模板：以程式常數展開 5 大意圖問句（what, suitable, risk, recovery, when_to_see_doctor）。
3. 新鮮度判定：以假時鐘判定距上次生成是否達 24 小時（扣除 2 小時寬限，即 22 小時）。
4. 受保護列：已核准 (approved)、已駁回 (rejected) 或人工編修 (manual_edit) 之列在簽章未變時永不排入。
5. 優先排序：簽章改變 (signature_changed) > 缺題 (missing_intents) > 生成時間過期 (time_stale)。
6. 唯讀設計：全函式不寫入資料庫、不呼叫模型；時鐘由呼叫端強制注入。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import hashlib
import json
import logging
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable, Optional, Sequence, Union

from src.general.answer_compose import clip_at_sentence
from src.ingestion.convert_chinese import to_traditional
from src.ingestion.generate_faq import validate_single_faq
from src.pageindex.faq_review import visible_faq_sql
from src.pageindex.tree_review import visible_tree_sql
from src.query.router import mask_prices

logger = logging.getLogger(__name__)

# 24 小時新鮮度週期與 2 小時提早刷新寬限
FRESHNESS_HOURS = 24
REFRESH_GRACE_HOURS = 2
PREFILL_TOPIC_PREFIX = "prefill-"

# 五大意圖之繁體中文標準疑問句模板（不得含數字、恰一個全形問號、包含 {title}）
INTENT_TEMPLATES: dict[str, str] = {
    "what": "{title}是什麼？",
    "suitable": "{title}適合哪些族群評估進行？",
    "risk": "{title}有哪些風險與注意事項？",
    "recovery": "{title}術後或日常照護應注意哪些重點？",
    "when_to_see_doctor": "{title}出現哪些異常情況時需要儘速就醫？",
}


def _self_validate_templates() -> None:
    """模組載入時自我檢驗模板合規性，不合格直接拋出 RuntimeError。"""
    if len(INTENT_TEMPLATES) != 5:
        raise RuntimeError("INTENT_TEMPLATES 必須恰有 5 個意圖模板")
    expected_intents = {"what", "suitable", "risk", "recovery", "when_to_see_doctor"}
    if set(INTENT_TEMPLATES.keys()) != expected_intents:
        raise RuntimeError(f"INTENT_TEMPLATES 意圖鍵不符: {set(INTENT_TEMPLATES.keys())}")

    sample_titles = ("玻尿酸注射", "感冒居家護理", "皮秒雷射療程")
    for intent, tpl in INTENT_TEMPLATES.items():
        if "{title}" not in tpl:
            raise RuntimeError(f"模板缺少 {{title}}: {intent} -> {tpl}")
        if tpl.count("？") != 1:
            raise RuntimeError(f"模板必須恰有一個全形問號: {intent} -> {tpl}")
        if any(ch.isdigit() for ch in tpl):
            raise RuntimeError(f"模板不得含數字: {intent} -> {tpl}")

        for st in sample_titles:
            q = tpl.format(title=st)
            if to_traditional(q) != q:
                raise RuntimeError(f"模板展開後非繁體中文: {q}")
            ok, reason = validate_single_faq({"question": q, "answer": "請致電診所確認"})
            if not ok:
                raise RuntimeError(f"模板未通過題目法規檢核: {q}, reason={reason}")


# 模組載入時立即自我檢驗
_self_validate_templates()


@dataclass(frozen=True)
class PrefillTopic:
    """待預生成之主題結構。"""
    topic_key: str
    title: str
    category: str
    clinic_id: Optional[str]
    tree_doc_id: Optional[str]
    reference: str
    ref_signature: str
    source_kind: str  # "tree" 或 "seed_faq"


@dataclass
class PrefillItem:
    """單一意圖待生成或重新生成項目。"""
    intent: str
    question: str
    topic_key: str
    existing_id: Optional[int] = None
    existing_status: Optional[str] = None


@dataclass
class PrefillTopicPlan:
    """單一主題之預生成規劃。"""
    topic: PrefillTopic
    reason: str  # "signature_changed", "missing_intents", "time_stale"
    items: list[PrefillItem]
    missing_intents: list[str] = field(default_factory=list)


@dataclass
class PrefillPlan:
    """整體預生成批次規劃結果。"""
    topics: list[PrefillTopicPlan]
    backlog: int
    stale_total: int
    protected_skipped: int


def _is_valid_chinese_title(title: str) -> bool:
    """檢驗主題標題是否為合法可讀繁體中文，且通過醫療法規檢驗。"""
    t = (title or "").strip()
    if not t:
        return False
    # 至少 2 個 CJK 統一表意漢字
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", t))
    if cjk_count < 2:
        return False
    # 不得含任何數字
    if any(c.isdigit() for c in t):
        return False
    # 必須全為繁體中文
    if to_traditional(t) != t:
        return False
    # 通過醫療法規四層檢驗（價格、簡體、政治立場、保證療效）
    ok, _ = validate_single_faq({"question": f"{t}是什麼？", "answer": "請致電診所確認"})
    return ok


def compute_ref_signature(parts: Iterable[tuple[str, int, str]]) -> str:
    """計算參考資料之 12 字元十六進位短雜湊（順序無關、內容或版號變更即變）。"""
    sorted_parts = sorted(parts, key=lambda x: (str(x[0]), int(x[1]), str(x[2])))
    hasher = hashlib.sha256()
    for ident, ver, text in sorted_parts:
        chunk = f"{ident}:{ver}:{text}\n"
        hasher.update(chunk.encode("utf-8"))
    return hasher.hexdigest()[:12]


def _load_seed_topics(seed_path: Union[str, Path]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """載入種子檔案內容，容錯回傳 (tree_names, topics)。"""
    p = Path(seed_path)
    if not p.is_file():
        return {}, []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        tree_names = data.get("tree_procedure_names", {})
        topics = data.get("topics", [])
        return (tree_names if isinstance(tree_names, dict) else {}), (topics if isinstance(topics, list) else [])
    except Exception as exc:
        logger.warning("載入種子清單失敗 (%s): %s", seed_path, exc)
        return {}, []


def enumerate_prefill_topics(
    conn: sqlite3.Connection,
    seed_path: Union[str, Path] = "data/batch/faq_seeds.json",
) -> list[PrefillTopic]:
    """列舉所有已建檔且已核准之主題（決策樹與種子 general 主題）。

    嚴格保證唯讀、不呼叫模型；未經核准內容絕不進入 reference。
    """
    _, raw_seed_topics = _load_seed_topics(seed_path)

    # 建立 seed_topic_by_tree_doc: tree_doc_id -> seed_topic
    seed_by_tree_doc: dict[str, dict[str, Any]] = {}
    for st in raw_seed_topics:
        if isinstance(st, dict) and st.get("tree_doc_id"):
            seed_by_tree_doc[str(st["tree_doc_id"])] = st

    cur = conn.cursor()

    # 檢查 page_index_trees 欄位結構
    cur.execute("PRAGMA table_info(page_index_trees)")
    tree_cols = {row[1] for row in cur.fetchall()}
    has_title_col = "title" in tree_cols
    has_cat_col = "category" in tree_cols

    title_select = "title" if has_title_col else "NULL AS title"
    cat_select = "category" if has_cat_col else "NULL AS category"

    has_status_col = "review_status" in tree_cols
    status_cond = "AND (review_status IS NULL OR review_status NOT IN ('pending', 'rejected'))" if has_status_col else ""

    tree_vis = visible_tree_sql(conn)
    query_trees = f"""
        SELECT doc_id, clinic_id, {cat_select}, summary_text, pre_op, procedure,
               post_op_short, maintenance, content_version, source_type, {title_select}
        FROM page_index_trees
        WHERE {tree_vis} {status_cond}
        ORDER BY id
    """
    cur.execute(query_trees)
    tree_rows = cur.fetchall()

    results: list[PrefillTopic] = []
    processed_doc_ids: set[str] = set()

    for row in tree_rows:
        doc_id = row[0]
        c_id = row[1]
        cat = row[2]
        summary_txt = row[3]
        pre_op = row[4]
        proc = row[5]
        post_op = row[6]
        maint = row[7]
        c_ver = row[8]
        raw_title = row[10]

        # 標題優先順序：
        # 1. page_index_trees.title 欄位（若有且符合中文有效標題）
        chosen_title: Optional[str] = None
        if raw_title and _is_valid_chinese_title(str(raw_title)):
            chosen_title = str(raw_title).strip()
        elif doc_id in seed_by_tree_doc:
            # 2. 種子主題 tree_doc_id 相符者，去除「常見問題」後綴
            st_title = str(seed_by_tree_doc[doc_id].get("title", ""))
            candidate_title = st_title.removesuffix("常見問題").strip()
            if _is_valid_chinese_title(candidate_title):
                chosen_title = candidate_title

        # 3. 若皆無可讀中文標題，絕不以 doc_id 拼湊標題，記錄略過
        if not chosen_title:
            logger.info("決策樹 %s 缺乏有效中文標題，略過預生成", doc_id)
            continue

        processed_doc_ids.add(doc_id)

        # 組裝參考文字：拼接各非空段落，屏蔽價格後截斷至 1200 字
        ref_parts: list[str] = []
        for seg in (summary_txt, pre_op, proc, post_op, maint):
            if seg and str(seg).strip():
                ref_parts.append(str(seg).strip())
        raw_ref = "\n".join(ref_parts)
        masked_ref = mask_prices(raw_ref)
        clipped_ref = clip_at_sentence(masked_ref, 1200)

        sig = compute_ref_signature([(doc_id, c_ver or 1, clipped_ref)])
        final_cat = cat or ("general" if c_id is None else "special")

        results.append(PrefillTopic(
            topic_key=f"{PREFILL_TOPIC_PREFIX}{doc_id}",
            title=chosen_title,
            category=final_cat,
            clinic_id=c_id,
            tree_doc_id=doc_id,
            reference=clipped_ref,
            ref_signature=sig,
            source_kind="tree",
        ))

    # B) 種子清單中 category 為 general 且 tree_doc_id 為空之主題
    faq_vis = visible_faq_sql(conn)
    for st in raw_seed_topics:
        if not isinstance(st, dict):
            continue
        st_cat = st.get("category")
        st_tree_doc = st.get("tree_doc_id")
        st_key = st.get("topic_key")
        st_title = str(st.get("title", ""))

        if st_cat != "general" or st_tree_doc:
            continue
        if not st_key:
            continue

        candidate_title = st_title.removesuffix("常見問題").strip()
        if not _is_valid_chinese_title(candidate_title):
            continue

        # 查詢已核准之同 topic_key FAQ（排除 pending 或 rejected）
        cur.execute(
            f"""
            SELECT id, content_version, question, answer
            FROM faq_cache
            WHERE clinic_id IS NULL AND topic_key = ?
              AND {faq_vis}
              AND (review_status IS NULL OR review_status NOT IN ('pending', 'rejected'))
            ORDER BY id
            """,
            (st_key,),
        )
        faq_rows = cur.fetchall()
        if not faq_rows:
            # 無已核准資料者不列入（不憑空生成）
            continue

        ref_lines: list[str] = []
        sig_parts: list[tuple[str, int, str]] = []
        for f_id, f_ver, q, a in faq_rows:
            qa_text = f"問：{str(q).strip()}\n答：{str(a).strip()}"
            ref_lines.append(qa_text)
            sig_parts.append((str(f_id), f_ver or 1, qa_text))

        raw_ref = "\n".join(ref_lines)
        masked_ref = mask_prices(raw_ref)
        clipped_ref = clip_at_sentence(masked_ref, 1200)
        sig = compute_ref_signature(sig_parts)

        results.append(PrefillTopic(
            topic_key=f"{PREFILL_TOPIC_PREFIX}{st_key}",
            title=candidate_title,
            category="general",
            clinic_id=None,
            tree_doc_id=None,
            reference=clipped_ref,
            ref_signature=sig,
            source_kind="seed_faq",
        ))

    return results


def _parse_iso_datetime(val: Any) -> Optional[datetime]:
    """容錯解析 ISO 格式日期時間字串為 UTC datetime。"""
    if not val or not isinstance(val, str):
        return None
    try:
        dt = datetime.fromisoformat(val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def plan_prefill(
    conn: sqlite3.Connection,
    topics: list[PrefillTopic],
    now: datetime,
    max_topics: int = 10,
    regenerate_all: bool = False,
) -> PrefillPlan:
    """規劃 24 小時預生成批次佇列。

    時鐘強制由 now 參數注入，全程純唯讀、不修改資料庫、不呼叫模型。
    """
    ref_now = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    stale_cutoff = timedelta(hours=FRESHNESS_HOURS - REFRESH_GRACE_HOURS)

    cur = conn.cursor()
    cur.execute("PRAGMA table_info(faq_cache)")
    cols = {r[1] for r in cur.fetchall()}
    has_meta = "metadata" in cols
    has_status = "review_status" in cols

    meta_select = "metadata" if has_meta else "NULL AS metadata"
    status_select = "review_status" if has_status else "NULL AS review_status"

    candidate_plans: list[tuple[int, datetime, str, PrefillTopicPlan]] = []
    total_protected_skipped = 0

    reason_priority = {
        "signature_changed": 0,
        "missing_intents": 1,
        "time_stale": 2,
    }

    for topic in topics:
        expected_keys = {f"{topic.topic_key}-{it}": it for it in INTENT_TEMPLATES}

        if topic.clinic_id is None:
            clinic_cond = "clinic_id IS NULL"
            params: list[Any] = [f"{topic.topic_key}-%"]
        else:
            clinic_cond = "clinic_id = ?"
            params = [topic.clinic_id, f"{topic.topic_key}-%"]

        query = f"""
            SELECT id, topic_key, question, {status_select}, {meta_select}
            FROM faq_cache
            WHERE {clinic_cond} AND topic_key LIKE ?
        """
        cur.execute(query, params)
        rows = cur.fetchall()

        existing_by_intent: dict[str, dict[str, Any]] = {}
        for r in rows:
            r_id, r_key, r_q, r_status, r_meta_raw = r[0], r[1], r[2], r[3], r[4]
            meta_dict: dict[str, Any] = {}
            corrupted = False
            if r_meta_raw:
                try:
                    loaded = json.loads(r_meta_raw)
                    if isinstance(loaded, dict):
                        meta_dict = loaded
                    else:
                        corrupted = True
                except Exception:
                    corrupted = True

            intent_found: Optional[str] = None
            if meta_dict.get("intent") in INTENT_TEMPLATES:
                intent_found = str(meta_dict["intent"])
            elif r_key in expected_keys:
                intent_found = expected_keys[r_key]

            if intent_found:
                existing_by_intent[intent_found] = {
                    "id": r_id,
                    "status": r_status,
                    "meta": meta_dict,
                    "corrupted": corrupted,
                    "topic_key": r_key,
                }

        queued_items: list[PrefillItem] = []
        topic_protected_skipped = 0
        has_sig_change = False
        gen_datetimes: list[datetime] = []
        missing_intents: list[str] = [it for it in INTENT_TEMPLATES if it not in existing_by_intent]

        for it, tpl in INTENT_TEMPLATES.items():
            q_text = tpl.format(title=topic.title)
            item_topic_key = f"{topic.topic_key}-{it}"

            if it not in existing_by_intent:
                queued_items.append(PrefillItem(
                    intent=it,
                    question=q_text,
                    topic_key=item_topic_key,
                    existing_id=None,
                    existing_status=None,
                ))
            else:
                info = existing_by_intent[it]
                ex_id = info["id"]
                ex_status = info["status"]
                meta = info["meta"]
                is_corrupt = info["corrupted"]

                dt = _parse_iso_datetime(meta.get("generated_at"))
                if dt is not None:
                    gen_datetimes.append(dt)

                col_sig = meta.get("ref_signature")
                sig_mismatch = is_corrupt or (col_sig != topic.ref_signature) or regenerate_all

                if sig_mismatch:
                    has_sig_change = True
                    queued_items.append(PrefillItem(
                        intent=it,
                        question=q_text,
                        topic_key=item_topic_key,
                        existing_id=ex_id,
                        existing_status=ex_status,
                    ))
                else:
                    ans_source = meta.get("answer_source")
                    is_protected = (ex_status in ("approved", "rejected")) or (ans_source == "manual_edit")

                    if is_protected:
                        topic_protected_skipped += 1
                    else:
                        if dt is None:
                            is_stale = True
                        else:
                            is_stale = ((ref_now - dt) >= stale_cutoff)

                        if is_stale:
                            queued_items.append(PrefillItem(
                                intent=it,
                                question=q_text,
                                topic_key=item_topic_key,
                                existing_id=ex_id,
                                existing_status=ex_status,
                            ))

        total_protected_skipped += topic_protected_skipped

        if queued_items:
            if has_sig_change:
                reason = "signature_changed"
            elif missing_intents:
                reason = "missing_intents"
            else:
                reason = "time_stale"

            oldest_dt = min(gen_datetimes) if gen_datetimes else datetime.min.replace(tzinfo=timezone.utc)
            t_plan = PrefillTopicPlan(
                topic=topic,
                reason=reason,
                items=queued_items,
                missing_intents=missing_intents,
            )
            candidate_plans.append((reason_priority[reason], oldest_dt, topic.topic_key, t_plan))

    candidate_plans.sort(key=lambda x: (x[0], x[1], x[2]))
    stale_total = len(candidate_plans)
    final_topics = [p[3] for p in candidate_plans[:max_topics]]
    backlog = max(0, stale_total - max_topics)

    return PrefillPlan(
        topics=final_topics,
        backlog=backlog,
        stale_total=stale_total,
        protected_skipped=total_protected_skipped,
    )
