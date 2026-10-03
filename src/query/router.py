#!/usr/bin/env python3
"""
Taiwan Clinic Medical PageIndex RAG System - special/general 查詢路由
Phase 01 Task 5: search/query interface with routing

路由邏輯（設計沿用先前研究階段確立的原則，見 AGENTS.md、
.planning/VISION-EXPANSION.md）：
- special：涉及本診所營運資訊（門診時間、地址電話）、特定療程細節、
  藥品/服務項目查詢——這些資料來自 clinicbrain 自己的結構化資料庫，
  必須精準檢索，不能讓 LLM 憑空生成。
- general：一般醫學常識、症狀衛教，不涉及特定診所資訊。

CONSTRAINT 遵循：
- 任何查詢結果回傳前，一律先經過 mask_prices() 過濾，即使資料庫內容
  本身已經不含價格（防禦式設計——未來資料來源可能不受控，例如診所
  上傳文件擷取進來的內容）。
- 路由分類錯誤的後果：若 general 問題被誤判為 special，可能讓診所
  專屬資料（如個別療程細節、營運資訊）滲入不該出現的情境；若 special
  問題被誤判為 general，會漏掉關鍵的診所資訊。寧可 special 判定寬鬆
  （多納入一些可能相關的診所資料），也不要 general 判定寬鬆到吃進
  診所專屬內容。
"""

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Literal, Optional

try:
    from .search import (
        search_drugs,
        search_service_items,
        search_page_index_trees,
        search_faq_cache,
    )
    from .faq_shortcut import (
        select_confident_faq,
        select_confident_faq_tiered,
        SHORTCUT_CANDIDATE_LIMIT,
    )
except ImportError:
    from search import (
        search_drugs,
        search_service_items,
        search_page_index_trees,
        search_faq_cache,
    )
    from faq_shortcut import (
        select_confident_faq,
        select_confident_faq_tiered,
        SHORTCUT_CANDIDATE_LIMIT,
    )


Route = Literal["special", "general"]

# 觸發 special 路由的關鍵字類別。任一類別命中即判定為 special。
_CLINIC_OPS_KEYWORDS = ("營業", "開門", "關門", "門診時間", "地址", "電話", "怎麼去", "營業時間", "幾點")
_PROCEDURE_KEYWORDS = (
    "雷射", "拉皮", "拉提", "填充", "玻尿酸", "肉毒", "電波", "音波", "飛梭",
    "除斑", "除毛", "拆線", "術前", "術後", "回診", "療程",
    "瘦瘦筆", "甲溝炎", "粉瘤", "脂肪瘤", "蟹足腫", "微創",
)
_DRUG_OR_SERVICE_KEYWORDS = ("藥", "成分", "副作用", "支付", "給付", "健保", "點數", "報保")

# 絕對禁止出現的價格格式：數字+元/塊，或 NT$/$ 開頭的金額
_PRICE_PATTERN = re.compile(r"\d+\s*[元塊]|NT\$\s*\d+|\$\d+")
_PRICE_MASK = "[請致電診所確認]"


# 中文連續字元擷取，用於 extract_search_terms() 的 fallback：把問句切成
# 幾段連續中文子字串，濾掉純標點/語助詞片段。
_CJK_RUN_PATTERN = re.compile(r"[一-鿿]+")

# 常見疑問語助詞/句型片段。這些字串會被當作「切割點」把一段連續中文
# 拆成更短的候選詞（例如「乙醯胺酚是什麼藥」在「是什麼」處被切成
# 「乙醯胺酚」與「藥」），而不只是整段完全等於語助詞時才丟棄——否則
# 像「乙醯胺酚是什麼藥」這種整句本身不在清單裡的情況會完全漏抽詞。
# 2 字元低資訊通用詞：在多筆 PageIndex 摘要中都會出現，走 LIKE fallback 時
# 會命中大量無關資料。排序時降到所有具體詞之後（不刪除，避免只剩這類詞的
# 問句完全搜不到東西）。新增詞彙前請先確認它確實在多個療程中普遍出現。
_GENERIC_TERMS = frozenset(
    ("維持", "回診", "術後", "術前", "療程", "注意", "照護", "恢復", "效果", "治療")
)

