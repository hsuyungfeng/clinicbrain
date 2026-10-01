"""
Taiwan Clinic Medical PageIndex RAG System - 常見問題主題來源與對應規則模組 (topic_sources)
Phase 09 Nightly Batch & Topic Sources: Task 1

設計原則（見 AGENTS.md 2.8 與 REQUIREMENTS BATCH-04）：
- 批次生成主題來源僅限：
  1. cache_stats 的未命中路由關鍵字聚合計數（miss_keyword 排行）
  2. 人工維護之繁體中文清單檔 (data/batch/faq_seeds.json)
- 嚴格隱私性：絕不讀取、還原或推測使用者輸入問句，僅存取聚合關鍵字與計數。
- 四層合規檢查：載入清單檔時強制執行價格、簡體字、政治立場、保證療效四層驗證。
"""

from dataclasses import dataclass
from datetime import date, timedelta
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Optional, Union

from src.ingestion.convert_chinese import to_traditional
from src.ingestion.generate_faq import validate_single_faq
from src.query.cache_stats import ROUTE_KEYWORD_VOCAB, get_cache_stats

SLUG_REGEX = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class SeedFileError(Exception):
    """種子清單檔案載入或校驗錯誤。"""
    def __init__(self, errors: list[str]):
        super().__init__("；".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class SeedTopic:
    """單一主題定義。"""
    topic_key: str
    title: str
    category: str
    clinic_id: Optional[str]
    keywords: tuple[str, ...]
    always: bool
    tree_doc_id: Optional[str]
    questions: tuple[str, ...]


@dataclass
class SeedFile:
    """種子清單結構。"""
    topics: list[SeedTopic]
    tree_procedure_names: dict[str, str]


@dataclass
class SelectedTopic:
    """經由統計或手動標記選中之待生成主題。"""
    topic: SeedTopic
    reason: str
    hot_count: int


@dataclass
class Selection:
    """選題結果。"""
    topics: list[SelectedTopic]
    unmapped_keywords: list[tuple[str, int]]
    stats_available: bool


def validate_seed_data(data: Any) -> list[str]:
    """
    校驗種子清單資料結構與內容醫療法規合規性。
    回傳錯誤訊息清單，若為空代表校驗合格。
    """
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["清單根節點必須為 JSON 物件 (dict)"]

    if data.get("schema_version") != 1:
        errors.append(f"schema_version 必須為 1，當前為: {data.get('schema_version')}")

    # 檢查 tree_procedure_names
    tree_names = data.get("tree_procedure_names")
    if not isinstance(tree_names, dict):
        errors.append("tree_procedure_names 必須為物件 (dict)")
    else:
        for doc_id, name in tree_names.items():
            if not isinstance(doc_id, str) or not SLUG_REGEX.match(doc_id):
                errors.append(f"tree_procedure_names 鍵 '{doc_id}' 必須為有效 slug 格式")
            if not isinstance(name, str) or not name.strip():
                errors.append(f"tree_procedure_names 鍵 '{doc_id}' 之名稱不可為空")
            elif to_traditional(name) != name:
                errors.append(f"tree_procedure_names 療程名稱 '{name}' 包含簡體字")

    # 檢查 topics
    topics = data.get("topics")
    if not isinstance(topics, list):
        errors.append("topics 必須為列表 (list)")
        return errors

    seen_keys: set[tuple[Optional[str], str]] = set()

    for idx, t in enumerate(topics):
        if not isinstance(t, dict):
            errors.append(f"第 {idx} 筆 topic 必須為物件 (dict)")
            continue

        topic_key = t.get("topic_key")
        title = t.get("title")
        category = t.get("category")
        clinic_id = t.get("clinic_id")
        keywords = t.get("keywords")
        always = t.get("always")
        tree_doc_id = t.get("tree_doc_id")
        questions = t.get("questions")

        # 1. topic_key 檢核
        if not isinstance(topic_key, str) or not SLUG_REGEX.match(topic_key):
            errors.append(f"第 {idx} 筆 topic 之 topic_key '{topic_key}' 必須為有效 slug 格式 (小寫英數與破折號)")

        # 2. title 檢核
        if not isinstance(title, str) or not title.strip():
            errors.append(f"主題 '{topic_key}' 之 title 欄位不可為空")
        elif to_traditional(title) != title:
            errors.append(f"主題 '{topic_key}' 之 title '{title}' 包含簡體字")

        # 3. category 與 clinic_id 檢核
        if category not in ("special", "general"):
            errors.append(f"主題 '{topic_key}' 之 category 必須為 'special' 或 'general'")
        elif category == "special":
            if not clinic_id or not isinstance(clinic_id, str) or not clinic_id.strip():
                errors.append(f"主題 '{topic_key}' category='special' 必須具備非空 clinic_id")
        elif category == "general":
            if clinic_id is not None:
                errors.append(f"主題 '{topic_key}' category='general' 其 clinic_id 必須為 None")

        # 重複 (clinic_id, topic_key) 檢核
        ident = (clinic_id, topic_key)
        if ident in seen_keys:
            errors.append(f"主題重複定義：clinic_id={clinic_id}, topic_key={topic_key}")
        seen_keys.add(ident)

        # 4. keywords 檢核
        if not isinstance(keywords, list):
            errors.append(f"主題 '{topic_key}' 之 keywords 必須為列表")
        else:
            for kw in keywords:
                if kw not in ROUTE_KEYWORD_VOCAB:
                    errors.append(f"主題 '{topic_key}' 之關鍵字 '{kw}' 不在路由詞表 (ROUTE_KEYWORD_VOCAB) 中")

        # 5. tree_doc_id 檢核
        if tree_doc_id is not None:
            if not isinstance(tree_doc_id, str) or not SLUG_REGEX.match(tree_doc_id):
                errors.append(f"主題 '{topic_key}' 之 tree_doc_id '{tree_doc_id}' 必須為有效 slug 格式")

        # 6. always 檢核
        if not isinstance(always, bool):
            errors.append(f"主題 '{topic_key}' 之 always 欄位必須為布林值")

        # 7. questions 檢核
        if not isinstance(questions, list) or len(questions) < 1 or len(questions) > 10:
            errors.append(f"主題 '{topic_key}' 之 questions 數量必須介於 1 到 10 筆之間")
        else:
            seen_q: set[str] = set()
            for q_idx, q in enumerate(questions):
                if not isinstance(q, str) or not q.strip():
                    errors.append(f"主題 '{topic_key}' 第 {q_idx} 題問題為空")
                    continue
                q_clean = q.strip()
                if q_clean in seen_q:
                    errors.append(f"主題 '{topic_key}' 包含重複問題: '{q_clean}'")
                seen_q.add(q_clean)

                # 簡體字檢核
                if to_traditional(q_clean) != q_clean:
                    errors.append(f"主題 '{topic_key}' 問題 '{q_clean}' 包含簡體字")

                # 四層合規檢核（以預設安全答案送驗）
                is_valid, reason = validate_single_faq({"question": q_clean, "answer": "請致電診所確認"})
                if not is_valid:
                    errors.append(f"主題 '{topic_key}' 問題 '{q_clean}' 未通過醫療法規合規檢查: {reason}")

    return errors


def load_seed_file(path: Union[str, Path]) -> SeedFile:
    """自指定路徑載入並校驗種子清單檔案。"""
    p = Path(path)
    if not p.exists():
        raise SeedFileError([f"種子清單檔案不存在: {p}"])

    try:
        content = p.read_text(encoding="utf-8")
        data = json.loads(content)
    except Exception as e:
        raise SeedFileError([f"無法解析種子清單 JSON 檔案: {e}"])

    errors = validate_seed_data(data)
    if errors:
        raise SeedFileError(errors)

    topics: list[SeedTopic] = []
    for t in data["topics"]:
        topics.append(
            SeedTopic(
                topic_key=t["topic_key"],
                title=t["title"],
                category=t["category"],
                clinic_id=t.get("clinic_id"),
                keywords=tuple(t.get("keywords") or []),
                always=bool(t.get("always")),
                tree_doc_id=t.get("tree_doc_id"),
                questions=tuple(t.get("questions") or []),
            )
        )

    return SeedFile(
        topics=topics,
        tree_procedure_names=dict(data.get("tree_procedure_names") or {}),
    )


def select_topics(
    seed: SeedFile,
    conn: sqlite3.Connection,
    *,
    since_days: int = 14,
    min_miss_count: int = 3,
    max_topics: Optional[int] = None,
    today: Optional[date] = None,
) -> Selection:
    """
    依據 cache_stats 聚合未命中統計與手動清單進行主題選題。

    規則：
    1. 僅查詢 cache_stats 之 miss_keyword 聚合，永不讀取問句原文。
    2. 熱門關鍵字（count >= min_miss_count）優先映射入選。
    3. always=True 之主題接續排於熱門主題之後。
    4. 未對應到任何清單主題的熱門關鍵字記入 unmapped_keywords。
    """
    ref_today = today or date.today()
    since_date = (ref_today - timedelta(days=since_days)).isoformat()

    stats_available = True
    top_miss: list[dict[str, Any]] = []

    try:
        stats = get_cache_stats(conn, since_date=since_date, top_n=100)
        top_miss = stats.get("top_miss_keywords", [])
    except Exception:
        stats_available = False

    # 取得達門檻之熱門關鍵字
    hot_keywords: dict[str, int] = {
        item["keyword"]: item["count"]
        for item in top_miss
        if item.get("count", 0) >= min_miss_count
    }

    hot_selected: list[tuple[SeedTopic, str, int, int]] = []
    selected_topic_keys: set[str] = set()

    # 1. 匹配熱門關鍵字主題
    for idx, topic in enumerate(seed.topics):
        overlap = set(topic.keywords) & set(hot_keywords.keys())
        if overlap:
            # 取 count 最大者為 reason 與 hot_count；若 count 相同取 keyword 字典序最小
            best_kw = min(overlap, key=lambda k: (-hot_keywords[k], k))
            best_count = hot_keywords[best_kw]
            hot_selected.append((topic, f"hot_keyword:{best_kw}", best_count, idx))
            selected_topic_keys.add(topic.topic_key)

    # 熱門主題排序：hot_count 降冪，其次檔案順序升冪
    hot_selected.sort(key=lambda x: (-x[2], x[3]))

    # 2. 匹配 always=True 之手動主題
    manual_selected: list[tuple[SeedTopic, str, int, int]] = []
    for idx, topic in enumerate(seed.topics):
        if topic.always and topic.topic_key not in selected_topic_keys:
            manual_selected.append((topic, "manual", 0, idx))
            selected_topic_keys.add(topic.topic_key)

    # 3. 找出未映射的熱門關鍵字
    all_mapped_kws = {kw for t in seed.topics for kw in t.keywords}
    unmapped: list[tuple[str, int]] = [
        (kw, count)
        for kw, count in hot_keywords.items()
        if kw not in all_mapped_kws
    ]
    # 依 count 降冪、keyword 升冪排序
    unmapped.sort(key=lambda x: (-x[1], x[0]))

    # 合併選題
    combined = [
        SelectedTopic(topic=t, reason=r, hot_count=c)
        for t, r, c, _ in (hot_selected + manual_selected)
    ]

    if max_topics is not None:
        combined = combined[:max_topics]

    return Selection(
        topics=combined,
        unmapped_keywords=unmapped,
        stats_available=stats_available,
    )
