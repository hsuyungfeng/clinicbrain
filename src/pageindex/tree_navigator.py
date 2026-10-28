"""
Taiwan Clinic Medical PageIndex RAG System - 階層節點推理導航與 VectifyAI TOC 轉換模組 (tree_navigator)

融合上游 VectifyAI/PageIndex 核心機制（Hierarchical TOC Tree Indexing + Reasoning-Based Branch Navigation），
並針對本機單一 slot 推論與台灣醫療法規進行零延遲（0-LLM-hop）最佳化：

1. 節點級分支導航 (select_tree_branches)：
   將 page_index_trees 的四段臨床結構映射為階層節點 (node_id: 0001..0004)，
   根據病患問句意圖動態放大目標分支字元預算（Branch Drill-down），並 100% 優先保留對應醫師權威醫囑 (*_physician_notes)。
2. 長文件 TOC 結構化分段濃縮 (condense_long_document_by_toc)：
   突破 tree_distiller 既往 3,500 字硬性截斷限制；針對超長衛教手冊先建立 TOC 章節節點樹，
   再依四大臨床階段均衡保留頭中尾關鍵段落（尤其是常置於文末的術後照護與警訊）。
3. VectifyAI/PageIndex 標準 Schema 匯出 (to_vectify_tree_schema)：
   將資料庫推理樹無損轉為上游標準巢狀結構 (doc_name, doc_description, structure[node_id, title, summary, nodes])。
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from src.general.answer_compose import classify_intent, clip_at_sentence

# 臨床四段式節點定義：(欄位鍵, 節點編號, 繁中標題, 醫囑欄位鍵, 關聯關鍵字)
CLINICAL_BRANCH_SPECS: tuple[tuple[str, str, str, str, tuple[str, ...]], ...] = (
    (
        "pre_op",
        "0001",
        "術前評估與準備",
        "pre_op_physician_notes",
        ("術前", "評估", "適合", "禁忌", "懷孕", "體質", "準備", "停藥", "條件"),
    ),
    (
        "procedure",
        "0002",
        "療程原理與步驟",
        "procedure_physician_notes",
        ("原理", "過程", "手術", "怎麼做", "是什麼", "時間", "麻醉", "方式", "儀器"),
    ),
    (
        "post_op_short",
        "0003",
        "術後短期照護與警訊",
        "post_op_short_physician_notes",
        ("術後", "恢復", "消腫", "拆線", "傷口", "紅腫", "照護", "照顧", "就醫", "風險", "副作用"),
    ),
    (
        "maintenance",
        "0004",
        "長期維持與日常保養",
        "maintenance_physician_notes",
        ("維持", "保養", "多久", "復發", "防曬", "飲食", "習慣", "長期"),
    ),
)

# 意圖對應之主導分支與次要分支
_INTENT_PRIMARY_BRANCHES: dict[str, tuple[str, ...]] = {
    "what": ("procedure", "pre_op"),
    "suitable": ("pre_op", "procedure"),
    "recovery": ("post_op_short", "maintenance"),
    "risk": ("post_op_short", "pre_op"),
    "when_to_see_doctor": ("post_op_short", "pre_op"),
    "other": ("procedure", "post_op_short"),
}


@dataclass(frozen=True)
class SelectedBranch:
    """經推理導航選取並分配預算後的臨床樹分支節點。"""

    node_id: str
    field_key: str
    label: str
    content: str
    physician_note: str
    is_primary: bool


def select_tree_branches(
    tree_fields: dict[str, Any],
    query: str,
    intent: str | None = None,
    *,
    total_budget: int = 1200,
) -> list[SelectedBranch]:
    """依問句意圖與關鍵字執行零延遲分支推理導航（Branch Drill-down）。

    - 命中問句意圖之主導分支（Primary Branches）獲得較高字元預算（約占 70%）。
    - 次要分支保留精簡摘要（約占 30%），避免無關段落稀釋 Context。
    - 若分支附帶醫師權威醫囑 (*_physician_notes)，強制保留並附加於該節點。
    """
    resolved_intent = intent or classify_intent(query or "")
    primary_keys = set(_INTENT_PRIMARY_BRANCHES.get(resolved_intent, ("procedure", "post_op_short")))

    # 若問句直接包含特定分支關鍵字，亦將該分支提昇為主導分支
    q_norm = (query or "").strip()
    for field_key, _, _, _, kw_list in CLINICAL_BRANCH_SPECS:
        if any(k in q_norm for k in kw_list):
            primary_keys.add(field_key)

    active_specs = []
    for spec in CLINICAL_BRANCH_SPECS:
        field_key, node_id, label, note_key, _ = spec
        raw_text = str(tree_fields.get(field_key) or "").strip()
        raw_note = str(tree_fields.get(note_key) or "").strip()
        if raw_text or raw_note:
            active_specs.append((field_key, node_id, label, raw_text, raw_note, field_key in primary_keys))

    if not active_specs:
        return []

    prim_count = sum(1 for item in active_specs if item[5])
    sec_count = len(active_specs) - prim_count

    if prim_count > 0 and sec_count > 0:
        prim_budget = max(220, int((total_budget * 0.72) / prim_count))
        sec_budget = max(120, int((total_budget * 0.28) / sec_count))
    else:
        even_budget = max(160, int(total_budget / len(active_specs)))
        prim_budget = even_budget
        sec_budget = even_budget

    results: list[SelectedBranch] = []
    for field_key, node_id, label, raw_text, raw_note, is_prim in active_specs:
        budget = prim_budget if is_prim else sec_budget
        clipped_content = clip_at_sentence(raw_text, budget) if raw_text else ""
        clipped_note = clip_at_sentence(raw_note, max(200, budget)) if raw_note else ""
        results.append(
            SelectedBranch(
                node_id=node_id,
                field_key=field_key,
                label=label,
                content=clipped_content,
                physician_note=clipped_note,
                is_primary=is_prim,
            )
        )
    return results


def to_vectify_tree_schema(tree_row: dict[str, Any]) -> dict[str, Any]:
    """將 clinicbrain 的臨床推理樹轉為上游 VectifyAI/PageIndex 標準巢狀 JSON Tree Schema。"""
    doc_id = str(tree_row.get("doc_id") or "unknown-doc")
    title = str(tree_row.get("title") or doc_id)
    summary = str(tree_row.get("summary_text") or "").strip()

    structure: list[dict[str, Any]] = []
    for idx, (field_key, node_id, label, note_key, _) in enumerate(CLINICAL_BRANCH_SPECS, start=1):
        body = str(tree_row.get(field_key) or "").strip()
        note = str(tree_row.get(note_key) or "").strip()
        if not body and not note:
            continue

        child_nodes: list[dict[str, Any]] = []
        if note:
            child_nodes.append(
                {
                    "node_id": f"{node_id}.1",
                    "title": f"{label}（醫師權威醫囑）",
                    "start_index": idx,
                    "end_index": idx,
                    "summary": note,
                    "nodes": [],
                }
            )

        structure.append(
            {
                "node_id": node_id,
                "title": label,
                "start_index": idx,
                "end_index": idx,
                "summary": body,
                "nodes": child_nodes,
            }
        )

    return {
        "doc_name": doc_id,
        "doc_title": title,
        "doc_description": summary or f"{title} 臨床決策推理樹",
        "structure": structure,
    }


_HEADING_OR_PARA_SPLIT_RE = re.compile(r"\n\s*\n|\n(?=#+\s|[一二三四五六七八九十]+、|\d+[.、])")


def condense_long_document_by_toc(text: str, max_chars: int = 3500) -> str:
    """針對超過 max_chars 的長篇醫療文件，建立 TOC 節點並依四大臨床階段均衡濃縮。

    解決 AGENTS.md §2.22 記錄之「tree_distiller 硬切前 3,500 字導致文末術後照護遺失」問題。
    - 長度 <= max_chars 時原樣回傳（100% 向後相容）。
    - 長度 > max_chars 時：依標題/段落切為 TOC 節點，優先保留命中「術前、療程、術後、維持」各階段之節點，
      確保文件後半段的術後短期照護與長期保養完整進入提煉上下文。
    """
    cleaned = (text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned

    raw_blocks = [b.strip() for b in _HEADING_OR_PARA_SPLIT_RE.split(cleaned) if b and b.strip()]
    if len(raw_blocks) <= 1:
        # 無明顯段落時，改依句子切分並取頭、中、尾三段組合
        head_budget = int(max_chars * 0.4)
        mid_budget = int(max_chars * 0.25)
        tail_budget = max_chars - head_budget - mid_budget
        mid_start = max(0, (len(cleaned) // 2) - (mid_budget // 2))
        return (
            clip_at_sentence(cleaned[: head_budget + 120], head_budget)
            + "\n"
            + clip_at_sentence(cleaned[mid_start : mid_start + mid_budget + 120], mid_budget)
            + "\n"
            + clip_at_sentence(cleaned[-(tail_budget + 120) :], tail_budget)
        )[:max_chars]

    # 為每個段落節點評分歸類至四大臨床籃子
    buckets: dict[str, list[tuple[int, str]]] = {
        "pre_op": [],
        "procedure": [],
        "post_op_short": [],
        "maintenance": [],
        "general": [],
    }
    for idx, blk in enumerate(raw_blocks):
        matched_bucket = "general"
        best_hits = 0
        for field_key, _, _, _, kw_list in CLINICAL_BRANCH_SPECS:
            hits = sum(1 for kw in kw_list if kw in blk)
            if hits > best_hits:
                best_hits = hits
                matched_bucket = field_key
        buckets[matched_bucket].append((idx, blk))

    per_stage_budget = int(max_chars * 0.22)
    selected_by_idx: dict[int, str] = {}

    # 1. 優先從四大臨床階段各抽取代表性節點
    for stage_key in ("pre_op", "procedure", "post_op_short", "maintenance"):
        stage_used = 0
        for idx, blk in buckets[stage_key]:
            if stage_used >= per_stage_budget:
                break
            rem = per_stage_budget - stage_used
            piece = clip_at_sentence(blk, rem) if len(blk) > rem else blk
            if piece:
                selected_by_idx[idx] = piece
                stage_used += len(piece) + 1

    # 2. 用剩餘預算依原始順序補齊首尾與一般節點
    current_total = sum(len(v) + 1 for v in selected_by_idx.values())
    for idx, blk in enumerate(raw_blocks):
        if idx in selected_by_idx:
            continue
        rem = max_chars - current_total
        if rem < 60:
            break
        piece = clip_at_sentence(blk, rem) if len(blk) > rem else blk
        if piece:
            selected_by_idx[idx] = piece
            current_total += len(piece) + 1

    ordered_pieces = [selected_by_idx[k] for k in sorted(selected_by_idx.keys())]
    return "\n".join(ordered_pieces)[:max_chars]