_STOPWORD_SPLIT_PATTERN = re.compile(
    "|".join(
        re.escape(w)
        for w in sorted(
            (
                "是什麼", "什麼", "會痛嗎", "會不會", "怎麼辦", "怎麼樣", "怎麼",
                "好嗎", "嗎", "呢", "的", "有沒有", "可以嗎", "要多久", "多久",
                "要注意", "注意事項", "請問", "可以", "需要", "或是", "或者",
                "還有", "和", "跟", "或", "有",
            ),
            key=len,
            reverse=True,
        )
    )
)


def extract_search_terms(query: str) -> list[str]:
    """從使用者的自然語言問句中擷取適合拿去 FTS/LIKE 搜尋的詞彙。

    背景：FTS5 trigram MATCH 要求查詢字串完整連續匹配索引內容，把整句
    自然語言問句（如「音波拉提會痛嗎？」）直接丟給 MATCH 幾乎必然失敗
    （即使句子裡包含完全存在於資料庫的詞彙如「音波拉提」）。必須先把
    問句拆解成候選詞彙，逐一嘗試搜尋。

    策略（簡易版，非斷詞演算法）：
    1. 若命中路由關鍵字表（_PROCEDURE_KEYWORDS/_DRUG_OR_SERVICE_KEYWORDS/
       _CLINIC_OPS_KEYWORDS），優先使用這些命中詞——它們是已知有效的
       醫療/診所術語。
    2. 額外用正則切出問句中所有連續中文字元段，再以常見疑問語助詞
       （見 _STOPWORD_SPLIT_PATTERN）為切割點進一步拆成更短片段，作為
       fallback 候選——這讓「乙醯胺酚是什麼藥？」這類問句中未被關鍵字
       表涵蓋的專有名詞（乙醯胺酚）也能被抓出來嘗試搜尋。

    已知限制：這不是真正的中文斷詞（無詞庫、無語意理解），對複雜問句
    可能切出不精確的候選詞（例如「請問哪家診所」中的「哪家診所」）。
    另外，2 字元的通用詞（如「維持」「回診」在多筆 PageIndex 摘要中都
    出現）走 LIKE fallback 時可能命中大量無關資料，稀釋 result set 的
    精準度——目前靠「較長/較具體的詞優先排序」緩解（見下方 candidates
    排序），正確答案通常仍排在前面，但不保證完全過濾雜訊。現階段以
    涵蓋常見醫療術語查詢為目標，非通用 NLP 斷詞替代品——若未來查詢
    準確率不足，應評估導入真正的中文分詞器（如 jieba）。
    """
    # 單一字元的關鍵字（如「藥」「痛」）只適合用來判斷路由意圖，不適合
    # 拿去做 LIKE 子字串搜尋——會匹配到大量無關資料（例如「藥」會命中
    # 幾乎所有藥品名稱）。搜尋用詞彙一律要求至少 2 字元。
    keyword_hits = [
        kw
        for kw in _CLINIC_OPS_KEYWORDS + _PROCEDURE_KEYWORDS + _DRUG_OR_SERVICE_KEYWORDS
        if kw in query and len(kw) >= 2
    ]

    # 先把整句按連續中文字元切成大段，再用語助詞當切割點把每一大段
    # 進一步拆成更短的候選詞（見上方 _STOPWORD_SPLIT_PATTERN 說明），
    # 濾掉切完後仍過短（<2字）或整段仍是語助詞的片段。
    cjk_fragments = []
    for run in _CJK_RUN_PATTERN.findall(query):
        for fragment in _STOPWORD_SPLIT_PATTERN.split(run):
            fragment = fragment.strip()
            if len(fragment) >= 2:
                cjk_fragments.append(fragment)

    # 低資訊通用詞降到最後（仍保留，當問句只剩這些詞時才有得搜），其餘
    # 依詞彙長度由長到短排序（越長越具體、越不容易誤中無關資料），
    # 長度相同則保留原本偵測順序；去重保留第一次出現。
    candidates = keyword_hits + cjk_fragments
    ordered = sorted(
        range(len(candidates)),
        key=lambda i: (candidates[i] in _GENERIC_TERMS, -len(candidates[i]), i),
    )

    seen = set()
    terms = []
    for i in ordered:
        term = candidates[i]
        if term not in seen:
            seen.add(term)
            terms.append(term)

    return terms if terms else [query]


@dataclass
class RouteResult:
    route: Route
    matched_keywords: list = field(default_factory=list)


