"""一般醫療諮詢之紅旗症狀偵測器。

本模組落實 GENERAL-02 之安全短路機制：
- 保守策略：任何潛在急重症或高風險徵候優先攔截，不呼叫 LLM、不執行知識庫檢索。
- 階層優先：emergency（立即撥打 119/急診）優先於 urgent（當日儘速就醫）。
- 雙層正規化：light_normalize 保留小數點供體溫比對；normalize_for_match 消除標點干擾。
- 隱私保護：本模組為純函式，不引入 logging、不碰資料庫、回傳之 RedFlagMatch 不含問句原文。
"""

from dataclasses import dataclass
import re
from typing import Literal
import unicodedata

from src.ingestion.convert_chinese import to_traditional


@dataclass(frozen=True)
class RedFlagRule:
    """紅旗規則定義。"""

    rule_id: str
    level: Literal["emergency", "urgent"]
    label: str
    patterns: tuple[str, ...]
    raw_patterns: tuple[str, ...] = ()
    strip_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class RedFlagMatch:
    """紅旗命中結果。刻意不含命中字串或原始問句以保障隱私。"""

    level: str
    rule_id: str
    label: str


# --- E08 巨集定義 ---
_E08_CTX = r"(注射|打完|打了|填充|玻尿酸|水光|微整|針)"
_E08_STRONG = r"(發黑|發紫|蒼白|壞死|潰爛|花斑|瘀黑|網狀斑)"
_E08_WEAK = r"((突然|馬上|立刻|一塊|一片|局部|斑駁).{0,4}(變白|發白)|(變白|發白).{0,3}(一塊|一片|斑駁))"
_E08_VIS = r"((眼睛|視力|眼).{0,6}(看不到|看不見|看不清|突然模糊|模糊|失明|變黑|黑掉))"

