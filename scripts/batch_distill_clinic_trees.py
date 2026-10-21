#!/usr/bin/env python3
"""
Taiwan Clinic Medical PageIndex RAG System - 門診核心手術與處置批次提煉模組
由 clinic.db 的 faq_cache 提煉 8 大核心外科手術臨床推理樹，並生成對應的 3 幕動畫草稿。

目標療程：
1. epidermal-cyst-excision: 未感染粉瘤微創旋轉吸引切除手術
2. paronychia-matrixectomy: 甲溝炎嵌甲甲床重整手術
3. bromhidrosis-rotary-cutter: 微創螺旋刀頂漿腺狐臭手術
4. endolift-laser: Endolift 光纖內提拉手術
5. microneedle-rf: 黃金微針電波拉提
6. scar-subcision: 疤痕與蟹足腫光纖皮下切割治療
7. lipoma-aspiration: 微創脂肪瘤抽吸切除手術
8. plasma-pen-electrocautery: 等離子筆與電灼贅疣治療
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 確保 opencc-python-reimplemented 可用
try:
    import opencc  # noqa: F401
except ImportError:
    uv_opencc = Path("/home/hsu/.cache/uv/archive-v0/hD69btIoBk4Lc2HKmEOvw")
    if uv_opencc.exists():
        sys.path.insert(0, str(uv_opencc))

from src.pageindex.db_writer import upsert_trees
from src.visual.ir import validate_ir
from src.visual.writer import has_visual_assets_table, upsert_assets

CLINIC_ID = "3503190424"
PROD_DB_PATH = PROJECT_ROOT / "clinic.db"

# 8 大核心手術與微創處置 PageIndex 臨床推理樹規格
DISTILLED_TREES: list[dict[str, Any]] = [
    {
        "doc_id": "epidermal-cyst-excision",
        "clinic_id": CLINIC_ID,
        "title": "未感染粉瘤微創旋轉吸引切除手術",
        "category": "special",
        "pre_op": (
            "術前須知：1. 評估粉瘤是否處於未發炎狀態，若急性紅腫化膿感染需先抗生素治療或切開排膿 "
            "2. 凝血功能異常或服用抗凝血藥品需先告知醫師 3. 術前請清潔患部皮膚，切勿自行大力擠壓以防囊壁破裂造成組織沾黏 "
            "4. 局部毛髮可視手術部位由護理人員適度剃除"
        ),
        "procedure": (
            "手術處置步驟：1. 患部局部浸潤麻醉並標記數毫米極微小切口 2. 微創旋轉吸引切除刀進入囊腔，以負壓旋轉吸引切除粉瘤角質內容物 "
            "3. 精細輔助剝離並完整清除表皮樣囊腫囊壁以防復發，微創對齊傷口縫合。過程約二十分鐘至半小時。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 傷口覆蓋紗布加壓包紮預防皮下血腫，前兩天保持乾燥清潔 2. 依醫囑定時更換無菌敷料並塗抹抗生素藥膏 "
            "3. 數天內避免劇烈運動、提重物與碰撞傷口 4. 傷口周圍若有輕微瘀青腫脹屬正常修復反應，若突發劇烈疼痛或異常滲血需即刻回診"
        ),
        "maintenance": (
            "長期維持與衛教：1. 術後約一週依醫囑回診檢查傷口癒合狀況與拆線 2. 拆線後可配合除疤凝膠或矽膠貼片照顧微小傷口 "
            "3. 加強防曬預防局部色素沉澱 4. 平時注意皮膚毛孔清潔，避免局部過度摩擦或油脂角質堆積 5. 定期自我觸診觀察，如有異常硬塊隨時預約門診評估"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "未感染粉瘤微創旋轉吸引切除手術術前確認非急性發炎期、告知用藥史。手術經極小微創切口，以負壓旋轉刀清除角質內容並完整剝離囊壁。"
            "術後加壓包紮防血腫、保持乾燥清潔。約一週回診評估，配合防曬與除疤護理降低復發。"
        ),
    },
    {
        "doc_id": "paronychia-matrixectomy",
        "clinic_id": CLINIC_ID,
        "title": "甲溝炎嵌甲甲床重整手術",
        "category": "special",
        "pre_op": (
            "術前須知：1. 評估嵌甲嚴重度與肉芽組織增生狀況，若有嚴重紅腫化膿感染需配合口服抗生素控制 "
            "2. 糖尿病或周邊血管疾病患者需特別告知以評估末梢循環 3. 手術當天穿著露趾拖鞋或寬鬆鞋襪，避免包鞋壓迫 "
            "4. 患趾清潔乾淨，術前切勿自行過度深挖或強行拔除趾甲邊角"
        ),
        "procedure": (
            "手術處置步驟：1. 患趾趾神經阻斷局部麻醉並使用指根止血帶維持清晰視野 2. 垂直縱向剪除嵌入側邊甲肉的病灶甲板並細緻修除發炎增生肉芽 "
            "3. 以化學燒灼或微創電燒破壞病灶側的甲母質生長組織，整復甲床後加壓止血包紮。過程約十五至二十五分鐘。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 術後當日患肢盡量抬高以減輕腫脹搏動感 2. 傷口敷料保持乾燥清潔，前兩天按時換藥與塗抹消炎藥膏 "
            "3. 遵從醫囑按時服用消炎止痛藥物 4. 避免長時間站立行走與劇烈運動，外出請穿著露趾拖鞋防範擠壓摩擦"
        ),
        "maintenance": (
            "長期維持與衛教：1. 數天至一週後回診檢查傷口癒合與肉芽消退狀況 2. 養成正確指甲修剪習慣，保持水平直剪且邊緣不可修剪過深過圓 "
            "3. 避免長期穿著過緊、過窄或高跟鞋款 4. 保持足部乾爽衛生預防黴菌或細菌滋生 5. 若有微度紅腫及早回診評估，維護指甲正常生長軌道"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "甲溝炎嵌甲甲床重整手術術前評估指甲嵌入與感染程度、著寬鬆鞋襪。手術採神經阻斷麻醉，側切嵌入甲板、修除肉芽並破壞病灶側甲母質。"
            "術後抬高患趾減輕腫脹、保持乾燥換藥。回診追蹤癒合，建立正確水平修剪指甲習慣防復發。"
        ),
    },
    {
        "doc_id": "bromhidrosis-rotary-cutter",
        "clinic_id": CLINIC_ID,
        "title": "微創螺旋刀頂漿腺狐臭手術",
        "category": "special",
        "pre_op": (
            "術前須知：1. 術前一週停止使用止汗劑、體香劑及刮除腋毛，避免刺激毛囊發炎 2. 停止服用阿斯匹靈、抗凝血劑或活血補品 "
            "3. 確認腋下皮膚無急性毛囊炎或濕疹感染 4. 手術當天穿著前開襟寬鬆上衣，方便術後手臂包紮穿脫 5. 徹底清洗身體維持乾淨衛生"
        ),
        "procedure": (
            "手術處置步驟：1. 腋下局部注射腫脹麻醉液充分分離組織層並止血 2. 於腋下自然皮褶處開設約半公分微創切口，引入電動迴轉式螺旋刀 "
            "3. 旋轉刮除並以負壓抽吸真皮深層之頂漿腺組織，確認皮瓣厚度後進行微創縫合與紗布壓迫固定。過程約一小時。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 腋下以紗布縫合加壓固定數天，嚴禁自行拆除敷料以防皮下積血 2. 手臂嚴禁劇烈抬高、提重物、開車或抱小孩 "
            "3. 身體擦澡為主，保持胸部與腋下包紮區域絕對乾燥清潔 4. 遵從醫囑服用止痛消炎與抗生素藥物，如發燒或敷料嚴重滲血需及時回診"
        ),
        "maintenance": (
            "長期維持與衛教：1. 依醫囑預約回診拆除固定紗布球與傷口縫線 2. 拆線後可配合醫師指導進行漸進式手臂伸展復健 "
            "3. 術後一個月內避免劇烈流汗運動、三溫暖或溫泉 4. 傷口可使用防曬與除疤凝膠照護 5. 若皮下觸摸有暫時性緊繃硬塊屬修復期纖維化，可配合輕度按摩逐漸軟化"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "微創螺旋刀頂漿腺狐臭手術術前停用止汗劑、告知用藥史並穿前扣寬鬆衣物。手術採腫脹麻醉，經小切口以電動螺旋刀刮除抽吸頂漿腺。"
            "術後紗布加壓固定防血腫、手臂避免抬高拉扯。依醫囑回診拆線，配合抗疤與溫和伸展照護。"
        ),
    },
    {
        "doc_id": "endolift-laser",
        "clinic_id": CLINIC_ID,
        "title": "Endolift 光纖內提拉手術",
        "category": "special",
        "pre_op": (
            "術前須知：1. 評估面部或頸部軟組織鬆弛、雙下巴及脂肪分佈 2. 術前兩週停用阿斯匹靈、維他命E及活血中藥 "
            "3. 施作區域若有微整填充物或皮膚感染需先行告知醫師 4. 手術當日請素顏洗淨臉部，卸除所有金屬飾品 5. 充分與醫師溝通治療期待與拉提緊實範圍"
        ),
        "procedure": (
            "手術處置步驟：1. 治療區域清潔消毒並施作微量局部浸潤麻醉 2. 使用極微細如髮絲之光纖進入皮下淺筋膜層與脂肪層 "
            "3. 發射微米雷射能量產生選擇性光熱作用，溫和融解局部脂肪並刺激深層膠原與彈力纖維緊縮。過程約四十分鐘至一小時。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 術後微孔針眼塗抹抗生素藥膏並保持乾燥 2. 局部若有微腫脹、輕度泛紅或微瘀青，可依指示間歇冰敷舒緩 "
            "3. 前三天洗臉時水溫宜微溫，避免大力搓揉治療區域 4. 當週內避免三溫暖、蒸氣室、烤箱及劇烈排汗運動 5. 外出加強防曬防範色素沉澱"
        ),
        "maintenance": (
            "長期維持與衛教：1. 膠原重組與深層緊實效果於術後一至三個月持續漸進顯現 2. 術後一個月內避免深層面部推拿按摩以保護修復中組織 "
            "3. 日常加強高效防曬與皮膚保濕屏障修護 4. 維持穩定體重與規律生活作息延長維持時間 5. 建議三至六個月後回診追蹤，評估整體緊實輪廓"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "Endolift 光纖內提拉手術術前評估鬆弛狀態、停用抗凝血成分並素顏清潔。手術採局部麻醉，髮絲細微光纖進入皮下層，發射雷射熱能融脂並緊緻筋膜。"
            "術後微孔保持乾燥、間歇冰敷消腫並加強防曬。膠原重組於數月內漸進展現。"
        ),
    },
    {
        "doc_id": "microneedle-rf",
        "clinic_id": CLINIC_ID,
        "title": "黃金微針電波拉提",
        "category": "special",
        "pre_op": (
            "術前須知：1. 術前一至兩週停止使用A酸、高濃度果酸及任何去角質產品 2. 若有心律調節器、懷孕、蟹足腫體質或面部急性發炎膿皰需告知醫師 "
            "3. 術前一週避免過度曝曬日光 4. 術前徹底卸妝清潔，均勻敷上表面麻醉藥膏以減輕刺痛感 5. 評估毛孔粗大、凹洞痘疤及鬆弛緊緻需求"
        ),
        "procedure": (
            "療程步驟：1. 卸除麻醉膏並全臉嚴格消毒 2. 醫師根據治療區域皮厚度設定絕緣微針穿透深度與電波能量參數 "
            "3. 微針矩陣快速精準穿入真皮層，於針尖釋放立體雙極電波熱能，表皮不累積過量熱能。過程約半小時至四十五分鐘。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 術後塗抹舒緩保濕精華並配合醫療級冷敷鎮靜微熱感 2. 治療部位可能有輕微泛紅、微小出血點或微腫，通常於數小時至兩天內減退 "
            "3. 當天洗臉以生理食鹽水或無菌水輕拭，二十四小時後可正常洗臉 4. 兩至三天內避免化妝、避免使用美白及酸類刺激性保養品 5. 微細結痂形成時切忌手摳抓"
        ),
        "maintenance": (
            "長期維持與衛教：1. 術後加強物理性防曬（帽子、口罩、遮陽傘）與溫和高係數防曬乳 2. 密集補水保濕以加速皮膚修復與膠原代謝 "
            "3. 膠原蛋白新生與毛孔緊實於療程後一個月逐漸顯著 4. 依膚況與醫師建議，可間隔四至六週進行階段性複合保養 5. 維持作息正常、充足睡眠有助延長膚質細緻維持度"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "黃金微針電波拉提術前停用A酸果酸、避開發炎傷口與日曬。療程採絕緣微針深入真皮釋放立體電波熱能，保護表皮同時刺激膠原新生。"
            "術後冷敷鎮靜、三天避免刺激性保養與化妝。加強保濕防曬，建議四至六週階段性保養。"
        ),
    },
    {
        "doc_id": "scar-subcision",
        "clinic_id": CLINIC_ID,
        "title": "疤痕與蟹足腫光纖皮下切割治療",
        "category": "special",
        "pre_op": (
            "術前須知：1. 評估疤痕形態（凹陷型滾輪痘疤、纖維攣縮疤或肥厚增生型蟹足腫） 2. 疤痕區域若有活動性發炎或化膿痘痘需先治療受控 "
            "3. 停止服用抗凝血劑、阿斯匹靈及活血健康食品 4. 蟹足腫體質需充分理解疤痕修復為多次多階段綜合治療 5. 術前清潔患處皮膚，勿使用刺激性藥劑"
        ),
        "procedure": (
            "治療處置步驟：1. 局部病灶周圍浸潤微量麻醉藥物以確保處置舒適 2. 導入微型皮下針刀或光纖探針至疤痕下方之深層纖維沾黏組織層 "
            "3. 扇形水平精密切割切斷牽引皮膚向下凹陷的攣縮纖維束，並配合光熱刺激或病灶微量注射調控纖維新生。過程約二十分鐘至半小時。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 術後局部無菌紗布適度按壓止血，避免深層形成大血腫 2. 二十四小時內微孔針眼保持乾燥清潔，可適度冷敷舒緩紅腫 "
            "3. 遵從醫囑塗抹抗菌修護藥膏，避免用手大力揉搓治療部位 4. 暫停劇烈運動及飲酒，外出加強物理遮蔽防曬避免色素沉澱 5. 若有異常腫痛或大範圍皮下瘀青隨時聯繫診所"
        ),
        "maintenance": (
            "長期維持與衛教：1. 視疤痕種類配合醫師建議使用除疤矽膠凝膠或矽膠貼片維持平整 2. 嚴格做好防曬保護以防黑色素沉澱 "
            "3. 凹陷釋放後組織膠原回彈與充填修塑需數週時間 4. 蟹足腫患者需遵醫囑定期回診追蹤，評估是否需要輔助低劑量局部注射 5. 多階段治療需耐心配合醫師階段性療程規劃"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "疤痕與蟹足腫光纖皮下切割治療術前評估疤痕攣縮形態與體質。治療採局部麻醉，以微型光纖鈍針於皮下扇形切斷牽引沾黏之纖維束，釋放表面皮膚張力。"
            "術後按壓止血、保持針孔清潔防曬。配合矽膠抗疤護理，定期回診階段性追蹤。"
        ),
    },
    {
        "doc_id": "lipoma-aspiration",
        "clinic_id": CLINIC_ID,
        "title": "微創脂肪瘤抽吸切除手術",
        "category": "special",
        "pre_op": (
            "術前須知：1. 超音波或臨床觸診確診為良性脂肪瘤，明確腫塊大小、深淺位置及與筋膜邊界 2. 凝血功能異常或長期服用抗凝血用藥需提前告知醫師 "
            "3. 確認腫塊周邊無急性蜂窩性組織炎或皮膚破潰 4. 術前清潔患處皮膚 5. 了解微創抽吸輔助切除旨在減小手術傷口疤痕"
        ),
        "procedure": (
            "手術處置步驟：1. 患部周圍注入適量腫脹麻醉液達到良好止痛與血管收縮效果 2. 於隱蔽皮紋切開數毫米微孔，插入微創專用鈍頭抽吸套管 "
            "3. 負壓分層抽吸均勻碎化之脂肪瘤塊，隨後細緻剝離並完整取出周邊纖維包膜以防復發，微創對齊傷口閉合。過程約二十分鐘至四十分鐘。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 術後局部以紗布或彈性繃帶適度加壓包紮，預防空腔血腫及血清腫 2. 傷口敷料保持清潔乾燥，前兩至三天避免碰水 "
            "3. 依醫囑按時換藥與服用預防性消炎止痛藥物 4. 數天內避免提重物、患部過度牽拉或劇烈衝擊 5. 觀察傷口滲液狀況，若滲血較多或突發異常脹痛需及時回診"
        ),
        "maintenance": (
            "長期維持與衛教：1. 術後約一週依醫囑回診檢查傷口癒合狀況與評估拆線 2. 視部位需要可穿戴彈性壓迫護具數週協助空腔緊密貼合 "
            "3. 傷口癒合後可配合除疤矽膠藥膏與防曬護理 4. 術後空腔可能會有短暫輕度皮下硬感，數月內會隨組織重塑逐漸軟化平復 5. 平時定期自我檢查，若有任何新發腫塊隨時預約門診"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "微創脂肪瘤抽吸切除手術術前經超音波確認腫塊邊界與位置。手術採局部腫脹麻醉，經數毫米微孔以鈍頭套管負壓抽吸瘤體，並剝離取出纖維包膜防止復發。"
            "術後局部加壓包紮預防積液與血腫。約一週回診評估，配合除疤護理。"
        ),
    },
    {
        "doc_id": "plasma-pen-electrocautery",
        "clinic_id": CLINIC_ID,
        "title": "等離子筆與電灼贅疣治療",
        "category": "special",
        "pre_op": (
            "術前須知：1. 由專科醫師當面檢查並確診為良性皮贅、肉芽、扁平疣或良性痣（排除惡性病變） 2. 裝有心臟節律器者需特別告知醫師以評估是否適合電灼 "
            "3. 患部若有急性濕疹、皮炎或未癒合傷口需先治療 4. 術前患部徹底清潔消毒，均勻敷上表面麻醉藥膏以減輕微熱刺痛感 5. 了解表皮微創結痂為正常修復過程"
        ),
        "procedure": (
            "處置步驟：1. 清潔消毒患部並擦除麻醉藥膏 2. 等離子弧光微放電或細微電灼針尖對準贅疣肉芽基底部 "
            "3. 瞬間微熱精準氣化微縮凸起病灶組織，同時微凝固微血管形成微創乾燥保護性微焦痂。過程約十分鐘至二十分鐘。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 治療點可能出現微紅與微小乾燥微痂，保持患部乾爽清潔 2. 當天避免用過熱熱水沖洗患部，洗臉洗澡後以乾淨毛巾輕壓吸乾 "
            "3. 依醫囑薄塗消炎抗生素藥膏數天 4. 結痂形成期間嚴禁以手摳抓或強行剝除，避免引發發炎或色素沉澱 5. 出門務必加強防曬防範日曬反黑"
        ),
        "maintenance": (
            "長期維持與衛教：1. 微小焦痂通常於一至兩週內自然脫落，呈現微粉紅新皮 2. 脫痂後新生皮膚較嬌嫩，需持續加強物理防曬與日常保濕 "
            "3. 避免使用強效美白、酒精或刺激性磨砂去角質用品 4. 平時注意皮膚日常衛生，避免長期過度摩擦領口或配戴飾品 5. 若有新贅疣肉芽長出可隨時預約門診評估處置"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "等離子筆與電灼贅疣治療術前由醫師當面確診良性表皮病灶並敷麻。處置以微小等離子弧光或電灼針瞬間氣化贅疣基底並微凝固止血，形成微創保護性乾燥微痂。"
            "術後保持乾爽乾燥、禁手摳痂皮。脫痂後加強防曬保濕防止反黑。"
        ),
    },
]

# 8 大核心手術對應的標準 3 幕動畫草稿 Typed IR
DISTILLED_VISUAL_ASSETS: list[dict[str, Any]] = [
    {
        "clinic_id": None,
        "topic_key": "tree-epidermal-cyst-excision",
        "title": "未感染粉瘤微創切除原理圖解",
        "keywords": ["粉瘤", "表皮樣囊腫", "微創手術", "旋轉切除刀", "囊壁完整清除"],
        "ir": {
            "topic_key": "tree-epidermal-cyst-excision",
            "title": "未感染粉瘤微創切除原理圖解",
            "keywords": ["粉瘤", "表皮樣囊腫", "微創手術", "旋轉切除刀", "囊壁完整清除"],
            "scenes": [
                {
                    "blueprint": "cyst_excision",
                    "title": "微創旋轉切除與完整囊袋剝離",
                    "caption": "透過微創小切口導入旋轉刀頭，減壓排空角質內容物並完整剝離表皮樣囊壁，大幅降低復發風險並縮減疤痕。",
                    "labels": [{"text": "微創小切口", "tone": "neutral"}, {"text": "完整剝離囊壁", "tone": "optimal"}],
                    "params": {
                        "cyst_label": "粉瘤囊腫",
                        "sac_label": "完整包膜",
                        "core_label": "角質分泌物",
                        "layer_labels": ["表皮層", "皮下真皮層"],
                        "sac_fill": "accent",
                        "step_labels": ["微創切口定位", "減壓排空引流", "完整囊袋剝離"],
                    },
                },
                {
                    "blueprint": "contrast",
                    "title": "手術方式對比說明",
                    "caption": "相較於傳統大切口切除易留下明顯疤痕，微創旋轉切除兼顧傷口美觀與囊壁清除完整度。",
                    "labels": [{"text": "傳統切開", "tone": "warning"}, {"text": "微創旋轉", "tone": "optimal"}],
                    "params": {
                        "left": {
                            "title": "傳統大切口",
                            "note": "切口長疤痕大",
                            "mode": "wide_incision",
                            "core_effect": "dim",
                            "core_label": "張力大易留疤",
                            "footnote": "切口較長且恢復期組織張力大",
                            "unit_fill": "warn",
                        },
                        "right": {
                            "title": "微創小孔徑",
                            "note": "切口小癒合佳",
                            "mode": "minimal_incision",
                            "rows": 3,
                            "per_row": 5,
                            "footnote": "微小切口減輕組織張力與疤痕",
                            "unit_fill": "ok",
                        },
                    },
                },
                {
                    "blueprint": "timeline",
                    "title": "照護與癒合進程",
                    "caption": "術後初期加壓保護傷口，微小切口逐步癒合平整，整體組織修復狀況因人而異需由醫師當面評估。",
                    "labels": [{"text": "初期加壓", "tone": "neutral"}, {"text": "組織平整", "tone": "optimal"}],
                    "params": {
                        "milestones": ["加壓包紮", "表皮密合", "平整隱痕"],
                        "unit_effect": "mature",
                        "connectors": "wound_healing",
                        "units": 3,
                        "unit_fill": "accent",
                    },
                },
            ],
        },
        "metadata": {"origin": "batch_distill", "doc_id": "epidermal-cyst-excision"},
    },
    {
        "clinic_id": None,
        "topic_key": "tree-paronychia-matrixectomy",
        "title": "甲溝炎甲床重整原理圖解",
        "keywords": ["甲溝炎", "嵌甲", "甲床重整", "甲母質處理", "微創手術"],
        "ir": {
            "topic_key": "tree-paronychia-matrixectomy",
            "title": "甲溝炎甲床重整原理圖解",
            "keywords": ["甲溝炎", "嵌甲", "甲床重整", "甲母質處理", "微創手術"],
            "scenes": [
                {
                    "blueprint": "nail_matrix",
                    "title": "嵌甲側切與甲床基質重整",
                    "caption": "游離並垂直縱向剪除嵌入側邊甲肉的尖銳甲刺，針對性破壞生長母質根部，引導健康趾甲向前生長。",
                    "labels": [{"text": "側切嵌甲", "tone": "neutral"}, {"text": "甲母質重整", "tone": "optimal"}],
                    "params": {
                        "nail_label": "趾甲板",
                        "fold_label": "側甲襞",
                        "spicule_label": "嵌甲尖刺",
                        "matrix_label": "甲基質生長板",
                        "matrix_fill": "warn",
                        "step_labels": ["嵌甲邊緣游離", "縱向側切移除", "甲床基質重整"],
                    },
                },
                {
                    "blueprint": "contrast",
                    "title": "治療策略對比說明",
                    "caption": "單純拔除指甲易使新長甲板再次側向嵌入，配合甲母質重整處置更能維護甲床健康生長輪廓。",
                    "labels": [{"text": "反覆拔甲", "tone": "warning"}, {"text": "甲母重整", "tone": "optimal"}],
                    "params": {
                        "left": {
                            "title": "單純拔甲",
                            "note": "指甲反覆嵌入",
                            "mode": "wide_incision",
                            "core_effect": "dim",
                            "core_label": "甲母未除",
                            "footnote": "未處理生長母質容易再次向側邊生長",
                            "unit_fill": "warn",
                        },
                        "right": {
                            "title": "甲床整復",
                            "note": "重塑生長軌道",
                            "mode": "minimal_incision",
                            "rows": 3,
                            "per_row": 5,
                            "footnote": "阻斷側生甲母引導指甲向前生長",
                            "unit_fill": "ok",
                        },
                    },
                },
                {
                    "blueprint": "timeline",
                    "title": "復原與維持進程",
                    "caption": "術後初期加強抬高與換藥，肉芽消退且甲床平順穩定，完整指甲生長狀態因人而異需由醫師當面評估。",
                    "labels": [{"text": "消腫換藥", "tone": "neutral"}, {"text": "甲床平順", "tone": "optimal"}],
                    "params": {
                        "milestones": ["紅腫消退", "表皮密合", "指甲直長"],
                        "unit_effect": "mature",
                        "connectors": "wound_healing",
                        "units": 3,
                        "unit_fill": "accent",
                    },
                },
            ],
        },
        "metadata": {"origin": "batch_distill", "doc_id": "paronychia-matrixectomy"},
    },
    {
        "clinic_id": None,
        "topic_key": "tree-bromhidrosis-rotary-cutter",
        "title": "螺旋刀微創狐臭手術原理圖解",
        "keywords": ["狐臭", "頂漿腺", "微創螺旋刀", "負壓抽吸", "異味改善"],
        "ir": {
            "topic_key": "tree-bromhidrosis-rotary-cutter",
            "title": "螺旋刀微創狐臭手術原理圖解",
            "keywords": ["狐臭", "頂漿腺", "微創螺旋刀", "負壓抽吸", "異味改善"],
            "scenes": [
                {
                    "blueprint": "subdermal_curettage",
                    "title": "螺旋刀微創刮除抽吸",
                    "caption": "透過微創小切口導入旋轉刀頭，刮除真皮下層頂漿腺並由負壓同步抽除，保留表面正常皮膚血液循環。",
                    "labels": [{"text": "皮下切口", "tone": "neutral"}, {"text": "精準刮除", "tone": "optimal"}],
                    "params": {
                        "target_label": "頂漿腺體",
                        "shaver_label": "微創旋轉刀",
                        "layer_labels": ["真皮深層", "皮下脂肪層"],
                        "tool_fill": "accent",
                        "step_labels": ["微創切口定位", "旋轉刮除分離", "負壓即時抽吸"],
                    },
                },
                {
                    "blueprint": "contrast",
                    "title": "手術方式特點對比",
                    "caption": "相較於傳統大範圍剪除皮瓣易有明顯疤痕，螺旋刀微創切除顯著縮小傷口範圍並兼顧腺體去除效果。",
                    "labels": [{"text": "傳統切開", "tone": "warning"}, {"text": "微創螺旋", "tone": "optimal"}],
                    "params": {
                        "left": {
                            "title": "傳統剪開法",
                            "note": "傷口較大疤痕長",
                            "mode": "wide_incision",
                            "core_effect": "dim",
                            "core_label": "疤痕較顯著",
                            "footnote": "傳統切口長度較大需要較長恢復期",
                            "unit_fill": "warn",
                        },
                        "right": {
                            "title": "螺旋刀微創",
                            "note": "切口微細恢復快",
                            "mode": "minimal_incision",
                            "rows": 3,
                            "per_row": 5,
                            "footnote": "微創孔徑大幅減輕皮膚創傷與疤痕",
                            "unit_fill": "ok",
                        },
                    },
                },
                {
                    "blueprint": "timeline",
                    "title": "術後固定與修復進程",
                    "caption": "術後初期加壓固定確保皮瓣貼合，皮下組織逐漸軟化平整，個別異味改善程度因人而異需由醫師當面評估。",
                    "labels": [{"text": "紗布固定", "tone": "neutral"}, {"text": "皮瓣平整", "tone": "optimal"}],
                    "params": {
                        "milestones": ["加壓固定", "皮瓣密合", "組織軟化"],
                        "unit_effect": "mature",
                        "connectors": "wound_healing",
                        "units": 3,
                        "unit_fill": "accent",
                    },
                },
            ],
        },
        "metadata": {"origin": "batch_distill", "doc_id": "bromhidrosis-rotary-cutter"},
    },
    {
        "clinic_id": None,
        "topic_key": "tree-endolift-laser",
        "title": "光纖內提拉微創原理圖解",
        "keywords": ["光纖拉提", "皮下雷射", "筋膜緊緻", "微創溶脂", "膠原新生"],
        "ir": {
            "topic_key": "tree-endolift-laser",
            "title": "光纖內提拉微創原理圖解",
            "keywords": ["光纖拉提", "皮下雷射", "筋膜緊緻", "微創溶脂", "膠原新生"],
            "scenes": [
                {
                    "blueprint": "skin_energy",
                    "title": "微光纖深層熱能緊緻",
                    "caption": "極細光纖導入皮下層，釋放微米雷射熱能融解局部脂肪，同時誘發深層筋膜膠原纖維熱收縮。",
                    "labels": [{"text": "微細光纖", "tone": "neutral"}, {"text": "熱能緊縮", "tone": "optimal"}],
                    "params": {
                        "mode": "focused",
                        "probe_label": "光纖探針",
                        "layer_labels": ["真皮深層", "皮下脂肪", "筋膜層"],
                        "focal_points": 5,
                        "energy_fill": "accent",
                        "step_labels": ["光纖微孔導入", "光熱均勻溶脂", "深層筋膜收縮"],
                    },
                },
                {
                    "blueprint": "contrast",
                    "title": "能量分層傳導對比",
                    "caption": "傳統表面加熱需經表皮穿透，皮下光纖傳導則直接於目標組織釋放能量，提高深層拉提效率。",
                    "labels": [{"text": "表皮傳導", "tone": "neutral"}, {"text": "皮下直達", "tone": "optimal"}],
                    "params": {
                        "left": {
                            "title": "表面傳導型",
                            "note": "能量由外向內",
                            "mode": "thermal_spread",
                            "core_effect": "dim",
                            "core_label": "表皮吸熱",
                            "footnote": "需控制表皮溫度避免能量過度累積",
                            "unit_fill": "warn",
                        },
                        "right": {
                            "title": "光纖直達型",
                            "note": "能量皮下深層",
                            "mode": "targeted_energy",
                            "rows": 3,
                            "per_row": 5,
                            "footnote": "深層直接作用刺激筋膜與組織收緊",
                            "unit_fill": "ok",
                        },
                    },
                },
                {
                    "blueprint": "timeline",
                    "title": "膠原重組與收緊進程",
                    "caption": "術後微小水腫自然消退，皮下膠原持續重塑展現緊緻輪廓，個人維持狀態因人而異需由醫師當面評估。",
                    "labels": [{"text": "初期微腫", "tone": "neutral"}, {"text": "輪廓緊實", "tone": "optimal"}],
                    "params": {
                        "milestones": ["微腫消退", "纖維收縮", "深層緊緻"],
                        "unit_effect": "mature",
                        "connectors": "collagen_remodeling",
                        "units": 3,
                        "unit_fill": "accent",
                    },
                },
            ],
        },
        "metadata": {"origin": "batch_distill", "doc_id": "endolift-laser"},
    },
    {
        "clinic_id": None,
        "topic_key": "tree-microneedle-rf",
        "title": "黃金微針電波原理圖解",
        "keywords": ["黃金微針", "電波拉提", "真皮膠原", "毛孔細緻", "微創修復"],
        "ir": {
            "topic_key": "tree-microneedle-rf",
            "title": "黃金微針電波原理圖解",
            "keywords": ["黃金微針", "電波拉提", "真皮膠原", "毛孔細緻", "微創修復"],
            "scenes": [
                {
                    "blueprint": "skin_energy",
                    "title": "微針電波立體加熱",
                    "caption": "絕緣微針穿透表皮進入真皮目標層，針尖精準釋放雙極射頻能量，啟動深層膠原與彈力纖維重組。",
                    "labels": [{"text": "絕緣針身", "tone": "neutral"}, {"text": "針尖放電", "tone": "optimal"}],
                    "params": {
                        "mode": "volumetric",
                        "probe_label": "黃金微針",
                        "layer_labels": ["表皮保護層", "真皮膠原層", "皮下淺層"],
                        "focal_points": 5,
                        "energy_fill": "accent",
                        "step_labels": ["微針精準穿透", "針尖釋放電波", "真皮膠原新生"],
                    },
                },
                {
                    "blueprint": "contrast",
                    "title": "能量深淺分佈對比",
                    "caption": "非絕緣傳統加熱能量易散佈表皮，針尖發電設計聚焦真皮深層加熱，有效降低表皮熱傷害風險。",
                    "labels": [{"text": "表層分散", "tone": "neutral"}, {"text": "深層聚焦", "tone": "optimal"}],
                    "params": {
                        "left": {
                            "title": "表層彌散型",
                            "note": "熱能停留表皮",
                            "mode": "thermal_spread",
                            "core_effect": "dim",
                            "core_label": "表皮高溫",
                            "footnote": "表面熱感較強且不易傳入深層",
                            "unit_fill": "warn",
                        },
                        "right": {
                            "title": "針尖深層型",
                            "note": "聚焦真皮加熱",
                            "mode": "targeted_energy",
                            "rows": 3,
                            "per_row": 5,
                            "footnote": "絕緣保護表皮能量深層均勻釋放",
                            "unit_fill": "ok",
                        },
                    },
                },
                {
                    "blueprint": "timeline",
                    "title": "膠原新生與修護進程",
                    "caption": "微細針孔迅速閉合修復，真皮基質膠原漸進新生緊實，個人膚質改善程度因人而異需由醫師當面評估。",
                    "labels": [{"text": "針孔閉合", "tone": "neutral"}, {"text": "膚質細緻", "tone": "optimal"}],
                    "params": {
                        "milestones": ["微紅減退", "自體激活", "毛孔平滑"],
                        "unit_effect": "mature",
                        "connectors": "collagen_remodeling",
                        "units": 3,
                        "unit_fill": "accent",
                    },
                },
            ],
        },
        "metadata": {"origin": "batch_distill", "doc_id": "microneedle-rf"},
    },
    {
        "clinic_id": None,
        "topic_key": "tree-scar-subcision",
        "title": "疤痕皮下切割原理圖解",
        "keywords": ["皮下切割", "疤痕鬆解", "攣縮纖維", "痘疤修復", "光纖處置"],
        "ir": {
            "topic_key": "tree-scar-subcision",
            "title": "疤痕皮下切割原理圖解",
            "keywords": ["皮下切割", "疤痕鬆解", "攣縮纖維", "痘疤修復", "光纖處置"],
            "scenes": [
                {
                    "blueprint": "subdermal_curettage",
                    "title": "皮下牽引纖維鬆解",
                    "caption": "以微創光纖鈍針深入皮下，切斷下拉牽扯真皮的攣縮纖維束，釋放局部張力促使凹陷組織向上平順回彈。",
                    "labels": [{"text": "皮下切入", "tone": "neutral"}, {"text": "鬆解牽引", "tone": "optimal"}],
                    "params": {
                        "target_label": "牽引纖維",
                        "shaver_label": "微型皮下針刀",
                        "layer_labels": ["凹陷表皮", "深層基底層"],
                        "tool_fill": "accent",
                        "step_labels": ["微創導入定位", "扇形切割沾黏", "促進組織回彈"],
                    },
                },
                {
                    "blueprint": "contrast",
                    "title": "處置深度對比說明",
                    "caption": "單純表面微磨難以鬆解深層硬化纖維，深層水平皮下切割能根本釋放沾黏束帶，改善凹陷形態。",
                    "labels": [{"text": "表面微磨", "tone": "neutral"}, {"text": "皮下鬆解", "tone": "optimal"}],
                    "params": {
                        "left": {
                            "title": "單純表面型",
                            "note": "難鬆解底層",
                            "mode": "wide_incision",
                            "core_effect": "dim",
                            "core_label": "牽引仍在",
                            "footnote": "深層纖維束依然向下拉扯凹陷",
                            "unit_fill": "warn",
                        },
                        "right": {
                            "title": "皮下切割型",
                            "note": "切斷攣縮束",
                            "mode": "minimal_incision",
                            "rows": 3,
                            "per_row": 5,
                            "footnote": "切斷牽引束帶讓皮膚自然回彈平坦",
                            "unit_fill": "ok",
                        },
                    },
                },
                {
                    "blueprint": "timeline",
                    "title": "組織重塑與回彈進程",
                    "caption": "皮下切割後微小血腫逐漸被吸收，新生膠原重組回填凹陷，個人疤痕修復程度因人而異需由醫師當面評估。",
                    "labels": [{"text": "張力釋放", "tone": "neutral"}, {"text": "平整回彈", "tone": "optimal"}],
                    "params": {
                        "milestones": ["張力解除", "肉芽充盈", "外觀平整"],
                        "unit_effect": "mature",
                        "connectors": "wound_healing",
                        "units": 3,
                        "unit_fill": "accent",
                    },
                },
            ],
        },
        "metadata": {"origin": "batch_distill", "doc_id": "scar-subcision"},
    },
    {
        "clinic_id": None,
        "topic_key": "tree-lipoma-aspiration",
        "title": "微創脂肪瘤切除原理圖解",
        "keywords": ["脂肪瘤", "微創抽吸", "包膜取出", "微小切口", "預防復發"],
        "ir": {
            "topic_key": "tree-lipoma-aspiration",
            "title": "微創脂肪瘤切除原理圖解",
            "keywords": ["脂肪瘤", "微創抽吸", "包膜取出", "微小切口", "預防復發"],
            "scenes": [
                {
                    "blueprint": "subdermal_curettage",
                    "title": "微創抽吸輔助切除",
                    "caption": "經由極小切口導入鈍頭套管，負壓抽除脂肪瘤體並完整剝離外層纖維包膜，兼具微小傷口與徹底清除。",
                    "labels": [{"text": "微孔導入", "tone": "neutral"}, {"text": "包膜取出", "tone": "optimal"}],
                    "params": {
                        "target_label": "脂肪瘤塊",
                        "shaver_label": "負壓抽吸管",
                        "layer_labels": ["表皮皮下", "深層筋膜層"],
                        "tool_fill": "fat",
                        "step_labels": ["微創切口入路", "負壓分層抽吸", "完整取出包膜"],
                    },
                },
                {
                    "blueprint": "contrast",
                    "title": "切口形態對比說明",
                    "caption": "相較於傳統手術需要切開與腫瘤等長的長傷口，微創抽吸能大幅縮小切口長度並隱蔽於皮紋。",
                    "labels": [{"text": "傳統切開", "tone": "warning"}, {"text": "微創抽吸", "tone": "optimal"}],
                    "params": {
                        "left": {
                            "title": "傳統大線切",
                            "note": "切口等長疤大",
                            "mode": "wide_incision",
                            "core_effect": "dim",
                            "core_label": "疤痕顯著",
                            "footnote": "切口長度需涵蓋整個脂肪瘤大小",
                            "unit_fill": "warn",
                        },
                        "right": {
                            "title": "微孔抽吸法",
                            "note": "微小切口癒合",
                            "mode": "minimal_incision",
                            "rows": 3,
                            "per_row": 5,
                            "footnote": "數毫米小孔兼顧腫瘤清除與美觀",
                            "unit_fill": "ok",
                        },
                    },
                },
                {
                    "blueprint": "timeline",
                    "title": "空腔閉合與平復進程",
                    "caption": "術後加壓協助皮下空腔貼合閉合，局部組織逐漸軟化平整，個別恢復狀態因人而異需由醫師當面評估。",
                    "labels": [{"text": "空腔貼合", "tone": "neutral"}, {"text": "組織平復", "tone": "optimal"}],
                    "params": {
                        "milestones": ["加壓包紮", "皮下貼合", "平整隱痕"],
                        "unit_effect": "mature",
                        "connectors": "wound_healing",
                        "units": 3,
                        "unit_fill": "accent",
                    },
                },
            ],
        },
        "metadata": {"origin": "batch_distill", "doc_id": "lipoma-aspiration"},
    },
    {
        "clinic_id": None,
        "topic_key": "tree-plasma-pen-electrocautery",
        "title": "等離子筆微氣化原理圖解",
        "keywords": ["等離子筆", "電灼治療", "皮贅肉芽", "微創氣化", "贅疣去除"],
        "ir": {
            "topic_key": "tree-plasma-pen-electrocautery",
            "title": "等離子筆微氣化原理圖解",
            "keywords": ["等離子筆", "電灼治療", "皮贅肉芽", "微創氣化", "贅疣去除"],
            "scenes": [
                {
                    "blueprint": "laser_action",
                    "title": "等離子弧光微氣化",
                    "caption": "以微小高能量等離子弧光精準聚焦病灶，瞬間氣化贅疣凸起組織並凝固微血管，形成微創保護性薄痂。",
                    "labels": [{"text": "等離子弧", "tone": "neutral"}, {"text": "病灶微氣化", "tone": "optimal"}],
                    "params": {
                        "mode": "fractional",
                        "beam_label": "等離子弧",
                        "target_label": "贅疣病灶",
                        "layer_labels": ["病灶表皮層", "真皮基底層"],
                        "beam_fill": "accent",
                        "step_labels": ["等離子弧聚焦", "表皮病灶氣化", "微創結痂修復"],
                    },
                },
                {
                    "blueprint": "contrast",
                    "title": "作用範圍對比說明",
                    "caption": "相較於大範圍傳統熱擴散易傷及周邊皮膚，等離子聚焦放電僅針對表面病灶，減少多餘熱傷害。",
                    "labels": [{"text": "廣泛擴散", "tone": "warning"}, {"text": "精準聚焦", "tone": "optimal"}],
                    "params": {
                        "left": {
                            "title": "傳統熱擴散",
                            "note": "易波及周圍",
                            "mode": "thermal_spread",
                            "core_effect": "dim",
                            "core_label": "周圍受熱",
                            "footnote": "熱能擴散容易造成周邊皮膚發紅",
                            "unit_fill": "warn",
                        },
                        "right": {
                            "title": "微弧精聚焦",
                            "note": "精準限於病灶",
                            "mode": "targeted_energy",
                            "rows": 3,
                            "per_row": 5,
                            "footnote": "微小弧光精準作用於贅疣組織本身",
                            "unit_fill": "ok",
                        },
                    },
                },
                {
                    "blueprint": "timeline",
                    "title": "結痂與新皮生成進程",
                    "caption": "微痂自然乾燥脫落後新生粉嫩表皮，平順恢復膚質，個別結痂脫落時間因人而異需由醫師當面評估。",
                    "labels": [{"text": "微痂保護", "tone": "neutral"}, {"text": "新皮平滑", "tone": "optimal"}],
                    "params": {
                        "milestones": ["微痂保護", "自體重整", "新皮平整"],
                        "unit_effect": "mature",
                        "connectors": "collagen_remodeling",
                        "units": 3,
                        "unit_fill": "accent",
                    },
                },
            ],
        },
        "metadata": {"origin": "batch_distill", "doc_id": "plasma-pen-electrocautery"},
    },
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="批次提煉 8 大核心門診手術 PageIndex 推理樹與動畫草稿",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=PROD_DB_PATH,
        help="目標 SQLite 資料庫路徑",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="唯讀預覽模式，不進行寫入",
    )
    args = parser.parse_args(argv)
    target_path = Path(args.db)

    if not target_path.exists():
        print(f"❌ 錯誤：資料庫檔案不存在：{target_path}", file=sys.stderr)
        return 2

    # 前置驗證：所有 IR 必須 100% 通過 validate_ir
    for asset in DISTILLED_VISUAL_ASSETS:
        ok, code = validate_ir(asset["ir"])
        if not ok:
            print(f"❌ IR 前置驗證失敗：{asset['topic_key']}, 代碼={code}", file=sys.stderr)
            return 1

    if args.dry_run:
        print("🔍 【預覽模式】符合規格之 8 大手術推理樹與動畫草稿：")
        for idx, t in enumerate(DISTILLED_TREES, 1):
            print(f"[{idx}] doc_id: {t['doc_id']} | 標題: {t['title']}")
        print(f"總計 {len(DISTILLED_TREES)} 棵樹與 {len(DISTILLED_VISUAL_ASSETS)} 份動畫草稿驗證通過。")
        return 0

    conn = sqlite3.connect(str(target_path))
    try:
        cur = conn.cursor()
        # 1. 檢查既有資料庫狀態
        cur.execute("SELECT count(*), group_concat(doc_id) FROM page_index_trees")
        orig_tree_count, orig_doc_ids = cur.fetchone()
        print(f"📊 寫入前推理樹筆數：{orig_tree_count}（包含：{orig_doc_ids}）")

        if not has_visual_assets_table(conn):
            print("❌ 資料庫缺少 visual_assets 資料表，請先執行遷移腳本。", file=sys.stderr)
            return 2

        cur.execute("SELECT count(*) FROM visual_assets")
        orig_visual_count = cur.fetchone()[0]
        print(f"📊 寫入前視覺解說卡筆數：{orig_visual_count}")

        # 2. 寫入門診手術 PageIndex 臨床推理樹 (緻妍與凡登等其他診所皆建立，屬於所有人可用的醫學推理樹)
        print("\n⏳ 正在寫入門診手術 PageIndex 臨床推理樹...")
        t_ins, t_upd, t_unchanged = upsert_trees(conn, DISTILLED_TREES, source_type="clinic_upload", review_status="approved")
        print(f"✅ 緻妍推理樹寫入完成：新增={t_ins}, 更新={t_upd}, 未變={t_unchanged}")

        # 針對凡登診所 (3503264627) 亦同步建立一般醫學推理樹
        cur.execute("SELECT clinic_id FROM clinic_info WHERE clinic_id != ?", (CLINIC_ID,))
        other_clinics = [row[0] for row in cur.fetchall()]
        for other_cid in other_clinics:
            other_trees = []
            for t in DISTILLED_TREES:
                ot = dict(t)
                ot["clinic_id"] = other_cid
                ot["doc_id"] = f"{other_cid}-{t['doc_id']}"
                ot["category"] = "general"
                other_trees.append(ot)
            o_ins, o_upd, o_unchanged = upsert_trees(conn, other_trees, source_type="clinic_upload", review_status="approved")
            print(f"✅ 診所 {other_cid} 推理樹寫入完成：新增={o_ins}, 更新={o_upd}, 未變={o_unchanged}")

        # 3. 清理舊版已被駁回之診所綁定草稿，寫入歸屬「一般醫學共用 (所有人可以使用)」的全新 3 幕動畫草稿
        print("\n⏳ 正在清理舊版駁回草稿並寫入一般醫學共用 8 份視覺解說卡動畫草稿...")
        cur.execute(
            "DELETE FROM visual_assets WHERE clinic_id = ? AND review_status = 'rejected' AND topic_key LIKE 'tree-%'",
            (CLINIC_ID,)
        )
        if cur.rowcount > 0:
            print(f"  已清除舊版被駁回之診所綁定草稿 {cur.rowcount} 筆，由全新一般醫學草稿取代。")

        visual_res = upsert_assets(conn, DISTILLED_VISUAL_ASSETS, source_type="llm_generated", commit=True)
        print(f"✅ 動畫草稿寫入完成：新增={visual_res['inserted']}, 更新={visual_res['updated']}, 未變={visual_res['unchanged']}")

        conn.commit()

        # 4. 驗收結果
        cur.execute("SELECT count(*) FROM page_index_trees")
        final_tree_count = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM visual_assets")
        final_visual_count = cur.fetchone()[0]

        print(f"\n🎉 處理完成！")
        print(f"📈 最終推理樹總數：{final_tree_count} 筆（新增 {final_tree_count - orig_tree_count} 筆）")
        print(f"📈 最終視覺解說卡總數：{final_visual_count} 筆（新增 {final_visual_count - orig_visual_count} 筆）")

        # 檢查 8 筆樹的 doc_id 是否都在資料庫中
        cur.execute("SELECT doc_id, title, review_status FROM page_index_trees ORDER BY id ASC")
        print("\n📋 目前資料庫內所有 PageIndex 推理樹：")
        for r in cur.fetchall():
            print(f"  - {r[0]}: {r[1]} [{r[2]}]")

        cur.execute("SELECT topic_key, title, review_status FROM visual_assets ORDER BY id ASC")
        print("\n🎬 目前資料庫內所有視覺解說卡：")
        for r in cur.fetchall():
            print(f"  - {r[0]}: {r[1]} [{r[2]}]")

        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