def classify(query: str) -> RouteResult:
    """依關鍵字判斷查詢應走 special 還是 general 路由。"""
    matched = []
    for kw in _CLINIC_OPS_KEYWORDS + _PROCEDURE_KEYWORDS + _DRUG_OR_SERVICE_KEYWORDS:
        if kw in query:
            matched.append(kw)

    route: Route = "special" if matched else "general"
    return RouteResult(route=route, matched_keywords=matched)


def mask_prices(text: str) -> str:
    """把任何形式的價格資訊替換成統一的引導文字。這是 CONSTRAINT 的最後
    一道防線，任何要回傳給使用者的文字都應該先經過這裡。"""
    if not text:
        return text
    return _PRICE_PATTERN.sub(_PRICE_MASK, text)


def get_clinic_hours(conn: sqlite3.Connection, clinic_id: str) -> list[dict]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT day_of_week, morning_start, morning_end, afternoon_start, afternoon_end,
               evening_start, evening_end, is_open
        FROM clinic_hours
        WHERE clinic_id = ?
        ORDER BY id
        """,
        (clinic_id,),
    )
    columns = (
        "day_of_week", "morning_start", "morning_end", "afternoon_start",
        "afternoon_end", "evening_start", "evening_end", "is_open",
    )
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def get_clinic_info(conn: sqlite3.Connection, clinic_id: str) -> dict | None:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT clinic_id, name, phone, address, website, clinic_type FROM clinic_info WHERE clinic_id = ?",
        (clinic_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    columns = ("clinic_id", "name", "phone", "address", "website", "clinic_type")
    return dict(zip(columns, row))


def get_clinic_custom_notes(conn: sqlite3.Connection, clinic_id: str) -> dict[str, str]:
    """回傳指定診所的通用段落備註字典 {section: note}。
    例如 {"pre_op": "...", "post_op_short": "..."}。
    這是診所層級、跨所有療程適用的通則，與單一療程專屬的 *_physician_notes 獨立分開。
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT section, note
        FROM clinic_custom_notes
        WHERE clinic_id = ?
        ORDER BY id ASC
        """,
        (clinic_id,),
    )
    return {row[0]: row[1] for row in cursor.fetchall()}


def _search_terms_merged(
    search_fn, conn: sqlite3.Connection, terms: list[str], limit: int, **kwargs
) -> list:
    """對多個候選詞彙分別呼叫 search_fn，合併結果並依 row_id 去重（保留
    第一次出現的順序——關鍵字命中詞優先於 CJK fallback 片段，因為
    extract_search_terms() 已經照這個優先順序排列 terms）。"""
    seen_ids = set()
    merged = []
    for term in terms:
        for hit in search_fn(conn, term, limit=limit, **kwargs):
            if hit.row_id not in seen_ids:
                seen_ids.add(hit.row_id)
                merged.append(hit)
    return merged[:limit]


@dataclass
class QueryResponse:
    route: Route
    matched_keywords: list
    clinic_info: dict | None
    clinic_hours: list
    page_index_hits: list
    drug_hits: list
    service_item_hits: list
    clinic_custom_notes: dict = field(default_factory=dict)
    faq_hits: list = field(default_factory=list)
    source: Literal["cache", "pageindex", "llm"] = "pageindex"
    cache_answer: Optional[str] = None
    cache_eligible: bool = True
    data_level: Optional[Literal["clinic", "general"]] = None


def faq_hit_level(hit) -> Literal["clinic", "general"]:
    """判定單筆 FAQ 命中的資料層級（Phase 11 CF-03）。
    fields 內 clinic_id 有值（非 None 且非空字串）為 clinic，否則為 general。
    """
    cid = hit.fields.get("clinic_id")
    return "clinic" if cid else "general"


def _gather_faq_hits(
    conn: sqlite3.Connection,
    terms: list[str],
    limit: int,
    clinic_id: Optional[str],
    route: Route,
) -> list:
    """依診所身分與路由彙集 FAQ 檢索結果（Phase 11 CF-01, CF-02, 決策 1）。

    遵守設計規範：
    1. 無 clinic_id 時：檢索後僅保留 clinic_id IS NULL 的 general FAQ，徹底防堵跨診所外洩。
    2. 有 clinic_id 且 route=='special'：檢索後診所層級排在 general 之前（穩定排序）。
    3. 有 clinic_id 且 route=='general'：隔離宣告局部放寬，優先檢索診所自己的 special FAQ，
       再接續 general FAQ，依 row_id 去重後截斷至 limit。
    4. 嚴禁在 router.py 撰寫原生 SQL，一律透過 search_faq_cache 檢索。
    """
    if clinic_id is None:
        raw_hits = _search_terms_merged(
            search_faq_cache,
            conn,
            terms,
            max(limit, SHORTCUT_CANDIDATE_LIMIT),
            clinic_id=None,
            category="general" if route == "general" else None,
        )
        filtered = [h for h in raw_hits if h.fields.get("clinic_id") is None]
        return filtered[:limit]

    if route == "special":
        raw_hits = _search_terms_merged(
            search_faq_cache,
            conn,
            terms,
            limit,
            clinic_id=clinic_id,
            category=None,
        )
        # 穩定排序：診所專屬層級在前，general 在後
        return sorted(raw_hits, key=lambda h: 0 if faq_hit_level(h) == "clinic" else 1)

    # 有效 clinic_id 且 route == "general"：
    # 局部放寬：先檢索診所自己的 special FAQ，再檢索 general FAQ
    clinic_special_hits = _search_terms_merged(
        search_faq_cache,
        conn,
        terms,
        max(limit, SHORTCUT_CANDIDATE_LIMIT),
        clinic_id=clinic_id,
        category="special",
    )
    clinic_special_hits = [h for h in clinic_special_hits if h.fields.get("clinic_id") == clinic_id]

    general_hits = _search_terms_merged(
        search_faq_cache,
        conn,
        terms,
        max(limit, SHORTCUT_CANDIDATE_LIMIT),
        clinic_id=None,
        category="general",
    )
    general_hits = [h for h in general_hits if h.fields.get("clinic_id") is None]

    merged_hits = []
    seen_ids = set()
    for h in clinic_special_hits + general_hits:
        if h.row_id not in seen_ids:
            seen_ids.add(h.row_id)
            merged_hits.append(h)

    return merged_hits[:limit]


def handle_query(
    conn: sqlite3.Connection,
    query: str,
    clinic_id: str | None = None,
    limit: int = 5,
    cache_shortcut: bool = True,
) -> QueryResponse:
    """統一查詢入口：分類路由 → 依路由查對應資料表 → 對所有文字欄位套用
    價格遮罩 → 評估 FAQ 快取短路 → 回傳結構化結果。

    general 路由刻意不查 clinic_info/clinic_hours/clinic_custom_notes（避免診所
    專屬資訊滲入一般醫學問答，見模組頂部說明），且本質上不需要 clinic_id，
    因此 clinic_id 預設為 None。但 special 路由若涉及診所營運、療程樹或通用備註，
    若呼叫端未傳入 clinic_id，將拋出明確之 ValueError。

    cache_shortcut 預設為 True。若問句不含診所營運關鍵字且存在高信心精確匹配的 FAQ，
    將短路回傳該 FAQ 原文（已遮蔽價格），其餘非必要欄位清空，加速回應。
    """
    # clinic_id 正規化：None、空字串或純空白一律視為 None
    if clinic_id is not None:
        clinic_id = clinic_id.strip()
        if not clinic_id:
            clinic_id = None

    route_result = classify(query)
    search_terms = extract_search_terms(query)

    clinic_info = None
    clinic_hours: list = []
    clinic_custom_notes: dict = {}

    if route_result.route == "special" and any(kw in query for kw in _CLINIC_OPS_KEYWORDS):
        if clinic_id is None:
            raise ValueError(f"special 路由查詢診所營運資訊需要提供 clinic_id（問句：'{query}'）")
        clinic_info = get_clinic_info(conn, clinic_id)
        clinic_hours = get_clinic_hours(conn, clinic_id)

    page_index_hits = _search_terms_merged(
        search_page_index_trees, conn, search_terms, limit, clinic_id=clinic_id
    )
    drug_hits = _search_terms_merged(search_drugs, conn, search_terms, limit)
    service_item_hits = _search_terms_merged(search_service_items, conn, search_terms, limit)
    faq_hits = _gather_faq_hits(conn, search_terms, limit, clinic_id, route_result.route)

    if route_result.route == "general":
        page_index_hits = [h for h in page_index_hits if h.fields.get("category") == "general"]
    elif route_result.route == "special":
        # special 路由且有 PageIndex 樹命中，或問及診所政策/術前術後注意事項時，撈出診所通用備註
        if page_index_hits or any(kw in query for kw in ("術前", "術後", "注意事項", "備註", "規定")):
            if clinic_id is None:
                raise ValueError(f"special 路由查詢診所通用備註需要提供 clinic_id（問句：'{query}'）")
            raw_notes = get_clinic_custom_notes(conn, clinic_id)
            clinic_custom_notes = {
                sec: mask_prices(note) for sec, note in raw_notes.items()
            }

    # 評估是否允許快取短路（營運問句以結構化資訊優先，不短路）
    shortcut_allowed = cache_shortcut and not any(kw in query for kw in _CLINIC_OPS_KEYWORDS)
    clinic_candidates: list = []
    general_candidates: list = []
    shortcut_candidates: list = []

    if shortcut_allowed:
        cand_limit = max(limit, SHORTCUT_CANDIDATE_LIMIT)
        if clinic_id is not None:
            raw_clinic = _search_terms_merged(
                search_faq_cache,
                conn,
                search_terms,
                cand_limit,
                clinic_id=clinic_id,
                category="special",
            )
            clinic_candidates = [h for h in raw_clinic if h.fields.get("clinic_id") == clinic_id]

            raw_gen = _search_terms_merged(
                search_faq_cache,
                conn,
                search_terms,
                cand_limit,
                clinic_id=None,
                category="general",
            )
            general_candidates = [h for h in raw_gen if h.fields.get("clinic_id") is None]
        else:
            raw_sc = _search_terms_merged(
                search_faq_cache,
                conn,
                search_terms,
                cand_limit,
                clinic_id=None,
                category="general" if route_result.route == "general" else None,
            )
            shortcut_candidates = [h for h in raw_sc if h.fields.get("clinic_id") is None]

    hit_lists = [page_index_hits, drug_hits, service_item_hits, faq_hits]
    if shortcut_allowed:
        if clinic_id is not None:
            hit_lists.extend([clinic_candidates, general_candidates])
        else:
            hit_lists.append(shortcut_candidates)

    for hit_list in hit_lists:
        for hit in hit_list:
            for key, value in hit.fields.items():
                if isinstance(value, str):
                    hit.fields[key] = mask_prices(value)

    if shortcut_allowed:
        if clinic_id is not None:
            decision = select_confident_faq_tiered(
                query=query,
                clinic_hits=clinic_candidates,
                general_hits=general_candidates,
                clinic_id=clinic_id,
                stopword_pattern=_STOPWORD_SPLIT_PATTERN,
            )
            if decision.hit is not None:
                return QueryResponse(
                    route=route_result.route,
                    matched_keywords=route_result.matched_keywords,
                    clinic_info=None,
                    clinic_hours=[],
                    page_index_hits=[],
                    drug_hits=[],
                    service_item_hits=[],
                    clinic_custom_notes={},
                    faq_hits=[decision.hit],
                    source="cache",
                    cache_answer=mask_prices(decision.hit.fields["answer"]),
                    cache_eligible=True,
                    data_level=decision.level,
                )
        else:
            legacy_decision = select_confident_faq(
                query=query,
                faq_hits=shortcut_candidates,
                route=route_result.route,
                clinic_id=None,
                stopword_pattern=_STOPWORD_SPLIT_PATTERN,
            )
            if legacy_decision.hit is not None:
                return QueryResponse(
                    route=route_result.route,
                    matched_keywords=route_result.matched_keywords,
                    clinic_info=None,
                    clinic_hours=[],
                    page_index_hits=[],
                    drug_hits=[],
                    service_item_hits=[],
                    clinic_custom_notes={},
                    faq_hits=[legacy_decision.hit],
                    source="cache",
                    cache_answer=mask_prices(legacy_decision.hit.fields["answer"]),
                    cache_eligible=True,
                    data_level="general",
                )

    non_shortcut_level = faq_hit_level(faq_hits[0]) if faq_hits else None
    return QueryResponse(
        route=route_result.route,
        matched_keywords=route_result.matched_keywords,
        clinic_info=clinic_info,
        clinic_hours=clinic_hours,
        page_index_hits=page_index_hits,
        drug_hits=drug_hits,
        service_item_hits=service_item_hits,
        clinic_custom_notes=clinic_custom_notes,
        faq_hits=faq_hits,
        source="pageindex",
        cache_answer=None,
        cache_eligible=shortcut_allowed,
        data_level=non_shortcut_level,
    )

