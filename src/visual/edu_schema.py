"""Phase 53-02: 7 段結構化衛教知識（`edu_json`）Pydantic Schema 與 DB 欄位遷移。"""

from __future__ import annotations

import sqlite3
from typing import List

from pydantic import BaseModel, Field


class EduDefinitionSection(BaseModel):
    summary: str = Field(..., min_length=10, max_length=240)
    anatomy_note: str = Field(..., min_length=6, max_length=180)
    key_point: str = Field(..., min_length=6, max_length=140)


class EduComparisonRow(BaseModel):
    aspect: str = Field(..., min_length=1, max_length=24)
    left_value: str = Field(..., min_length=1, max_length=60)
    right_value: str = Field(..., min_length=1, max_length=60)


class EduComparisonSection(BaseModel):
    left_title: str = Field(..., min_length=2, max_length=24)
    right_title: str = Field(..., min_length=2, max_length=24)
    rows: List[EduComparisonRow] = Field(..., min_length=2, max_length=6)


class EduCausesRisksSection(BaseModel):
    flow_steps: List[str] = Field(..., min_length=3, max_length=5)
    risk_factors: List[str] = Field(..., min_length=3, max_length=8)


class EduComplicationItem(BaseModel):
    name: str = Field(..., min_length=1, max_length=24)
    description: str = Field(..., min_length=2, max_length=80)


class EduSymptomsComplicationsSection(BaseModel):
    symptoms: List[str] = Field(..., min_length=2, max_length=8)
    complications: List[EduComplicationItem] = Field(..., min_length=2, max_length=6)


class EduDiagnosisMethod(BaseModel):
    method: str = Field(..., min_length=1, max_length=32)
    purpose: str = Field(..., min_length=2, max_length=100)


class EduDiagnosisSection(BaseModel):
    methods: List[EduDiagnosisMethod] = Field(..., min_length=2, max_length=5)


class EduPreventionMythSection(BaseModel):
    tips: List[str] = Field(..., min_length=3, max_length=6)
    myth_buster: str = Field(..., min_length=8, max_length=220)


class EduRedFlagsTakeawaySection(BaseModel):
    red_flags: List[str] = Field(..., min_length=2, max_length=5)
    takeaway: str = Field(..., min_length=8, max_length=100)


class EduAnimationHints(BaseModel):
    s1_trigger_label: str = Field(..., min_length=2, max_length=24)
    s1_lesion_label: str = Field(..., min_length=2, max_length=24)
    s1_defense_label: str = Field(..., min_length=2, max_length=24)
    s1_step_labels: List[str] = Field(..., min_length=3, max_length=3)
    s1_caption: str = Field(..., min_length=16, max_length=180)
    s2_left_title: str = Field(..., min_length=2, max_length=24)
    s2_left_note: str = Field(..., min_length=2, max_length=32)
    s2_right_title: str = Field(..., min_length=2, max_length=24)
    s2_right_note: str = Field(..., min_length=2, max_length=32)
    s2_caption: str = Field(..., min_length=16, max_length=180)
    s3_care_items: List[str] = Field(..., min_length=3, max_length=4)
    s3_red_flags: List[str] = Field(..., min_length=2, max_length=4)
    s3_myth_note: str = Field(..., min_length=2, max_length=48)
    s3_takeaway: str = Field(..., min_length=6, max_length=60)
    s3_caption: str = Field(..., min_length=16, max_length=180)


class EduContent(BaseModel):
    topic_key: str
    title: str
    definition: EduDefinitionSection
    comparison: EduComparisonSection
    causes_risks: EduCausesRisksSection
    symptoms_complications: EduSymptomsComplicationsSection
    diagnosis: EduDiagnosisSection
    prevention_myth: EduPreventionMythSection
    red_flags_takeaway: EduRedFlagsTakeawaySection
    animation_hints: EduAnimationHints


def ensure_edu_columns(conn: sqlite3.Connection) -> None:
    """冪等為 `visual_assets` 新增 `edu_json` 與 `edu_updated_at` 欄位。"""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(visual_assets)").fetchall()}
    if "edu_json" not in cols:
        conn.execute("ALTER TABLE visual_assets ADD COLUMN edu_json TEXT")
    if "edu_updated_at" not in cols:
        conn.execute("ALTER TABLE visual_assets ADD COLUMN edu_updated_at TEXT")
    conn.commit()
