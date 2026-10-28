#!/usr/bin/env python3
"""臺灣基層診所 36 項 ICD-10 目錄知識萃取與 pathology_mechanism 升級 CLI (Phase 35-02)。

用法：
  python3 scripts/enrich_icd10_primary_care.py --check              # 僅離線驗證，不寫檔
  python3 scripts/enrich_icd10_primary_care.py                      # 以離線權威知識升級並寫回目錄 JSON
  python3 scripts/enrich_icd10_primary_care.py --use-llm --out <路徑>  # 以本地 LLM 萃取摘要（失敗即退回離線）

安全規範：
- 不連線任何資料庫；只讀寫 JSON 目錄檔。
- 寫檔前整批驗證，任一條目未通過即結束碼 2 且不寫檔。
- 結束碼：0 成功；1 未預期錯誤；2 驗證或參數拒絕。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.visual.icd10_catalog import DEFAULT_CATALOG_PATH, load_icd10_catalog, validate_catalog_entry  # noqa: E402
from src.visual.icd10_enrichment import enrich_entry, enrich_with_llm  # noqa: E402


def _local_llm(prompt: str) -> str:
    """延遲匯入本地 LLM 呼叫（僅 --use-llm 時才會連線 llama-server）。"""
    from src.pageindex.llm_client import local_llm_call

    return local_llm_call(prompt, timeout=420)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="升級 ICD-10 目錄為 pathology_mechanism 並寫入臨床摘要")
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG_PATH), help="來源目錄 JSON")
    parser.add_argument("--out", default=None, help="輸出路徑（預設同來源檔）")
    parser.add_argument("--check", action="store_true", help="僅驗證，不寫檔")
    parser.add_argument("--use-llm", action="store_true", help="以本地 LLM 萃取摘要，失敗即退回離線知識庫")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = Path(args.catalog)
    if not source.exists():
        print(f"❌ 找不到目錄檔：{source}", file=sys.stderr)
        return 2

    entries = load_icd10_catalog(source)
    enriched: list[dict] = []
    sources: dict[str, int] = {}
    try:
        for entry in entries:
            if args.use_llm:
                item, origin = enrich_with_llm(entry, _local_llm)
            else:
                item, origin = enrich_entry(entry), "offline"
            enriched.append(item)
            sources[origin] = sources.get(origin, 0) + 1
    except ValueError as exc:
        print(f"❌ 升級失敗：{exc}", file=sys.stderr)
        return 2

    failures = []
    for item in enriched:
        ok, code = validate_catalog_entry(item)
        if not ok:
            failures.append((item["topic_key"], code))
    if failures:
        for topic, code in failures:
            print(f"❌ 驗證失敗：{topic} -> {code}", file=sys.stderr)
        return 2

    print(f"✅ 驗證通過：{len(enriched)} 筆；來源統計 {sources}")
    if args.check:
        print("（--check：未寫檔）")
        return 0

    out = Path(args.out) if args.out else source
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(enriched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"📝 已寫入：{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
