"""Phase 54-02: 本機 LLM 實質醫學新知比對器、輪巡選題與合規防護。"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, List

from src.utils.price_mask import deep_mask_prices
from src.ingestion.convert_chinese import to_traditional
from src.pageindex.llm_client import VISUAL_SAMPLING, local_llm_call
from src.pageindex.prompt_template import _FORBIDDEN_PHRASES, _POLITICAL_STANCE_PHRASES
from src.refresh.schema import ensure_refresh_tables
from src.refresh.sources import SourceEvidence
from src.visual.edu_schema import EduContent

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)
_PHYSICIAN_NOTE_KEYS = (
    "pre_op_physician_notes",
    "procedure_physician_notes",
    "post_op_short_physician_notes",
    "maintenance_physician_notes",
)


@dataclass(frozen=True)
class RefreshCandidate:
    target_type: str  # 'faq' | 'tree' | 'visual_edu'
    target_key: str
    clinic_id: str | None
    title: str
    query_hint: str
    current_snapshot: dict[str, Any]
    priority_score: int = 0


def _default_refresh_llm(prompt: str) -> str:
    sampling = dict(VISUAL_SAMPLING)
    sampling["max_tokens"] = max(int(sampling.get("max_tokens", 1200)), 1800)
    sampling["temperature"] = 0.2
    return local_llm_call(prompt, timeout=180, sampling=sampling)


def _recursive_traditional(obj: Any) -> Any:
    if isinstance(obj, str):
        return to_traditional(obj.strip())
    if isinstance(obj, list):
        return [_recursive_traditional(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _recursive_traditional(v) for k, v in obj.items()}
    return obj


def _check_compliance(obj: Any) -> None:
    if isinstance(obj, str):
        for kw in _FORBIDDEN_PHRASES:
            if kw in obj:
                raise ValueError(f"提案含保證療效禁詞: {kw}")
        for kw in _POLITICAL_STANCE_PHRASES:
            if kw in obj:
                raise ValueError(f"提案含政治敏感詞彙: {kw}")
        return
    if isinstance(obj, list):
        for x in obj:
            _check_compliance(x)
    elif isinstance(obj, dict):
        for v in obj.values():
            _check_compliance(v)


def _extract_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if "<think>" in text and "</think>" in text:
        text = text.split("</think>", 1)[1].strip()
    text = _CODE_FENCE_RE.sub("", text).strip()
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e <= s:
        raise ValueError("LLM 回傳內容未包含合法 JSON")
    return json.loads(text[s : e + 1])


def _load_hot_miss_keywords(conn: sqlite3.Connection) -> dict[str, int]:
    try:
        rows = conn.execute(
            "SELECT keyword, SUM(count) AS cnt FROM cache_stats "
            "WHERE outcome = 'miss_keyword' AND keyword != '' "
            "AND stat_date >= date('now', 'localtime', '-7 days') "
            "GROUP BY keyword ORDER BY cnt DESC LIMIT 20"
        ).fetchall()
        return {str(r[0]): int(r[1] or 0) for r in rows}
    except sqlite3.OperationalError:
        return {}


def select_refresh_candidates(
    conn: sqlite3.Connection,
    *,
    daily_quota: int = 15,
    target_type: str = "all",
    topic_keys: list[str] | None = None,
) -> List[RefreshCandidate]:
    """依 cache_stats 熱點與最久未檢核順序挑選已核准候選（排除已有 pending 提案者）。"""
    ensure_refresh_tables(conn)
    hot_kws = _load_hot_miss_keywords(conn)
    pending_set = {
        (r[0], r[1])
        for r in conn.execute("SELECT target_type, target_key FROM knowledge_refresh_proposals WHERE status = 'pending'").fetchall()
    }
    verified_map = {
        (r[0], r[1]): r[2]
        for r in conn.execute("SELECT target_type, target_key, last_verified_at FROM knowledge_refresh_log").fetchall()
    }

    pool: list[tuple[int, str, RefreshCandidate]] = []
    types = ["faq", "tree", "visual_edu"] if target_type == "all" else [target_type]

    if "faq" in types:
        rows = conn.execute(
            "SELECT id, clinic_id, topic_key, question, answer, category "
            "FROM faq_cache WHERE review_status = 'approved'"
        ).fetchall()
        for fid, cid, tk, q, a, cat in rows:
            key = str(fid)
            if topic_keys and (tk not in topic_keys and key not in topic_keys):
                continue
            if ("faq", key) in pending_set:
                continue
            score = sum(cnt for kw, cnt in hot_kws.items() if kw in (q or "") or kw in (tk or ""))
            lv = verified_map.get(("faq", key), "")
            pool.append(
                (
                    -score,
                    lv,
                    RefreshCandidate(
                        target_type="faq",
                        target_key=key,
                        clinic_id=cid,
                        title=q,
                        query_hint=f"{tk or ''} {q}",
                        current_snapshot={"topic_key": tk, "question": q, "answer": a, "category": cat},
                        priority_score=score,
                    ),
                )
            )

    if "tree" in types:
        rows = conn.execute(
            "SELECT doc_id, clinic_id, title, pre_op, procedure, post_op_short, maintenance "
            "FROM page_index_trees WHERE review_status = 'approved'"
        ).fetchall()
        for doc_id, cid, title, pre, proc, post, maint in rows:
            if topic_keys and doc_id not in topic_keys:
                continue
            if ("tree", doc_id) in pending_set:
                continue
            score = sum(cnt for kw, cnt in hot_kws.items() if kw in (title or "") or kw in (doc_id or ""))
            lv = verified_map.get(("tree", doc_id), "")
            pool.append(
                (
                    -score,
                    lv,
                    RefreshCandidate(
                        target_type="tree",
                        target_key=doc_id,
                        clinic_id=cid,
                        title=title,
                        query_hint=f"{title} {doc_id}",
                        current_snapshot={
                            "doc_id": doc_id,
                            "title": title,
                            "pre_op": pre,
                            "procedure": proc,
                            "post_op_short": post,
                            "maintenance": maint,
                        },
                        priority_score=score,
                    ),
                )
            )

    if "visual_edu" in types:
        try:
            rows = conn.execute(
                "SELECT topic_key, clinic_id, title, edu_json "
                "FROM visual_assets WHERE review_status = 'approved' AND edu_json IS NOT NULL"
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        for tk, cid, title, edu_s in rows:
            if topic_keys and tk not in topic_keys:
                continue
            if ("visual_edu", tk) in pending_set:
                continue
            score = sum(cnt for kw, cnt in hot_kws.items() if kw in (title or "") or kw in (tk or ""))
            lv = verified_map.get(("visual_edu", tk), "")
            pool.append(
                (
                    -score,
                    lv,
                    RefreshCandidate(
                        target_type="visual_edu",
                        target_key=tk,
                        clinic_id=cid,
                        title=title,
                        query_hint=title,
                        current_snapshot=json.loads(edu_s),
                        priority_score=score,
                    ),
                )
            )

    pool.sort(key=lambda item: (item[0], item[1], item[2].target_type, item[2].target_key))
    return [item[2] for item in pool[: max(1, int(daily_quota))]]


def _build_judge_prompt(cand: RefreshCandidate, evidence: list[SourceEvidence]) -> str:
    ev_text = "\n".join(
        f"- [{ev.published_at}] {ev.title} ({ev.url})\n  摘要: {ev.snippet}" for ev in evidence[:3]
    )
    snap = json.dumps(cand.current_snapshot, ensure_ascii=False)[:1600]
    if cand.target_type == "faq":
        payload_hint = '{"question": "...", "answer": "..."}'
    elif cand.target_type == "tree":
        payload_hint = '{"title": "...", "pre_op": "...", "procedure": "...", "post_op_short": "...", "maintenance": "..."}'
    else:
        payload_hint = "完整的 7 段 EduContent JSON（與現有快照相同欄位結構）"

    return (
        "你是台灣臨床醫學知識庫審核顧問。請比較「現有已發布內容」與「最新權威醫學來源摘要」，"
        "判斷是否出現**實質新醫學證據**（新治療指引、新禁忌症、藥品警訊或舊觀念已被推翻）。\n"
        "若只是措辭不同而醫學實質無異動，請務必回傳 `has_material_change: false`。\n"
        f"【目標類型】: {cand.target_type} | 【標題】: {cand.title}\n"
        f"【現有內容】:\n{snap}\n\n"
        f"【最新權威來源】:\n{ev_text}\n\n"
        "【輸出規範】僅輸出單一合法台灣繁體中文 JSON，不得出現價格數字或保證療效禁詞：\n"
        '{"has_material_change": true/false, "diff_summary": "條列說明差異重點", '
        f'"proposed_payload": {payload_hint}}}\n'
    )


def evaluate_and_propose(
    conn: sqlite3.Connection,
    cand: RefreshCandidate,
    evidence: list[SourceEvidence],
    *,
    llm_call: Callable[[str], str] | None = None,
    dry_run: bool = False,
) -> str:
    """比對來源與現有內容；僅有實質變動才寫入 `pending` 提案。回傳 `'unchanged' | 'proposed' | 'skipped'`。"""
    if not evidence:
        return "skipped"

    ensure_refresh_tables(conn)
    now_iso = datetime.now(timezone.utc).isoformat()
    caller = llm_call or _default_refresh_llm
    raw = caller(_build_judge_prompt(cand, evidence))
    parsed = _extract_json(raw)
    has_change = bool(parsed.get("has_material_change", False))

    if not has_change:
        if not dry_run:
            conn.execute(
                "INSERT INTO knowledge_refresh_log (target_type, target_key, last_verified_at, last_status, last_source_url) "
                "VALUES (?, ?, ?, 'unchanged', ?) "
                "ON CONFLICT(target_type, target_key) DO UPDATE SET "
                "last_verified_at=excluded.last_verified_at, last_status='unchanged', last_source_url=excluded.last_source_url",
                (cand.target_type, cand.target_key, now_iso, evidence[0].url),
            )
            conn.commit()
        return "unchanged"

    diff_summary = to_traditional(str(parsed.get("diff_summary") or "發現權威來源更新"))
    payload = parsed.get("proposed_payload")
    if not isinstance(payload, dict):
        raise ValueError("proposed_payload 必須為 JSON 物件")

    payload = _recursive_traditional(payload)
    payload = deep_mask_prices(payload)
    diff_summary = deep_mask_prices(diff_summary)
    _check_compliance(payload)
    _check_compliance(diff_summary)

    if cand.target_type == "tree":
        for note_key in _PHYSICIAN_NOTE_KEYS:
            payload.pop(note_key, None)
        for req in ("pre_op", "procedure", "post_op_short", "maintenance"):
            if not str(payload.get(req) or "").strip():
                raise ValueError(f"tree 提案缺少必要段落: {req}")
    elif cand.target_type == "faq":
        if not str(payload.get("question") or "").strip() or not str(payload.get("answer") or "").strip():
            raise ValueError("faq 提案缺少 question 或 answer")
    elif cand.target_type == "visual_edu":
        payload["topic_key"] = cand.target_key
        payload["title"] = cand.title
        payload.pop("organ_system", None)
        payload.pop("anatomy_target", None)
        EduContent.model_validate(payload)

    top_ev = evidence[0]
    if not dry_run:
        conn.execute(
            "INSERT OR IGNORE INTO knowledge_refresh_proposals "
            "(target_type, target_key, clinic_id, title, source_url, source_domain, "
            "evidence_summary, diff_summary, current_snapshot, proposed_json, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
            (
                cand.target_type,
                cand.target_key,
                cand.clinic_id,
                cand.title,
                top_ev.url,
                top_ev.domain,
                top_ev.snippet[:500],
                diff_summary[:500],
                json.dumps(cand.current_snapshot, ensure_ascii=False),
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.execute(
            "INSERT INTO knowledge_refresh_log (target_type, target_key, last_verified_at, last_status, last_source_url) "
            "VALUES (?, ?, ?, 'proposed', ?) "
            "ON CONFLICT(target_type, target_key) DO UPDATE SET "
            "last_verified_at=excluded.last_verified_at, last_status='proposed', last_source_url=excluded.last_source_url",
            (cand.target_type, cand.target_key, now_iso, top_ev.url),
        )
        conn.commit()
    return "proposed"