RED_FLAG_RULES: tuple[RedFlagRule, ...] = (
    # E01 cardiac
    RedFlagRule(
        rule_id="E01",
        level="emergency",
        label="胸痛/心臟急症",
        strip_terms=(
            "隆胸",
            "豐胸",
            "墊胸",
            "縮胸",
            "隆乳",
            "胸部整形",
            "胸部手術",
            "乳房手術",
            "乳房整形",
            "胸部填充",
        ),
        patterns=(
            r"胸.{0,2}(痛|悶|壓迫|緊縮)",
            r"胸.{0,6}(壓住|壓著|壓石頭|重物)",
            r"心絞痛",
            r"心肌梗塞",
            r"心臟病發",
            r"心口.{0,2}(痛|悶)",
            r"心臟.{0,3}(痛|絞|壓|不舒服)",
            r"心悸",
            r"心跳.{0,3}(很快|過快|不規則|亂|停)",
            r"chestpain",
            r"heartattack",
        ),
    ),
    # E02 breathing
    RedFlagRule(
        rule_id="E02",
        level="emergency",
        label="呼吸困難/氣道梗塞",
        patterns=(
            r"呼吸.{0,3}(困難|不順|急促|窘迫|停止)",
            r"(喘|吸|透|上)不.{0,2}氣",
            r"吸不.{0,2}空氣",
            r"喘.{0,2}不上氣",
            r"上氣不接下氣",
            r"(無法|不能|沒辦法|不太能)呼吸",
            r"窒息",
            r"噎住",
            r"噎到",
            r"嗆到",
            r"氣喘發作",
            r"喘不過來",
            r"喉嚨.{0,2}卡住",
            r"卡住.{0,2}喉嚨",
            r"卡在喉嚨",
            r"cantbreathe",
            r"cannotbreathe",
            r"unabletobreathe",
            r"shortnessofbreath",
            r"difficultybreathing",
        ),
    ),
    # E03 consciousness
    RedFlagRule(
        rule_id="E03",
        level="emergency",
        label="意識不清/抽搐",
        patterns=(
            r"意識.{0,3}(不清|模糊|喪失|不明)",
            r"昏迷",
            r"昏倒",
            r"暈倒",
            r"暈過去",
            r"暈厥",
            r"昏厥",
            r"昏睡",
            r"失去意識",
            r"不省人事",
            r"叫不醒",
            r"叫不起來",
            r"抽搐",
            r"癲癇發作",
            r"(神智|神志).{0,2}(不清|恍惚)",
            r"(發燒|小孩|孩子|寶寶|嬰兒|幼兒|小朋友).{0,6}抽筋",
        ),
    ),
    # E04 bleeding
    RedFlagRule(
        rule_id="E04",
        level="emergency",
        label="大量出血",
        patterns=(
            r"大量.{0,2}(出血|流血)",
            r"(一直|不斷|持續).{0,2}(流血|出血)",
            r"流.{0,2}很多血",
            r"血.{0,2}(一直|不停|不斷).{0,1}流",
            r"血流.{0,1}(不停|不止|不斷)",
            r"(血|出血|流血).{0,2}(不止|不停|不斷)",
            r"止不住.{0,2}血",
            r"血.{0,3}止不住",
            r"噴血",
            r"吐血",
            r"嘔血",
            r"咳血",
            r"咳出.{0,3}血",
            r"咳.{0,2}大量.{0,2}血",
            r"咳.{0,2}很多.{0,2}血",
        ),
    ),
    # E05 anaphylaxis
    RedFlagRule(
        rule_id="E05",
        level="emergency",
        label="過敏性休克/喉頭水腫",
        patterns=(
            r"過敏.{0,3}休克",
            r"休克",
            r"anaphyla",
            r"舌頭.{0,3}(腫|脹)",
            r"喉頭.{0,2}(水腫|腫|緊)",
            r"喉嚨.{0,3}(腫|緊|收縮|閉|脹).{0,10}(呼吸|喘|吞|吸不|說不出|發不出聲)",
            r"(呼吸|喘|吞嚥|吞不下).{0,10}喉嚨.{0,3}(腫|緊|收縮|閉|脹)",
            r"(打完|打了|注射|施打|過敏|服藥|吃藥|用藥).{0,8}喉嚨.{0,3}(腫|緊|收縮|閉|脹)",
            r"(嘴唇|臉|眼皮|舌頭|喉嚨).{0,3}(腫|脹).{0,10}(呼吸|喘|吞|頭暈)",
            r"全身.{0,4}(蕁麻疹|起疹|紅疹).{0,10}(喘|呼吸|頭暈|昏)",
        ),
    ),
    # E06 stroke
    RedFlagRule(
        rule_id="E06",
        level="emergency",
        label="急性中風徵候",
        patterns=(
            r"中風",
            r"stroke",
            r"半身不遂",
            r"(手腳|四肢|手臂|腿).{0,3}麻痺",
            r"麻痺.{0,3}無力",
            r"手腳.{0,2}(無力|沒力)",
            r"(單側|半邊|一側|一邊|左邊|右邊|左側|右側).{0,3}(手|腳|臉|身體)?.{0,3}(無力|沒力|麻|癱|不能動|動不了)",
            r"口齒不清",
            r"(說話|講話).{0,2}(不清|含糊)",
            r"突然.{0,4}(看不見|失明)",
            r"(突然|忽然|單側|一邊|半邊|左邊|右邊|說話|講話|口齒).{0,8}(臉|嘴|口).{0,2}歪",
            r"(臉|嘴|口).{0,2}歪.{0,8}(說話|講話|口齒|突然|單側|一邊|無力|流口水)",
        ),
    ),
    # E07 poisoning
    RedFlagRule(
        rule_id="E07",
        level="emergency",
        label="中毒/誤食/藥物過量",
        patterns=(
            r"食物中毒|藥物中毒|一氧化碳中毒|酒精中毒|瓦斯中毒|農藥中毒",
            r"(服藥|藥物|藥).{0,1}過量",
            r"overdose",
            r"誤(服|食|飲)",
            r"吞.{0,3}整瓶",
            r"吞.{0,2}電池",
            r"吞.{0,2}異物",
            r"(喝|吞|吃).{0,2}農藥",
        ),
    ),
    # E08 filler_occlusion
    RedFlagRule(
        rule_id="E08",
        level="emergency",
        label="填充劑血管阻塞徵兆",
        patterns=(
            f"{_E08_CTX}.{{0,20}}{_E08_STRONG}",
            f"{_E08_STRONG}.{{0,20}}{_E08_CTX}",
            f"{_E08_CTX}.{{0,20}}{_E08_WEAK}",
            f"{_E08_WEAK}.{{0,20}}{_E08_CTX}",
            f"{_E08_CTX}.{{0,20}}{_E08_VIS}",
            f"{_E08_VIS}.{{0,20}}{_E08_CTX}",
        ),
    ),
    # U01 severe_pain
    RedFlagRule(
        rule_id="U01",
        level="urgent",
        label="劇烈疼痛",
        patterns=(
            r"劇烈.{0,4}痛",
            r"劇痛",
            r"痛到.{0,6}(受不了|睡不著|無法|哭|冒冷汗|昏)",
            r"痛得.{0,4}(受不了|不得了|要命|厲害)",
            r"難以忍受",
            r"受不了.{0,3}痛",
            r"痛.{0,2}受不了",
            r"痛死",
            r"越來越痛",
            r"愈來愈痛",
            r"止痛藥.{0,4}(沒用|無效|壓不住)",
        ),
    ),
    # U02 high_fever
    RedFlagRule(
        rule_id="U02",
        level="urgent",
        label="高燒/持續發燒/幼兒發燒",
        patterns=(
            r"高燒",
            r"燒.{0,3}不退",
            r"退不了燒",
            r"(持續|反覆|一直).{0,2}(發燒|燒)",
            r"(發燒|發熱|燒了|燒).{0,4}(不停|三天|3天|四天|五天|一週|一周|一星期|七天|一個禮拜|好幾天|幾天|多天)",
            r"(嬰兒|寶寶|新生兒|幼兒|小孩|孩子|小朋友).{0,6}(發燒|發熱)",
        ),
        raw_patterns=(
            r"(體溫|發燒|燒到|燒至).{0,2}(?<![\d.])(39|40|41)(\.\d)?(?!\d)",
            r"(?<![\d.])(39|40|41)\.\d度",
        ),
    ),
    # U03 wound_infection
    RedFlagRule(
        rule_id="U03",
        level="urgent",
        label="傷口感染/化膿",
        patterns=(
            r"化膿",
            r"流膿",
            r"膿液",
            r"膿瘍",
            r"冒膿",
            r"滲膿",
            r"傷口.{0,4}有膿",
            r"傷口.{0,8}(紅腫|發炎|感染|惡臭|臭味)",
            r"紅腫.{0,4}熱",
            r"紅腫熱痛",
            r"蜂窩性?組織炎",
            r"敗血",
            r"傷口.{0,4}(裂開|崩開)",
            r"(術後|傷口|開刀|手術).{0,12}(發燒|發熱)",
            r"(發燒|發熱).{0,12}(術後|傷口|開刀|手術)",
        ),
    ),
    # U04 other_urgent
    RedFlagRule(
        rule_id="U04",
        level="urgent",
        label="其他急症徵候",
        patterns=(
            r"黑便",
            r"血便",
            r"便血",
            r"尿血",
            r"血尿",
            r"視力.{0,4}(模糊|變差|喪失|看不清)",
            r"突然.{0,4}(耳聾|聽不見)",
            r"(持續|一直|不斷|反覆).{0,2}嘔吐",
            r"吐個不停|吐不停|嘔吐不止",
            r"(懷孕|孕).{0,8}(出血|流血)",
            r"嘴唇.{0,2}(腫|脹)",
            r"臉.{0,2}腫起來",
        ),
    ),
    # U05 acute_abdomen
    RedFlagRule(
        rule_id="U05",
        level="urgent",
        label="急腹症/劇烈腹痛",
        patterns=(
            r"(肚子|腹).{0,2}(好痛|很痛|超痛|劇痛|絞痛|痛到)",
            r"右下腹.{0,2}痛",
            r"腹痛如絞",
            r"急腹症",
            r"肚子.{0,2}痛.{0,3}(嘔吐|發燒|發硬|變硬)",
        ),
    ),
)

# 模組載入時預先編譯所有正則表達式
_COMPILED_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    rule.rule_id: tuple(re.compile(p) for p in rule.patterns)
    for rule in RED_FLAG_RULES
}

_COMPILED_RAW_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    rule.rule_id: tuple(re.compile(p) for p in rule.raw_patterns)
    for rule in RED_FLAG_RULES
}


def light_normalize(text: str) -> str:
    """輕度正規化。

    流程：NFKC -> lower() -> to_traditional() -> 「疼」替換為「痛」-> 移除所有空白。保留標點與小數點。
    空值回傳空字串。
    """
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = t.lower()
    t = to_traditional(t)
    t = t.replace("疼", "痛")
    t = re.sub(r"\s+", "", t)
    return t


def normalize_for_match(text: str) -> str:
    """完全正規化。

    流程：對 light_normalize 結果去除所有非字詞字元（含所有標點、小數點、撇號等）。
    空值回傳空字串。
    """
    light = light_normalize(text)
    if not light:
        return ""
    return re.sub(r"[\W_]+", "", light)


def detect_red_flag(text: str) -> RedFlagMatch | None:
    """偵測問句中之紅旗急重症徵候。

    純函式：不存取資料庫、不呼叫 LLM、不寫入日誌、不回傳問句片段。

    Args:
        text: 使用者問句。

    Returns:
        若命中則回傳 RedFlagMatch(level, rule_id, label)；未命中則回傳 None。
        emergency 優先於 urgent；若多個 urgent 命中則回傳優先序最高（第一個）者。
    """
    if not text or not text.strip():
        return None

    light = light_normalize(text)
    norm = normalize_for_match(text)
    if not norm and not light:
        return None

    first_urgent: RedFlagMatch | None = None

    for rule in RED_FLAG_RULES:
        # 先從 norm 移除該規則專屬的 strip_terms
        m = norm
        if rule.strip_terms:
            for term in rule.strip_terms:
                m = m.replace(term, "")

        hit = False
        compiled_patterns = _COMPILED_PATTERNS.get(rule.rule_id, ())
        for cp in compiled_patterns:
            if cp.search(m):
                hit = True
                break

        if not hit and rule.raw_patterns:
            compiled_raw = _COMPILED_RAW_PATTERNS.get(rule.rule_id, ())
            for cp in compiled_raw:
                if cp.search(light):
                    hit = True
                    break

        if hit:
            match = RedFlagMatch(
                level=rule.level, rule_id=rule.rule_id, label=rule.label
            )
            if rule.level == "emergency":
                return match
            if first_urgent is None:
                first_urgent = match

    return first_urgent
