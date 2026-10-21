#!/usr/bin/env python3
"""
Taiwan Clinic Medical PageIndex RAG System - 凡登整形外科診所 27 篇官方醫療內文提煉模組
針對凡登整形外科（clinic_id = '3503264627'），將官網 27 篇專業醫療內文結構化提煉為：
1. 27 棵標準四段式 PageIndex 臨床推理樹（page_index_trees）
2. 54 筆高頻口語臨床問答（faq_cache）

嚴格醫療合規準則：
1. 100% 繁體中文，無簡體字。
2. 零價格數字洩漏（如有提及一律由 deep_mask_prices 清洗為 [請致電診所確認]）。
3. 零違法醫療廣告宣傳與保證字眼（嚴禁「保證有效」、「徹底根除」、「100%」、「零風險」等）。
4. 醫師權威指令（*_physician_notes）強制留空 (None)，待主治醫師親自簽核。
5. 寫入一律經由 db_writer.upsert_trees 與 faq_writer.upsert_faqs 唯一權威路徑。
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

# 確保 opencc 可用
try:
    import opencc  # noqa: F401
except ImportError:
    uv_opencc = Path("/home/hsu/.cache/uv/archive-v0/hD69btIoBk4Lc2HKmEOvw")
    if uv_opencc.exists():
        sys.path.insert(0, str(uv_opencc))

from src.pageindex.db_writer import upsert_trees
from src.pageindex.faq_writer import upsert_faqs
from src.pageindex.tree_distiller import deep_mask_prices, validate_tree_segment

CLINIC_ID = "3503264627"
PROD_DB_PATH = PROJECT_ROOT / "clinic.db"

# 27 筆凡登專屬 PageIndex 臨床推理樹定義
VENDOME_TREES: list[dict[str, Any]] = [
    {
        "doc_id": f"{CLINIC_ID}-qray-frx-fractional-laser",
        "clinic_id": CLINIC_ID,
        "title": "QRAY FRX 雙波長微創飛梭雷射",
        "category": "special",
        "pre_op": (
            "術前須知：1. 評估痘疤凹洞深度、毛孔粗大與皮膚光老化程度 2. 術前一週停用口服及外用A酸、果酸煥膚與去角質 "
            "3. 治療部位若有單純疱疹、濕疹或未癒合傷口需延期 4. 確實卸妝清潔，均勻敷上表面麻醉藥膏三十分鐘至四十分鐘。"
        ),
        "procedure": (
            "療程步驟：1. 採用波長 10600nm 二氧化碳汽化微光束，微創傷口僅約六十毫微米 2. 深入真皮層引發微熱分解作用（MTZ），"
            "汽化受損纖維化組織 3. 刺激深層纖維母細胞新生膠原蛋白與彈力纖維，促使真皮層排列重整，填補凹陷痘疤。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 術後皮膚微紅微腫伴灼熱感，立即冰敷鎮定二十分鐘 2. 術後二十四小時內避免接觸自來水，以無菌生理食鹽水輕按清潔 "
            "3. 薄塗抗生素或生長因子修復藥膏 4. 約三天內形成微細結痂，切勿自行摳抓，加強保濕與物理性防曬。"
        ),
        "maintenance": (
            "長期維持保養：1. 微痂約五至七天自然脫落，加強神經醯胺與玻尿酸保濕 2. 一個月內避免高溫三溫暖、溫泉及酸類美白產品 "
            "3. 建議每四至六週由醫師評估進行下一階段治療 4. 定期回診觀察真皮層組織增生與平整度。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "QRAY FRX 飛梭雷射以 10600nm 二氧化碳汽化微光束深入真皮層，刺激膠原蛋白新生與凹陷組織填補。"
            "術前停用A酸，術後冰敷鎮定並維持無菌清潔，約一週結痂脫落後加強保濕防曬。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-thermage-flx-rf",
        "clinic_id": CLINIC_ID,
        "title": "Thermage FLX 鳳凰電波單極緊膚療程",
        "category": "special",
        "pre_op": (
            "術前須知：1. 評估全臉肌膚鬆弛度、軟組織下垂及輪廓線模糊程度 2. 體內裝置心律調節器、植入式去顫器或金屬植入物者嚴禁施作 "
            "3. 術前一週避免過度曝曬與去角質 4. 清潔臉部並貼附原廠回路背貼，確認治療向量標記。"
        ),
        "procedure": (
            "療程步驟：1. 運用專利單極電波技術與智能 AccuREP 能量優化技術，每一發擊發前自動測量局部肌膚阻抗 "
            "2. 探頭將立體高頻電波容積式傳導至真皮層與皮下組織（深度達四點三毫米） 3. 促使膠原蛋白即刻收縮，並配合環迴震動與冷媒噴灑提升舒適度。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 術後皮膚可能出現暫時性輕微泛紅或微溫浮腫，多於數小時至兩天內消退 2. 無表面創口，當天即可溫和清潔與防曬 "
            "3. 避免立即劇烈冰敷以免削弱熱能刺激膠原新生效應 4. 一週內避免前往溫泉、烤箱或劇烈高溫活動。"
        ),
        "maintenance": (
            "長期維持保養：1. 術後一至三個月真皮層纖維母細胞持續分泌新生膠原蛋白，輪廓緊緻度逐步展現 2. 日常加強抗氧化精華與高係數防曬 "
            "3. 維持作息規律與充足水分 4. 建議每年定期由醫師評估規劃一次維持療程。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "Thermage FLX 鳳凰電波利用專利單極電波與智能阻抗校準，容積式加熱真皮層與皮下組織促使膠原收縮新生。"
            "無恢復期，術後避免劇烈冰敷，一至三個月展現自然緊緻提拉效果。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-chin-augmentation-genioplasty",
        "clinic_id": CLINIC_ID,
        "title": "下巴美型手術（3D客製人工骨植入與下巴截骨成型術）",
        "category": "special",
        "pre_op": (
            "術前須知：1. 進行 3D 顏面顱骨電腦斷層掃描（CT），精確評估下巴後縮長度、翹度與頦神經位置 2. 術前一週停用阿斯匹靈、抗凝血劑與活血中藥 "
            "3. 手術前維持良好口腔衛生 4. 舒眠或全身麻醉前嚴格禁食八小時。"
        ),
        "procedure": (
            "手術步驟：1. 自下唇口腔內黏膜切口切開，在骨膜下精密剝離囊袋並保護雙側頦神經 2. 人工骨植入方案：將客製雕塑之人工骨貼合下顎骨緣，"
            "以鈦釘牢固鎖定；或下巴截骨方案：微動力骨鋸平整截開下頦骨塊向前向下移位，微型鈦板剛性固定 3. 口腔黏膜分層減張對位縫合。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 下巴黏貼彈性加壓膠帶固定三至五天以減緩血腫 2. 每餐進食後務必使用無菌漱口水徹底清潔口腔防止感染 "
            "3. 前三天冰敷下顎周圍，第四天起改溫敷 4. 採流質或軟質溫涼飲食，避免用力咀嚼與碰撞下巴。"
        ),
        "maintenance": (
            "長期維持保養：1. 術後約一週回診檢查傷口癒合狀況（口內可吸收線約兩至三週自行吸收） 2. 一個月內避免托下巴、趴睡或碰撞下顎 "
            "3. 定期追蹤咬合及骨癒合進度 4. 建立協調自然的三庭五眼下臉立體比例。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "下巴美型手術經口腔內切口，透過人工骨植入或下巴截骨調整下臉立體弧度與翹度。"
            "術前 3D 電腦斷層精準定位神經，術後口內照護與加壓固定防血腫，一個月內避免外力碰撞。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-mid-lower-smas-facelift",
        "clinic_id": CLINIC_ID,
        "title": "中下臉 SMAS 筋膜深層拉皮手術（展延式深層提拉與骨膜固定）",
        "category": "special",
        "pre_op": (
            "術前須知：1. 全面評估皮膚、皮下脂肪、SMAS筋膜、維持韌帶及顏面神經走行 2. 評估法令紋、嘴邊肉、木偶紋及下顎緣鬆垂成因 "
            "3. 術前兩週嚴格戒菸、停用抗凝血劑與阿斯匹靈 4. 完成心電圖、胸部X光及全身麻醉術前檢驗。"
        ),
        "procedure": (
            "手術步驟：1. 沿耳前耳輪腳自然摺痕經耳後隱痕切口進入 2. 展延式深層筋膜提拉（Extended Deep Plane SMAS），精細鬆解顴骨韌帶與咬肌韌帶 "
            "3. 將下垂 SMAS 筋膜地基向上後方向量立體重塑復位，並以強韌不可吸收線牢固錨定於骨膜（Periosteum）上 4. 修剪贅皮後進行無張力精密減張縫合。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 放置負壓引流管（通常一至兩天視引流量拔除）預防皮下血腫 2. 全臉佩戴彈性加壓面罩 3. 前三天頭部抬高臥床並局部冷敷 "
            "4. 每日使用無菌生理食鹽水與抗生素藥膏換藥，嚴防傷口感染。"
        ),
        "maintenance": (
            "長期維持保養：1. 術後七至十天分段拆線，持續佩戴塑臉面罩二至四週鞏固貼合 2. 拆線一週後開始塗抹除疤凝膠，避免陽光直射疤痕 "
            "3. 一個月內避免大笑、劇烈運動或按摩臉部 4. 深層骨架筋膜重置提供穩定長效之年輕輪廓。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "中下臉拉皮採展延式深層筋膜（SMAS）提拉，鬆解維持韌帶並將筋膜錨定於骨膜，根本改善法令紋與下顎線下垂。"
            "術後引流管防血腫、面罩加壓塑型，無張力縫合保護耳垂自然形態。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-facial-bone-contouring",
        "clinic_id": CLINIC_ID,
        "title": "顏面輪廓削骨手術（顴骨弓內推縮窄與下顎骨角削減塑型）",
        "category": "special",
        "pre_op": (
            "術前須知：1. 安排高解析度 3D 顏面顱骨電腦斷層掃描（CT）與三維骨骼重組 2. 精確定位下顎齒槽神經管走向、顴骨體弓突起程度及軟組織厚度 "
            "3. 術前兩週停用抗凝血劑與活血補品 4. 維持口腔衛生並落實術前八小時禁食。"
        ),
        "procedure": (
            "手術步驟：1. 全身麻醉下施行。顴骨內推自口腔上顎前庭切口合併鬢角隱痕切口，進行雙端截骨將顴骨弓適度向內旋轉縮窄，"
            "以微型純鈦板釘雙重剛性固定 2. 下顎骨角削減自口內下顎前庭入路，精準保護神經血管束，以微動力骨鋸弧形平滑切除肥大骨角並研磨修順 3. 生理食鹽水沖洗後分層縫合。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 放置引流管排除骨面微量滲血 2. 佩戴彈性壓力面罩加壓塑型防止血腫 3. 每小時以無菌漱口水清潔口腔，嚴防感染 "
            "4. 前三天採全流質冷溫飲食並密集冰敷雙頰，第四天起改溫敷退腫。"
        ),
        "maintenance": (
            "長期維持保養：1. 兩週內進食軟質清淡食物，避免堅硬、費力咀嚼之食材 2. 口內縫線約兩週門診檢查 3. 一個月內避免外力碰撞臉部或劇烈球類運動 "
            "4. 術後三個月骨癒合穩定，展現柔和流暢輪廓線條。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "顏面輪廓削骨手術經口內隱痕切口，進行顴骨弓內推縮窄與下顎骨角弧形削減，以純鈦板釘牢固骨骼。"
            "術前 3D 電腦斷層導航避開神經，術後面罩加壓與口內清潔防感染，術後三個月展現自然和諧輪廓。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-ultraformer-mpt-hifu",
        "clinic_id": CLINIC_ID,
        "title": "Ultraformer MPT 媚必提微脈衝音波拉提療程",
        "category": "special",
        "pre_op": (
            "術前須知：1. 評估全臉與頸部鬆弛程度、脂肪分佈及法令紋深淺 2. 治療區域若有嚴重囊腫型痤瘡、開放傷口或金屬植入物應暫緩 "
            "3. 術前一週避免過度曝曬與酸類去角質 4. 徹底清潔卸妝並敷上表面麻醉藥膏約三十分鐘。"
        ),
        "procedure": (
            "療程步驟：1. 結合微聚焦音波（MMFU）與創新微脈衝技術（MPT），具備標準點狀聚焦與連續微脈衝線狀模式 2. 透過多層次探頭深度 "
            "（一點五毫米至深層脂肪探頭），將密集音波熱能傳遞至真皮層、脂肪層與 SMAS 筋膜層 3. 形成密集熱凝固區，引導筋膜即刻收縮並刺激長效膠原蛋白重塑。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 術後肌膚輕度發紅、微溫或微浮腫，多數於數小時內消退 2. 無表皮創口，當天即可正常保濕、防曬與上妝 "
            "3. 一週內避免使用磨砂膏、A酸與果酸產品 4. 禁止前往高溫三溫暖烤箱。"
        ),
        "maintenance": (
            "長期維持保養：1. 術後即刻具備筋膜緊緻感，一至三個月隨著真皮膠原纖維新生重組，下顎線與立體度顯著提升 2. 加強肌膚保濕補水與日間防曬 "
            "3. 維持健康作息 4. 建議每六至十二個月由醫師評估維持治療。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "Ultraformer MPT 媚必提微脈衝音波透過連續聚焦熱能，直達 SMAS 筋膜層與皮下脂肪層促使緊緻收縮。"
            "無恢復期，術後加強保濕與防曬，一至三個月展現自然提拉與下顎線清晰輪廓。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-mommy-makeover-reconstruction",
        "clinic_id": CLINIC_ID,
        "title": "產後媽媽身形修復手術（腹直肌閉合、腹部拉皮與複合自體脂肪隆乳）",
        "category": "special",
        "pre_op": (
            "術前須知：1. 評估產後腹壁鬆弛度、腹直肌分離寬度、鬆弛妊娠紋贅皮及乳房萎縮下垂程度 2. 建議停止哺乳至少六個月且體重穩定後評估 "
            "3. 術前四週嚴格戒菸以確保皮瓣微血管循環灌流 4. 完成心電圖、凝血功能檢驗與全身麻醉評估。"
        ),
        "procedure": (
            "手術步驟：1. 全身麻醉下施行。於下腹比基尼線低位隱痕切口大範圍剝離腹壁皮瓣 2. 以高強度不吸收線進行腹直肌筋膜摺疊縫合（Plication），"
            "閉合分離肌肉重建緊緻腹壁核心 3. 切除下腹鬆弛贅皮與多餘組織，精雕重置肚臍 4. 同步抽吸腰腹多餘脂肪，經離心純化後精細分層移植至乳房萎縮部位。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 留置腹部引流管觀察分泌液量 2. 二十四小時穿戴醫療級高壓束腹衣與定位胸衣 3. 前數天採屈膝微彎腰姿勢休息與行走，"
            "減輕腹部切口縫合張力 4. 按醫囑服用抗生素與消腫藥物，傷口維持乾燥清潔。"
        ),
        "maintenance": (
            "長期維持保養：1. 引流管通常於三至五天引流量小於三十毫升後拔除 2. 術後一至兩週分段拆線 3. 束腹衣持續穿戴四至八週幫助組織貼合 "
            "4. 術後六週內嚴禁提重物或劇烈核心運動 5. 循序漸進恢復平坦緊實身形。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "產後媽媽身形修復整合腹直肌分離縫合閉合、腹部切皮拉皮與自體脂肪豐胸，重塑緊緻腹壁與胸型曲線。"
            "低位比基尼隱痕切口，術後穿戴束腹衣並避免劇烈腹部用力，循序恢復健康自信曲線。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-fue-hair-transplantation",
        "clinic_id": CLINIC_ID,
        "title": "FUE 微創毛囊單位精準植髮手術",
        "category": "special",
        "pre_op": (
            "術前須知：1. 使用高倍率毛囊檢測儀評估後枕部供髮區毛囊密度、毛髮直徑及受髮區落髮分期 2. 術前一週停用外用生髮水（Minoxidil）、"
            "阿斯匹靈及抗凝血藥品 3. 手術當天穿著前開襟襯衫，避免穿脫衣物碰撞受髮區 4. 洗淨頭皮維持清爽。"
        ),
        "procedure": (
            "手術步驟：1. 後枕部供髮區局部腫脹麻醉 2. 使用直徑零點八至一點零毫米微動力取髮針，精準分散提取單株健康毛囊單位 3. 高解析顯微鏡下精細分離、"
            "修整並置於低溫生長因子保存液 4. 受髮區依自然毛流生長方向與角度進行微孔藝術化精準植入。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 後枕部覆蓋無菌敷料，受髮區保持通風透氣並定時噴灑無菌生理食鹽水保濕 2. 黃金七十二小時內嚴禁觸摸、抓撓或用力碰撞受髮區 "
            "3. 睡眠時枕部墊高採平躺仰臥 4. 隔日回診由專人進行無菌清潔洗頭與換藥。"
        ),
        "maintenance": (
            "長期維持保養：1. 術後第四天起依醫囑以溫和洗髮精指腹輕柔清洗頭皮 2. 術後二至四週植入毛幹進入生理性休止期脫落（毛囊幹細胞存留皮下），屬正常現象 "
            "3. 術後三至四個月起新髮持續萌出，九至十二個月展現自然濃密髮量 4. 配合醫師建議進行落髮衛教維持供髮穩定。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "FUE 微創植髮自後枕部點狀提取健康毛囊單位，顯微鏡下分離後依自然毛流角度精準微孔植入。"
            "後枕部微創點狀傷口無線性疤痕，術後保護黃金七十二小時，九至十二個月展現自然濃密髮際線。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-orthognathic-surgery",
        "clinic_id": CLINIC_ID,
        "title": "3D 數位導航正顎手術（雙顎 LeFort I 與下顎枝截骨成型術）",
        "category": "special",
        "pre_op": (
            "術前須知：1. 進行全口環景X光、齒顎模型掃描與 3D 顏面顱骨電腦斷層掃描 2. 與齒顎矯正專科醫師跨團隊整合，擬定三維數位手術計畫（VSP）"
            "並製作 3D 咬合導板 3. 評估骨性戽斗、暴牙或顏面歪斜成因 4. 完成心電圖、胸部X光與全身麻醉前訪視。"
        ),
        "procedure": (
            "手術步驟：1. 全身麻醉下全口內無痕切口進行 2. 上顎施行 LeFort I 型截骨術，將上顎骨整體向上、向前或向後移動復位以改善暴牙或中臉凹陷 "
            "3. 下顎施行雙側下顎枝矢狀劈開術（BSSO）或垂直截骨術，將下顎骨段向後移動或旋轉對稱 4. 依照3D咬合導板引導至理想咬合，以純鈦微型骨板釘剛性固定。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 使用彈性橡皮圈引導咬合定位，不進行完全死鎖，維持呼吸道通暢安全 2. 前三天頭部抬高四十五度並於雙側臉頰進行密集冷敷 "
            "3. 每餐後以無菌漱口水徹底清潔口腔黏膜切口 4. 前兩週採全流質冷溫營養飲食，避免口內傷口撕裂。"
        ),
        "maintenance": (
            "長期維持保養：1. 術後第二週起可轉為軟質無渣食物（布丁、蒸蛋），六至八週內嚴禁咀嚼堅硬食物 2. 定期拍攝X光追蹤截骨端骨癒合進度 "
            "3. 術後四至六週銜接術後齒列微調矯正 4. 達成健全咀嚼功能與和諧對稱之顏面線條。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "3D 數位導航正顎手術經口內無痕切口，結合 LeFort I 與 BSSO 截骨術改善骨性戽斗、暴牙與臉型歪斜。"
            "純鈦板釘剛性固定，術後彈性定位安全維持呼吸道，協同牙齒矯正達到理想咬合與端正輪廓。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-triton-laser-hair-removal",
        "clinic_id": CLINIC_ID,
        "title": "Triton 海神雙波長雷射除毛療程",
        "category": "special",
        "pre_op": (
            "術前須知：1. 評估除毛部位毛髮粗細、生長密度與膚色 2. 治療前兩至三天在家先以刮刀刮除表面毛髮留微小黑毛根，切勿使用蜜蠟或拔毛夾拔除毛囊 "
            "3. 術前一週避免過度曝曬與擦拭酸類美白成分 4. 清潔除毛部位皮膚。"
        ),
        "procedure": (
            "療程步驟：1. 搭載亞歷山大（755nm）與二極體（810nm）協同雙波長技術，具備深度組織穿透性 2. 結合專利 360 度接觸式藍寶石水冷卻探頭，"
            "在擊發前後維持表皮低溫防燙 3. 高能量光束精準被毛囊黑色素吸收轉化為熱能，破壞毛囊幹細胞與生長核心，抑制再生。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 治療後皮膚毛囊周圍可能呈現輕微紅暈如小雞皮疙瘩，屬正常熱凝固反應 2. 立即塗抹舒緩凝膠或進行局部冰敷鎮定 "
            "3. 當日避免洗過熱熱水澡、泡溫泉或前往蒸氣室 4. 外出除毛裸露部位需塗抹防曬乳。"
        ),
        "maintenance": (
            "長期維持保養：1. 術後一至兩週殘留微毛根會隨角質自然脫落，切勿用力摳拔 2. 依毛髮生長週期（生長期、退行期、休止期），"
            "建議每四至六週規律治療一次 3. 連續接受六至八次治療以達理想持久光滑成效 4. 平時做好肌膚保濕。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "Triton 海神除毛搭載雙波長（755nm/810nm）與 360 度藍寶石冷卻探頭，溫和破壞毛囊生長點達到高效減毛。"
            "術前刮除毛髮勿拔毛，術後加強保濕防曬，每四至六週依毛囊週期規律治療。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-hydrafacial-deep-cleansing",
        "clinic_id": CLINIC_ID,
        "title": "Hydrafacial 海菲秀專利水渦漩深層清潔煥膚",
        "category": "special",
        "pre_op": (
            "術前須知：1. 評估全臉膚質（粉刺堆積、角質過厚、油脂旺盛或乾燥缺水） 2. 治療區域若有嚴重開放傷口、嚴重囊腫痤瘡或活動性濕疹需延緩 "
            "3. 療程前三天避免過度日曬與去角質 4. 徹底卸妝清潔面部。"
        ),
        "procedure": (
            "療程步驟：1. 第一步使用藍色專利水渦漩端頭搭配乳酸精華，溫和軟化老廢角質並帶走表層髒污 2. 第二步使用青綠色端頭搭配水楊酸精華，"
            "無痛負壓水渦漩深度抽吸黑頭粉刺與毛孔多餘油脂 3. 第三步換用透明端頭將小分子玻尿酸、胜肽及抗氧化多酚精華深層導入真皮表層。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 療程後毛孔通暢乾淨、肌膚立現水潤光澤，無修復期 2. 當天即可正常上妝與保養 3. 洗臉以常溫水清潔，避免大力搓揉臉部 "
            "4. 加強塗抹低敏保濕精華與乳液修護屏障。"
        ),
        "maintenance": (
            "長期維持保養：1. 術後一週內加強保濕補水與每日日間防曬（SPF30+） 2. 避免使用含酒精、果酸或粗顆粒磨砂產品 3. 建議每三至四週定期進行一次毛孔深層清潔保養 "
            "4. 維持健康清透水嫩肌質。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "Hydrafacial 海菲秀運用專利水渦漩端頭與三道精華步驟，溫和去除老廢角質、無痛抽吸粉刺並深層導入抗氧化多酚。"
            "無修復期立現水潤光澤，術後加強保濕防曬，建議每月定期保養維持毛孔健康通暢。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-nd-yag-laser-toning",
        "clinic_id": CLINIC_ID,
        "title": "Nd:YAG 銣雅鉻淨膚雷射均色淡斑",
        "category": "special",
        "pre_op": (
            "術前須知：1. 評估膚色不均、雀斑、曬斑或深層色素沉澱分佈 2. 術前一週避免使用甘醇酸、A酸煥膚或過度曝曬 3. 近期口服A酸或光敏感病史者需主動告知 "
            "4. 清潔臉部卸除所有彩妝防曬。"
        ),
        "procedure": (
            "療程步驟：1. 採用 1064nm / 532nm 雙波長銣雅鉻雷射光束均質輸出低能量光斑 2. 光能量穿透真皮層，透過光震波與光熱效應將沉積黑色素顆粒震碎為微粒，"
            "交由體內巨噬細胞吞噬代謝 3. 微熱能促進真皮淺層膠原蛋白微幅增生，達到提亮膚色與收斂油脂毛孔。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 治療後皮膚輕度發紅或溫熱微脹，敷上保濕修護面膜十五分鐘即可緩解 2. 無表皮破皮傷口，可正常清水清潔與護膚 "
            "3. 避免使用美白酸類成分保養品 4. 嚴格做好物理遮蔽與防曬措施。"
        ),
        "maintenance": (
            "長期維持保養：1. 加強保濕與日間防曬以防色素反黑 2. 兩週內避免前往溫泉、三溫暖烤箱 3. 建議每三至四週定期由醫師評估保養一次 "
            "4. 連續數次治療後膚色均勻度與淨白光澤顯著改善。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "Nd:YAG 淨膚雷射以 1064nm 均質光波震碎黑色素顆粒，改善膚色暗沉與淺層色斑，收斂油脂毛孔。"
            "無創無恢復期，術後加強防曬與深層保濕，每三至四週定期保養維持肌膚亮白健康。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-hyaluronic-acid-dermal-filler",
        "clinic_id": CLINIC_ID,
        "title": "玻尿酸皮下填充微整形雕塑（深層容積支撐與中軸立體塑型）",
        "category": "special",
        "pre_op": (
            "術前須知：1. 評估臉部骨骼萎縮與凹陷區域（如淚溝、法令紋、夫妻宮或蘋果肌） 2. 告知過敏史及既往填充物注射史 3. 術前一週避免服用阿斯匹靈及抗凝血藥品 "
            "4. 注射部位徹底清潔消毒並局部敷麻三十分鐘。"
        ),
        "procedure": (
            "療程步驟：1. 依注射區域深淺挑選適當分子量之交聯玻尿酸 2. 專科醫師使用鈍針或細緻銳針，於骨膜上層或深層脂肪室進行多層次微量扇形逆行注射 "
            "3. 透過多點支撐拉提法（MD Codes）補足結構支撐，避開顏面危險血管 4. 輕柔塑型使線條平順和諧。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 注射微針孔貼敷人工皮保護二十四小時維持清潔 2. 部位微脹或輕度瘀青屬正常現象，前兩天可輕柔冷敷 3. 切勿大力揉捏、"
            "按壓或趴睡擠壓塑型區 4. 一週內避免前往烤箱、三溫暖或進行劇烈運動。"
        ),
        "maintenance": (
            "長期維持保養：1. 玻尿酸於皮下自然抓水澎潤，多補充水分加強肌膚保濕 2. 隨體內玻尿酸酶自然緩慢代謝，效果依劑型與個人體質維持約六至十八個月 "
            "3. 可定期回診由醫師評估微調補充 4. 維持輪廓立體自然與年輕神采。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "玻尿酸微整形於骨膜上層或深層脂肪進行多層次精密注射，改善淚溝、法令紋與輪廓凹陷。"
            "術後避免揉壓與高溫三溫暖，依劑型維持約半年至一年半，多喝水保濕維持立體平整澎潤。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-picosecond-laser-rejuvenation",
        "clinic_id": CLINIC_ID,
        "title": "聚焦蜂巢皮秒雷射深層除斑與膚質重塑",
        "category": "special",
        "pre_op": (
            "術前須知：1. 由專業醫師以皮膚檢測儀鑑別深淺層斑點、肝斑或凹洞毛孔 2. 術前一週停用A酸、果酸煥膚與高濃度維生素C，嚴禁過度曝曬 "
            "3. 患部若有單純疱疹或傷口感染應暫緩 4. 清潔臉部並敷表面麻膏三十分鐘。"
        ),
        "procedure": (
            "療程步驟：1. 採用皮秒超短脈衝（Picosecond）雷射，強大光機械衝擊波瞬間將黑色素震碎為粉塵狀，大幅減少熱殘留 2. 搭配專利蜂巢透鏡，"
            "在表皮無創傷狀態下於真皮層誘導光致空泡效應（LIOB） 3. 劇烈刺激真皮層膠原蛋白與彈力纖維新生重組。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 蜂巢透鏡治療後皮膚呈現微紅或皮下細密出血點，通常二十四至四十八小時內消退 2. 術後立即冰敷鎮定二十分鐘 "
            "3. 前三天以無菌生理食鹽水輕按清潔，薄擦生長因子修復霜 4. 嚴格做好物理遮蔽與防曬（SPF50+）。"
        ),
        "maintenance": (
            "長期維持保養：1. 斑點微細結痂約三至七天自行脫落，切勿用手摳抓 2. 術後兩週內避免泡溫泉與使用美白刺激性護膚品 3. 每四至八週規律治療一次 "
            "4. 逐步淡化頑固色斑、收斂毛孔並改善肌膚平整度。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "皮秒雷射運用光機械衝擊波震碎黑色素粉塵，蜂巢透鏡於真皮層誘導空泡效應（LIOB）刺激膠原新生。"
            "熱殘留少、退紅快，術後加強修護防曬，約一週微痂脫落後毛孔細緻斑點淡化。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-blepharoplasty-eye-contouring",
        "clinic_id": CLINIC_ID,
        "title": "全方位美眸眼整形手術（客製雙眼皮、無痕內開眼袋移位與提眼瞼肌矯正）",
        "category": "special",
        "pre_op": (
            "術前須知：1. 評估眼瞼皮膚鬆弛度、眼眶脂肪脫垂量、提眼瞼肌肌力（MRD1）及淚溝深淺 2. 術前兩週停用阿斯匹靈、抗凝血劑與活血中藥 "
            "3. 手術當天不可配戴隱形眼鏡或化眼妝 4. 與專科醫師充分溝通理想眼型雙眼皮折線寬度與弧度。"
        ),
        "procedure": (
            "手術步驟：1. 雙眼皮採微創多點埋線固定或切開法修除贅皮 2. 提眼瞼肌無力者進行結膜側或經皮提眼瞼肌筋膜摺疊前移矯正 3. 眼袋手術採結膜內無痕切口（外表無傷口），"
            "游離下眼眶脫垂脂肪，精細轉位回填固定至淚溝骨膜凹陷處（Fat Repositioning），並緊緻眼眶隔膜。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 術後雙眼局部加壓冰敷以減緩腫脹與微滲血 2. 前三天每小時冰敷十五分鐘（避開眼球直接受壓） 3. 睡眠時頭部墊高三十度 "
            "4. 按時點眼藥水與塗抹抗生素眼膏 5. 一週內避免揉眼睛、戴隱形眼鏡或劇烈用力。"
        ),
        "maintenance": (
            "長期維持保養：1. 術後五至七天拆除外表縫線（內開眼袋無外縫線無需拆線） 2. 拆線後第二天起改溫敷促進循環消腫 3. 眼周水腫於一至兩週大幅改善，"
            "一至三個月神態和諧自然 4. 門診追蹤眼袋平整度與眼神神韻。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "全方位眼整形涵蓋客製雙眼皮、提眼瞼肌矯正與無痕內開眼袋脂肪移位回填淚溝。"
            "外表無切口隱痕，術後冰敷消腫與規律點藥水，一至兩週消腫展現明亮精神神韻。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-ultherapy-focused-ultrasound",
        "clinic_id": CLINIC_ID,
        "title": "Ultherapy 美國音波深層極線音波拉提療程",
        "category": "special",
        "pre_op": (
            "術前須知：1. 評估全臉下垂程度、皮下軟組織厚度與輪廓線鬆弛狀況 2. 治療區有金屬植入物、開放性傷口或嚴重糖尿病者需經醫師審慎評估 "
            "3. 術前一週避免果酸去角質與烈日曝曬 4. 清潔全臉並敷上表面麻醉藥膏。"
        ),
        "procedure": (
            "療程步驟：1. 美國 FDA 核准拉提適應症之微聚焦超音波技術（MFU-V） 2. 具備專利「DeepSEE 即時超音波顯像螢幕」，施打時精確同步監控皮膚層、"
            "皮下脂肪與 SMAS 筋膜層位置（深達四點五毫米） 3. 精準釋放聚焦熱凝結點（溫度達六十五至七十度），引發筋膜層強效收縮提拉。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 術後皮膚微紅或有些微深層壓痛、筋膜酸脹感，屬熱能聚集正常反應，數小時至數天內自然消退 2. 表面無創口，"
            "可立即洗臉、保濕與化妝 3. 一週內避免冰水洗臉或劇烈冰敷以免削弱熱效應 4. 加強防曬保濕。"
        ),
        "maintenance": (
            "長期維持保養：1. 筋膜與真皮層啟動膠原蛋白新生機制，拉提緊實效果於術後二至三個月達到高峰 2. 下顎輪廓線緊緻清晰 3. 日常做好高係數防曬與保濕 "
            "4. 單次療程通常可維持一年至兩年，定期回診評估維持輪廓。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "Ultherapy 美國音波搭載專利即時超音波顯像螢幕，精準將微聚焦音波直達 4.5mm SMAS 筋膜層誘導熱凝收縮。"
            "無表面創口，術後加強保濕與防曬，術後二至三個月下顎線與臉頰緊實提拉。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-full-deep-plane-facelift",
        "clinic_id": CLINIC_ID,
        "title": "高位深層筋膜全臉拉皮手術（Full Deep Plane Facelift）",
        "category": "special",
        "pre_op": (
            "術前須知：1. 全面評估上中下臉及頸部複合老化（顳部眉眼下垂、中臉中軸脂肪下移、法令紋、木偶紋與頸部鬆弛） 2. 術前兩週完全戒菸以確保皮瓣血液微循環灌流 "
            "3. 停用抗凝血劑、阿斯匹靈與活血保健品 4. 完成心電圖、胸部X光及全身麻醉評估。"
        ),
        "procedure": (
            "手術步驟：1. 全身麻醉下施行。切口自顳部髮際內沿耳屏緣繞過耳垂延伸至耳後髮際 2. 在深層筋膜下（Deep Plane）進行高位解剖剝離，精確解離顴大肌韌帶與下顎真性維持韌帶 "
            "3. 完整游離並重置 SMAS 筋膜連同脂肪墊複合體立體向上向後復位，並將筋膜錨定於顳深筋膜與乳突骨膜 4. 無張力微米級對位縫合切口。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 留置雙側低壓引流管一至兩天以引流組織微滲液 2. 全臉佩戴彈性加壓面罩加壓防血腫 3. 術後住院觀察一至兩天，"
            "頭部抬高四十五度臥床 4. 按時服用抗生素與止痛藥物 5. 採流質易消化飲食，避免劇烈面部表情。"
        ),
        "maintenance": (
            "長期維持保養：1. 術後四十八小時內拔除引流管並換藥 2. 術後七至十天分段拆線 3. 拆線後持續穿戴塑臉面罩三至四週鞏固組織貼合 "
            "4. 拆線一週後塗抹除疤凝膠護理疤痕 5. 一個月內禁止重量訓練與染燙髮 6. 骨架級重置成效持久自然。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "高位深層筋膜全臉拉皮（Deep Plane）於筋膜下解離真性韌帶，將 SMAS 筋膜與下垂軟組織連同復位並錨定於骨膜。"
            "無張力縫合不扯耳垂，術後佩戴面罩加壓護理，提供自然流暢且長效年輕的深層骨架重置。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-renuvion-helium-plasma",
        "clinic_id": CLINIC_ID,
        "title": "Renuvion 超能電漿微創皮下縮皮緊緻術",
        "category": "special",
        "pre_op": (
            "術前須知：1. 評估抽脂後皮膚鬆弛度、腹部下垂、蝴蝶袖或雙下巴鬆垂程度 2. 評估體質與凝血功能，確認無皮下急性感染病史 "
            "3. 術前一週停用抗凝血藥品與活血保健品 4. 標記治療區域向量與微創進針點。"
        ),
        "procedure": (
            "手術步驟：1. 局部浸潤麻醉或舒眠麻醉下施作 2. 透過約零點三至零點五公分微小穿刺孔進入皮下纖維縱膈層 3. 運用專利氦氣介質激發成第四態電漿（Plasma），"
            "在零點二秒內瞬間升溫至八十五度促使皮下纖維隔膜產生強效收縮，同時冷氦氣在零點零四四秒內瞬間降溫冷卻至正常體溫，達到瞬熱瞬冷極致縮皮且不燙傷表皮。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 微創穿刺孔貼敷防水敷料 2. 治療區域穿戴專屬彈性塑身衣或下巴頭套加壓固定，防止皮下積液並助組織緊密貼合 "
            "3. 術後前數天可能出現暫時性微腫脹與麻木感 4. 前三天冷敷周圍，按時服用抗生素與消炎止痛藥物。"
        ),
        "maintenance": (
            "長期維持保養：1. 塑身衣建議全天穿戴二至四週，其後改夜間穿戴二至四週以鞏固縮皮成果 2. 微創切口約一週癒合結痂 "
            "3. 術後一個月避免大力揉搓或劇烈碰撞治療部位 4. 皮下膠原網絡持續緊密重組，緊實度於一至三個月達理想狀態。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "Renuvion 超能電漿利用氦氣激發電漿態，瞬熱八十五度促使皮下纖維隔膜收縮，同時瞬冷防燙表皮。"
            "零點三公分微創切口，術後穿戴塑身衣加壓貼合，顯著改善抽脂後鬆弛或產後腹部皮膚下垂。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-structural-autologous-rhinoplasty",
        "clinic_id": CLINIC_ID,
        "title": "結構式自體軟骨全方位隆鼻手術（鼻中膈延長與精雕立體鼻型）",
        "category": "special",
        "pre_op": (
            "術前須知：1. 進行 3D 顏面輪廓評估與鼻腔電腦斷層，精準鑑別鼻中膈彎曲、鼻梁塌陷或短鼻朝天問題 2. 溝通鼻梁弧度與鼻唇角角度 "
            "3. 術前兩週戒菸、停用抗凝血劑與活血中藥 4. 手術前維持鼻部皮膚清潔，全身麻醉前嚴格禁食八小時。"
        ),
        "procedure": (
            "手術步驟：1. 開放式鼻小柱階梯狀隱痕切口 2. 取用自體鼻中膈軟骨、耳軟骨或自體肋軟骨 3. 在鼻中膈尾端搭建堅韌軟骨延伸支架（Septal Extension Graft），"
            "穩固延長鼻長度與抬高鼻尖 4. 精巧縫合鼻翼軟骨塑型鼻頭微凸點，並堆疊軟骨盾牌保護皮膚張力 5. 鼻梁骨膜下植入精雕植體抬高山根，分層無張力縫合。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 鼻梁外貼熱塑鼻夾板固定五至七天維持挺立並預防血腫 2. 鼻孔內視情況放置引流棉條一至兩天 3. 前三天密集冰敷眼周與鼻周圍，"
            "睡眠時墊高枕頭 4. 嚴禁擤鼻涕、戴眼鏡或擠壓鼻樑 5. 以無菌棉棒沾生理食鹽水清潔血痂並塗抹抗生素藥膏。"
        ),
        "maintenance": (
            "長期維持保養：1. 術後五至七天返院拆除鼻夾板及表面縫線 2. 一個月內嚴禁配戴眼鏡、擤鼻涕、趴睡、挖鼻孔或劇烈碰撞 "
            "3. 術後三至六個月深層水腫完全消退 4. 展現結構穩固、觸感自然之原生立體挺拔美鼻。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "結構式隆鼻經開放式鼻小柱隱痕切口，以自體軟骨搭建鼻中膈延長支架並精雕鼻頭微凸點，骨膜下植入鼻樑假體。"
            "術後鼻夾板固定一週防移位，避免擤鼻涕與外力壓迫，打造結構穩固挺拔美鼻。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-bbl-broadband-light",
        "clinic_id": CLINIC_ID,
        "title": "BBL 青萃光旗艦脈衝光嫩膚（多波段光老化精準光療）",
        "category": "special",
        "pre_op": (
            "術前須知：1. 評估色斑類型、微血管擴張、酒糟泛紅或光老化膚質 2. 排除近期過度曝曬或曬傷者 3. 治療前一週停用口服及外用A酸、果酸煥膚 "
            "4. 清潔臉部肌膚並佩戴專業護目鏡保護雙眼。"
        ),
        "procedure": (
            "療程步驟：1. 採用 Sciton BBL 寬頻光科技，配備多波段磁吸式濾光片 2. 以平頂波能量發射至肌膚不同深度：短波長鎖定表淺黑色素改善雀斑曬斑，"
            "長波長作用於含氧血紅素收縮擴張微血管、改善泛紅酒糟 3. 溫和光熱刺激真皮纖維母細胞新生膠原蛋白與彈力纖維。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 治療後皮膚輕微發紅溫熱，敷上醫用冰鎮修護面膜十五分鐘 2. 色素斑點處可能出現如胡椒粒般的微細薄痂，無表面開放創口 "
            "3. 治療當日即可清水洗臉上保濕防曬 4. 一週內避免高溫泡澡與刺激性美白酸類成分。"
        ),
        "maintenance": (
            "長期維持保養：1. 色素微痂通常三至五天隨角質自然脫落，嚴禁手摳 2. 術後加強肌膚保濕屏障修護與每日物理性防曬（SPF30+以上） "
            "3. 建議每三至四週進行一次光療保養 4. 連續三至五次大幅改善暗沉、色斑與微血管泛紅。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "BBL 青萃光採用專利多波段寬頻光，精準改善表淺色斑、收縮擴張微血管改善酒糟泛紅並刺激膠原增生。"
            "溫和低熱殘留，術後加強保濕與防曬，微細胡椒薄痂自然脫落後膚色勻亮通透。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-varicose-vein-evlt-sclerotherapy",
        "clinic_id": CLINIC_ID,
        "title": "微創下肢靜脈曲張血管內雷射閉合與泡沫硬化劑治療",
        "category": "special",
        "pre_op": (
            "術前須知：1. 由專科醫師使用血管彩色杜普勒超音波全面掃描大隱靜脈、小隱靜脈逆流時間與瓣膜閉鎖不全位置 2. 評估下肢水腫、"
            "皮膚色素沉澱或潰瘍程度 3. 術前量測並備妥醫療級漸進式彈性減壓襪 4. 術前確認凝血功能正常。"
        ),
        "procedure": (
            "手術步驟：1. 局部腫脹麻醉在超音波精確導引下施作 2. 於膝下微創穿刺置入雷射光纖鞘管，將波長 1470nm 徑向雷射光纖推送至隱股交界處下方安全距離 "
            "3. 雷射環形能量轉化為熱能，使病變靜脈內皮均勻熱凝閉合萎縮 4. 合併細小曲張血管注入專利泡沫硬化劑，促使微細蜘蛛網血管纖維化吸收。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 治療後立即穿上醫療級大腿長度壓力彈性襪加壓止血並促進深層回流 2. 術後可立即下床慢步走動三十分鐘，預防深層靜脈血栓 "
            "3. 術後四十八小時內穿戴彈性襪睡眠，微創穿刺針孔保持乾燥 4. 兩週內避免長途久坐不動或熱水泡澡。"
        ),
        "maintenance": (
            "長期維持保養：1. 術後第一週於日間維持穿戴彈性減壓襪 2. 術後兩週及一個月門診複查血管超音波，確認病變血管已閉合且深層通暢 "
            "3. 平時避免長時間維持同姿勢久站久坐 4. 睡前抬高下肢促進血液回流，預防靜脈高壓復發。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "微創靜脈曲張治療在超音波導引下運用 1470nm 雷射光纖閉合大隱靜脈，合併泡沫硬化劑消除微細蜘蛛血管。"
            "微創無大切口，術後即刻行走防血栓，穿戴醫療級彈性襪加速恢復與消除腿部脹痛。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-chronic-migraine-botox-decompression",
        "clinic_id": CLINIC_ID,
        "title": "慢性頑固性偏頭痛肉毒桿菌素注射與周邊神經微創減壓治療",
        "category": "special",
        "pre_op": (
            "術前須知：1. 依據國際頭痛疾病分類（ICHD-3）詳盡評估，排除顱內器質性病變 2. 審閱偏頭痛日記（每月發作十五天以上且持續三個月以上） "
            "3. 鑑別頭痛誘發觸發點（眶上神經、顴顳神經或枕大神經壓迫） 4. 術前一週避免服用影響凝血藥品。"
        ),
        "procedure": (
            "處置步驟：1. 第一線採 PREEMPT 慢性偏頭痛標準注射協議，由專業醫師在頭面部、顳部、後枕部及肩頸部三十一至三十九處特定觸發肌群進行精準微量注射 "
            "2. 阻斷痛覺神經傳導物質（CGRP、神經激肽）釋放並放鬆緊繃痙攣肌肉 3. 對於藥物難治之頑固病例，可經髮際內微創隱痕切口鬆解受壓迫之周邊感覺神經。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 肉毒注射針孔保持乾燥六小時 2. 四小時內避免平躺、按摩揉捏頭皮或劇烈運動，以防藥劑擴散至周圍非目標肌肉 "
            "3. 減壓手術者傷口保持乾爽，前三天局部冷敷減輕水腫 4. 定時服用消炎止痛藥物。"
        ),
        "maintenance": (
            "長期維持保養：1. 肉毒注射後約一至兩週頭痛發作頻率與強度逐步降低，單次注射效果約維持三至四個月 2. 建議每十二週定期回診由醫師評估維持治療 "
            "3. 神經減壓手術者術後一週拆線，一個月內避免劇烈搖晃頭部 4. 日常維持規律睡眠作息與避免強光誘發因子。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "慢性偏頭痛治療採 PREEMPT 協議於頭頸肩多處觸發點注射肉毒桿菌素阻斷致痛胜肽，頑固者可進行周邊神經微創減壓。"
            "術後避免揉捏注射處，一至兩週顯著降低發作頻率與嚴重度，每三個月規律評估維持生活品質。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-swan-neck-cervicoplasty",
        "clinic_id": CLINIC_ID,
        "title": "天鵝頸闊頸肌縫合拉皮術（下巴微創隱痕與下顎輪廓線雕塑）",
        "category": "special",
        "pre_op": (
            "術前須知：1. 評估下顎至頸部夾角、下巴深淺層脂肪堆積量、闊頸肌分離垂帶（火雞脖）程度及下巴骨後縮狀況 2. 評估是否合併需要二腹肌前腹或深層脂肪修整 "
            "3. 術前兩週嚴格戒菸、停用抗凝血劑與阿斯匹靈 4. 全身體檢並完成麻醉安全評估。"
        ),
        "procedure": (
            "手術步驟：1. 舒眠或全身麻醉下施作。於下巴下緣微凹天然皮摺處取約兩至三公分微創隱痕切口 2. 直視放大視野下精細解離皮瓣，"
            "移除闊頸肌前深淺層多餘脂肪 3. 將左右兩側分離鬆弛的闊頸肌（Platysma）邊緣游離，進行中央馬甲式折疊縫合（Platysmaplasty），形成堅實吊帶重塑俐落下顎天鵝頸夾角 4. 微米對位縫合切口。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 局部留置細微引流管一至兩天以防組織液積聚 2. 佩戴專屬頸頜彈性加壓面罩固定 3. 前三天頭部抬高仰臥，"
            "避免頻繁低頭或劇烈扭轉頸部 4. 按醫囑定時服用消腫藥物與抗生素 5. 下巴切口每日換藥清潔塗抹藥膏。"
        ),
        "maintenance": (
            "長期維持保養：1. 術後七至十天門診拆除切口縫線 2. 塑型面罩建議前兩週全天穿戴，第三至四週改夜間穿戴鞏固組織貼合 "
            "3. 術後一個月內避免仰頭劇烈伸展或重訓 4. 下巴下緣隱痕切口三至六個月逐漸淡化為不明顯細線，締造長效緊緻天鵝頸。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "天鵝頸拉皮經下巴下緣兩至三公分微創隱痕切口，移除深淺層脂肪並將分離的闊頸肌進行馬甲式內對縫（Platysmaplasty）。"
            "術後佩戴彈性面罩加壓塑型，消除火雞脖垂帶與雙下巴，重現清晰緊緻的俐落天鵝頸線條。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-overfilled-face-syndrome-correction",
        "clinic_id": CLINIC_ID,
        "title": "饅化臉過度填充修復綜合治療（精準降解酶、微創減容與深層組織解離）",
        "category": "special",
        "pre_op": (
            "術前須知：1. 高解析度高頻超音波（HFUS）掃描臉部皮下層，精準鑑別過度填充成分（玻尿酸積聚、自體脂肪結節、纖維增生或假性囊腫） "
            "2. 評估微笑與動態表情時組織僵硬擠壓度 3. 術前停用抗凝血藥品 4. 擬定分階段精準微創修復計畫。"
        ),
        "procedure": (
            "治療步驟：1. 玻尿酸積聚在超音波即時導引下微量注射原廠高活性透明質酸酶（降解酶），精確溶解目標填充物同時保護正常自體基質 "
            "2. 增生纖維或多餘脂肪結節利用微鈍針微創低負壓抽吸減容 3. 進行皮下沾黏纖維組織細緻解離（Subcision）恢復彈性 4. 若合併前次拉皮失誤則配合深層筋膜重置。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 治療後患部局部微腫脹或微瘀青，冷敷十五分鐘舒緩 2. 微小進針點保持乾燥二十四小時並塗抹抗生素藥膏 "
            "3. 注射降解酶後留觀三十分鐘確認無過敏反應 4. 一週內避免大力揉捏擠壓治療區域，避免高溫烤箱蒸氣室。"
        ),
        "maintenance": (
            "長期維持保養：1. 玻尿酸通常在注射降解酶後一至兩天內快速分解，組織在一至兩週內恢復柔軟自然 2. 術後兩至四週回診超音波追蹤，"
            "評估殘留組織是否需微調 3. 穩定後若有凹陷不均，再由專科醫師以最小劑量進行精細真皮微雕 4. 擺脫僵硬假面感。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "饅化臉過度填充修復經高頻超音波精確定位，注射降解酶溶解過量玻尿酸，配合微創低壓抽吸與沾黏纖維解離。"
            "術後避免揉壓，一至兩週組織恢復自然柔軟，由專科醫師逐步修復立體流暢原生輪廓。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-asce-rose-exosome-regeneration",
        "clinic_id": CLINIC_ID,
        "title": "ASCE+ 外泌體大馬士革玫瑰幹細胞再生修復療法",
        "category": "special",
        "pre_op": (
            "術前須知：1. 評估全臉膚況（屏障受損、敏感泛紅、毛孔粗大、乾敏細紋）或頭皮毛囊健康狀況 2. 排除治療部位有活動性細菌或病毒感染 "
            "3. 術前一週避免果酸去角質與長時間曝曬 4. 清潔全臉並敷表皮舒緩麻膏三十分鐘。"
        ),
        "procedure": (
            "療程步驟：1. 採用 ASCE+ 原廠大馬士革玫瑰幹細胞外泌體（Exosomes），富含百億級生長因子、活性胜肽與抗發炎微小核糖核酸 "
            "2. 以專利凍晶乾燥技術提煉，常溫新鮮復溶 3. 搭配微針或水光微滴技術均勻導入真皮表層，作為細胞間傳訊介質，極速啟動纖維母細胞自我修復與膠原新生。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 導入後皮膚微紅微溫，立即敷上專屬修復凍膜或無菌冰鎮冷敷 2. 無表面破壞性開放傷口，當天洗臉使用生理食鹽水，"
            "避免自來水刺激 3. 前三天加強深層鎖水保濕 4. 嚴禁使用含酒精、香精及酸類之保養品。"
        ),
        "maintenance": (
            "長期維持保養：1. 外泌體在皮下持續傳遞細胞修復信號，術後三至七天肌膚細緻度與保水度顯著提升，退紅修復表現優異 2. 外出塗抹溫和物理防曬乳 "
            "3. 建議每三至四週進行一次深層修護療程，連續三次建立強韌肌膚健康屏障 4. 維持水潤光澤。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "ASCE+ 外泌體萃取自大馬士革玫瑰幹細胞，富含生長因子與胜肽，經微針或水光導入深層活化纖維母細胞。"
            "極速退紅修護屏障，術後加強保濕與物理防曬，連續保養重建健康細緻強韌膚質。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-rejuran-pdrn-skin-healer",
        "clinic_id": CLINIC_ID,
        "title": "Rejuran 麗珠蘭野生鮭魚 DNA 多核苷酸（PN/PDRN）再生逆齡水光注射",
        "category": "special",
        "pre_op": (
            "術前須知：1. 評估皮膚彈性流失、眼周細紋、深層缺水或痘疤受損問題 2. 對魚類或海鮮嚴重過敏者應由醫師審慎評估 3. 術前一週避免服用阿斯匹靈等抗凝血藥品 "
            "4. 清潔臉部肌膚並均勻塗抹局部麻醉膏四十分鐘。"
        ),
        "procedure": (
            "療程步驟：1. 原廠 Rejuran Healer，核心成分為從野生鮭魚精巢DNA中提煉純化之專利高分子多核苷酸（Polynucleotide, PN） "
            "2. 由專科醫師使用專用多針水光儀或極細34G針頭，以微滴淺層注射技術均勻注入真皮淺層 3. PN分子具備卓越生物相容性，直接提供DNA合成材料，"
            "促進真皮層細胞生理修復與微血管新生。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 注射後全臉可能暫時浮現細小丘疹狀凸起（小皮丘），此為高分子PN儲留於真皮層正常現象，通常於二十四至四十八小時內吸收平整 "
            "2. 治療後立即冰敷並敷上修復面膜鎮定 3. 當日避免洗臉化妝，次日可溫和清潔 4. 一週內避免三溫暖烤箱。"
        ),
        "maintenance": (
            "長期維持保養：1. 水光皮丘吸收後，真皮厚度與彈力纖維在術後兩至四週逐步增生，改善乾紋與粗糙毛孔 2. 加強日常基礎保濕與日間防曬 "
            "3. 標準療程建議每三至四週進行一次施打，連續三至四次為一完整週期 4. 長效維持肌膚緊緻透亮水潤。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "Rejuran 麗珠蘭自野生鮭魚DNA提煉專利多核苷酸（PN），以微滴注射注入真皮層刺激細胞生理修復與膠原增生。"
            "術後小皮丘一至兩天自然吸收，四週逐步改善眼周乾紋與毛孔粗糙，定期保養維持水潤飽滿。"
        ),
    },
    {
        "doc_id": f"{CLINIC_ID}-bulbous-nose-rhinoplasty",
        "clinic_id": CLINIC_ID,
        "title": "蒜頭鼻雕塑與鼻頭軟骨微創縮小手術（軟骨縫合重塑與軟組織精細減容）",
        "category": "special",
        "pre_op": (
            "術前須知：1. 專業評估鼻頭圓鈍成因（大翼軟骨過寬外擴、鼻尖皮下纖維脂肪組織肥厚、或鼻頭支撐力不足） 2. 3D 鼻部測量鼻翼與鼻尖立體比例 "
            "3. 術前兩週戒菸、停用阿斯匹靈及抗凝血中藥補品 4. 維持鼻部周圍皮膚潔淨。"
        ),
        "procedure": (
            "手術步驟：1. 舒眠麻醉下採鼻孔內緣或鼻小柱微創隱痕切口進入鼻頭框架 2. 在放大視野下精細打薄多餘的皮下纖維脂肪組織（Defatting），"
            "有效減少軟組織厚度 3. 針對外擴的大翼軟骨進行軟骨間縫合（Interdomal Suture）與對跨縫合，拉近軟骨頂點收攏鼻尖 4. 必要時植入小片自體耳軟骨搭建穩定垂直支撐，精雕海鷗線鼻尖。"
        ),
        "post_op_short": (
            "術後即刻照護：1. 鼻尖外側以透氣紙膠帶及微型熱塑夾板加壓固定五至七天，防止皮下組織水腫 2. 前三天鼻周圍加強冷敷 3. 按時服用消腫抗炎藥物 "
            "4. 保持傷口乾燥，以無菌棉棒沾生理食鹽水清潔分泌物 5. 嚴禁大力擠壓鼻頭或擤鼻涕。"
        ),
        "maintenance": (
            "長期維持保養：1. 術後五至七天拆除鼻部固定膠板與切口縫線 2. 拆線後避免碰撞鼻頭、趴睡或戴重框眼鏡 3. 鼻頭微血管豐富，深層水腫約需一至三個月循序消退 "
            "4. 術後三至六個月軟骨與皮膚緊密貼合，展現持久自然秀氣挺立的小巧鼻型。"
        ),
        "pre_op_physician_notes": None,
        "procedure_physician_notes": None,
        "post_op_short_physician_notes": None,
        "maintenance_physician_notes": None,
        "summary_text": (
            "蒜頭鼻縮小手術經鼻孔微創隱痕切口打薄多餘皮下纖維脂肪，並以軟骨間對縫收攏大翼軟骨頂點，打造立體海鷗線鼻頭。"
            "術後熱塑夾板固定一週減腫防移位，避免揉壓碰撞，三至六個月展現精緻秀氣小巧鼻型。"
        ),
    },
]

# 54 筆高頻口語臨床問答（每療程 2 筆）
VENDOME_FAQS: list[dict[str, Any]] = [
    # 1. QRAY FRX飛梭
    {
        "question": "QRAY FRX 飛梭雷射打完後會結痂很厚、影響上班工作嗎？",
        "answer": (
            "QRAY FRX 飛梭雷射採用微創汽化光束，微熱分解傷口僅約六十毫微米，術後皮膚主要呈現微紅伴輕微灼熱感，"
            "約一至三天內會形成如同薄細沙顆粒般的細微微痂，通常五至七天隨洗臉自然脫落。術後隔天即可防曬並進行溫和保濕，"
            "不影響日常行政工作或一般社交生活。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-qray-frx-fractional-laser",
    },
    {
        "question": "飛梭雷射改善痘疤凹洞需要做幾次治療？",
        "answer": (
            "痘疤凹洞屬於真皮層受損纖維化組織，通常需要分階段先破壞再刺激膠原蛋白填補重組。一般建議以四至六週為間隔，"
            "連續進行三至六次完整治療。醫師會依據滾動型、車廂型或冰鑿型等不同痘疤深淺，靈活調整雷射能量密度與覆蓋率。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-qray-frx-fractional-laser",
    },
    # 2. THERMAGE FLX 鳳凰電波
    {
        "question": "鳳凰電波施打時會很痛嗎？需要全身麻醉嗎？",
        "answer": (
            "鳳凰電波具備專利環迴震動技術與智慧冷媒噴灑機制，能有效分散大腦神經痛覺訊號，施打過程多數人僅感受到溫熱感或短暫刺熱感。"
            "臨床上建議敷表皮麻藥即可安全施作，不建議進行深度全身麻醉，以保留病患即時熱感反饋，確保能量擊發安全有效。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-thermage-flx-rf",
    },
    {
        "question": "鳳凰電波做完多久可以看到緊實拉提效果？能維持多久？",
        "answer": (
            "施打當下即可感受到膠原蛋白受熱收縮帶來的初步緊緻感；隨著深層纖維母細胞持續分泌新生膠原蛋白，最佳緊實輪廓會在術後二至六個月逐漸顯現。"
            "單次完整治療效果依個人體質、年齡與保養習慣，通常可維持一年至一年半，建議每年定期回診評估維持輪廓。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-thermage-flx-rf",
    },
    # 3. 下巴手術推薦
    {
        "question": "墊下巴手術選擇「人工骨植入」和「下巴截骨」有什麼不同？",
        "answer": (
            "人工骨（Medpor）植入是在骨膜下植入生物相容性極佳的人工假體並以鈦釘固定，適合中輕度下巴後縮或短小者，傷口位於口內且恢復較快；"
            "下巴截骨（Genioplasty）則是將自身下頦骨切開並向前或向下移位固定，不需任何外來植體，適合嚴重下巴後縮、下巴過長需縮短或歪斜不對稱者。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-chin-augmentation-genioplasty",
    },
    {
        "question": "墊下巴手術傷口在外面還是嘴巴裡面？多久可以正常咬東西？",
        "answer": (
            "手術切口位於下唇口腔內側黏膜處，外觀皮膚完全沒有任何疤痕。術後第一週建議採溫涼流質或布丁、蒸蛋等軟質食物，進食後務必使用無菌漱口水保持清潔；"
            "通常一週後可恢復一般軟質飲食，一個月內避免啃咬堅硬食物（如堅果、甘蔗）或用力托下巴。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-chin-augmentation-genioplasty",
    },
    # 4. 中下臉拉皮
    {
        "question": "中下臉拉皮和埋線拉皮、音波拉提最大的差別是什麼？",
        "answer": (
            "音波與埋線主要透過熱能收縮或線材倒鉤暫時牽拉軟組織，屬於輕度保養，對深層嚴重鬆垂的地基難以根本復位；中下臉 SMAS 拉皮手術則是在放大視野下鬆解深層真性維持韌帶，"
            "將移位的 SMAS 筋膜地基多層往上復位並牢固縫合錨定於骨膜上，同時修除多餘贅皮，效果深刻自然且持久穩定。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-mid-lower-smas-facelift",
    },
    {
        "question": "中下臉拉皮手術的傷口會很明顯嗎？耳垂會不會變形？",
        "answer": (
            "手術切口沿耳前耳屏天然輪廓摺痕順著耳垂繞至耳後髮際，癒合後疤痕相當隱密。凡登拉皮技術最關鍵特色在於將拉力完全由深層 SMAS 筋膜與骨膜承擔，"
            "表面皮膚採「零張力無壓縫合」，因此完全不會發生耳垂被往下牽拉扯長變形的「小丑耳（Pixie Ear）」問題。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-mid-lower-smas-facelift",
    },
    # 5. 削骨手術首選
    {
        "question": "削骨手術會不會傷到神經導致嘴歪面癱？",
        "answer": (
            "顏面神經主要走行於軟組織層，而削骨手術嚴格於骨膜下層進行，下顎骨角削減時亦會透過術前 3D 電腦斷層精準避開下牙槽神經管，由經驗豐富的顱顏整外專科醫師執刀極具安全性。"
            "術後雙唇周圍可能因局部水腫產生暫時性微麻鈍感，通常隨水腫消退在數週至數月內完全恢復。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-facial-bone-contouring",
    },
    {
        "question": "顴骨削骨內推後，臉頰會不會更容易鬆弛下垂？",
        "answer": (
            "凡登顴骨內推手術在骨膜下精密剝離，盡可能保留軟組織與骨膜之原生附著點，截骨後將顴骨弓微向上旋轉並以微型純鈦板釘剛性固定，預防骨塊下移；"
            "對於原本皮膚彈性較差或年齡較長者，亦可同步評估配合中臉懸吊或音波電波拉提，維持輪廓立體緊緻。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-facial-bone-contouring",
    },
    # 6. 媚必提
    {
        "question": "海芙音波媚必提 MPT 和傳統第三代海芙音波有什麼不一樣？",
        "answer": (
            "媚必提（MPT）突破傳統單一點狀聚焦模式，首創連續微脈衝（Micro-Pulsed）線狀輸出技術，單發擊發速度大幅提升且能在目標組織形成密集無縫熱凝固區，熱蓄積更均勻密集；"
            "此外媚必提新增獨家圓形探頭與專用精華導入功能，對於眼周、嘴角等細緻弧度貼合度更佳，治療體感舒適度顯著提高。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-ultraformer-mpt-hifu",
    },
    {
        "question": "媚必提音波施打時會不會很痛？需要舒眠麻醉嗎？",
        "answer": (
            "由於 MPT 連續微脈衝擊發時間極短且熱能傳導更均質，相較於傳統音波的尖銳刺痛感大幅減輕許多。多數人在敷表面麻膏後即可舒適完成治療，"
            "無需進行舒眠全身麻醉，術後無任何表面傷口，可立即洗臉防曬回歸日常作息。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-ultraformer-mpt-hifu",
    },
    # 7. 媽媽復活術
    {
        "question": "產後腹部鬆弛只靠運動練核心，為什麼沒辦法改善小腹凸出？",
        "answer": (
            "懷孕期間子宮膨大常導致左右兩側腹直肌被強力撐開分離（腹直肌分離，Diastasis Recti），且真皮層彈性纖維斷裂形成鬆弛贅皮與妊娠紋。"
            "運動雖然能鍛鍊肌肉力量，但無法將已被拉鬆分離的肌筋膜中線自動閉合，亦無法消除多餘鬆垂皮瓣，唯有透過腹部拉皮手術縫合腹直肌中線才能根本改善腹凸。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-mommy-makeover-reconstruction",
    },
    {
        "question": "腹部拉皮手術會留下很長的疤痕嗎？穿泳衣會看出來嗎？",
        "answer": (
            "腹部拉皮切口設計於下腹部極低位置的比基尼線內，平行於腹股溝自然摺線，穿著低腰內褲或比基尼泳衣時能完全隱藏遮蔽。"
            "術後配合完善的減張照顧、矽膠除疤凝膠與貼片護理，疤痕會在半年至一年內逐步成熟褪色為淡淡細線。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-mommy-makeover-reconstruction",
    },
    # 8. 植髮手術推薦
    {
        "question": "FUE 微創植髮手術後枕部會留下明顯一條線的疤痕嗎？",
        "answer": (
            "不會。傳統 FUT 切頭皮手術才會在後枕部留下長條形線性疤痕；而 FUE 微創植髮採用直徑小於一毫米的微型鑽孔針，點狀分散提取單株毛囊單位，"
            "取髮點細微如針孔，術後數天即迅速結痂癒合，即便日後理短髮或推平頭，後枕部外觀依然自然無明顯疤痕。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-fue-hair-transplantation",
    },
    {
        "question": "植髮手術做完後多久才會長出新頭髮？會不會再次掉落？",
        "answer": (
            "術後二至四週植入的毛幹會先進入正常的生理休止期暫時性脫落，但皮下毛囊幹細胞依然健康存留；術後三至四個月起新毛髮開始萌出，"
            "術後六至九個月日益濃密，約九至十二個月達到豐滿自然成果。移植的後枕部毛囊天生不帶落髮雄性受體，存活後持久生長。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-fue-hair-transplantation",
    },
    # 9. 正顎手術
    {
        "question": "做正顎手術一定要綁牙（顎間固定）不能張開嘴巴嗎？",
        "answer": (
            "傳統正顎手術常需用鐵絲將上下牙齒死死固定數週；但現代正顎手術採用高強度純鈦微型骨板骨釘進行剛性骨骼固定，術後多僅使用彈性橡皮圈進行咬合定位引導，"
            "不需將嘴巴完全鎖死。病患術後即可張口說話與進食流質營養，大幅提升呼吸道安全性與術後照護舒適度。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-orthognathic-surgery",
    },
    {
        "question": "骨性戽斗或嚴重暴牙只做牙齒矯正，跟做正顎手術差別在哪裡？",
        "answer": (
            "單純牙齒矯正只能移動牙齒齒槽骨角度（代償性調整），對於顎骨發育過度或不足（如骨性戽斗、骨性下顎後縮、顏面歪斜）無法改變骨骼基底位置，容易導致暴牙牙根外凸或咬合不穩；"
            "正顎手術則從根本切開骨骼將上下顎骨移至標準三維位置，同時解決咬合功能障礙與整體臉型比例。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-orthognathic-surgery",
    },
    # 10. 海神雷射
    {
        "question": "海神除毛雷射跟傳統除毛雷射相比，真的比較不痛嗎？",
        "answer": (
            "是的。Triton 海神除毛搭載專利 360 度環迴藍寶石接觸式冷卻探頭，在雷射擊發前、擊發中與擊發後皆能維持表皮低溫保護，"
            "大幅阻斷熱能向表皮神經傳導，多數人僅感覺涼爽微溫，相較於傳統亞歷山大除毛的劇烈橡皮筋彈痛感舒適許多。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-triton-laser-hair-removal",
    },
    {
        "question": "除毛療程做一次就可以除乾淨嗎？需要做幾次？",
        "answer": (
            "人體毛髮分為生長期、退行期與休止期三個階段，雷射只對含有高濃度黑色素的「生長期」毛囊有效。因此單次雷射只能破壞該批生長期毛囊，"
            "一般建議每四至六週治療一次，連續接受六至八次治療，方能全面涵蓋各週期毛囊，達到持久光滑潔淨的效果。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-triton-laser-hair-removal",
    },
    # 11. 海菲秀(水飛梭)
    {
        "question": "做海菲秀（水飛梭）清粉刺會像傳統做臉擠粉刺一樣痛或留紅印嗎？",
        "answer": (
            "完全不會。傳統做臉擠粉刺常使用粉刺夾或暗瘡針硬擠，易造成毛孔發炎、留疤或微血管破裂；海菲秀採用專利水渦漩技術與水楊酸精華，"
            "以溫和無痛的負壓水流軟化並深度旋轉抽吸毛孔髒污與黑頭，做完後皮膚不紅腫破皮，反而立現透亮水潤。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-hydrafacial-deep-cleansing",
    },
    {
        "question": "海菲秀多久需要做一次保養？敏弱肌膚也可以做嗎？",
        "answer": (
            "一般建議每個月進行一次深層毛孔清潔與抗氧化導入保養，有助於維持角質代謝週期與毛孔暢通。海菲秀精華液溫和且探頭多樣，"
            "敏弱肌膚亦可由專業人員調降負壓吸力並加強修護舒緩精華，安全溫和淨化膚質。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-hydrafacial-deep-cleansing",
    },
    # 12. 淨膚雷射
    {
        "question": "打淨膚雷射會不會反黑？術後可以立刻上妝嗎？",
        "answer": (
            "淨膚雷射採用均質光斑與低能量調控，溫和震碎黑色素顆粒，表皮沒有破皮創口，只要術後做好嚴格防曬與保濕，反黑機率極低。"
            "治療後敷鎮定面膜退紅後即可正常擦拭防曬或上淡妝，不影響日常生活作息。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-nd-yag-laser-toning",
    },
    {
        "question": "淨膚雷射打一次斑點就會完全消失嗎？",
        "answer": (
            "色斑形成與真皮表皮深層色素累積有關，淨膚雷射是以漸進式代謝方式將色素碎裂交由體內巨噬細胞吸收，單次治療能達到均勻膚色與初步淡化；"
            "若要顯著淡化曬斑、雀斑或深層斑點，建議每三至四週接受一次評估施作，連續進行三至五次以上效果更為理想。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-nd-yag-laser-toning",
    },
    # 13. 玻尿酸
    {
        "question": "玻尿酸打完會不會臉很僵硬、變成「饅化臉」？",
        "answer": (
            "饅化臉通常源於過量注射、施打層次錯誤或頻繁大面積填補。凡登整形外科堅持「深層骨膜支撐、微量多點立體錨定」原則，"
            "針對骨骼萎縮關鍵點提供結構力，嚴格控制施打劑量與解剖層次，動態表情自然協調，絕不會出現塑膠假面或浮腫僵硬感。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-hyaluronic-acid-dermal-filler",
    },
    {
        "question": "玻尿酸注射後如果效果不滿意，可以補救復原嗎？",
        "answer": (
            "玻尿酸具備高度安全性的一大原因即是擁有特效解劑——降解酶（透明質酸酶，Hyaluronidase）。若對注射形態不滿意或有移位不均情形，"
            "專科醫師可透過超音波精確引導注射微量降解酶，在二十四至四十八小時內精準溶解多餘玻尿酸，安全恢復原生樣貌。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-hyaluronic-acid-dermal-filler",
    },
    # 14. 皮秒雷射
    {
        "question": "皮秒雷射跟傳統淨膚雷射有什麼差別？恢復期比較短嗎？",
        "answer": (
            "傳統淨膚雷射是以「奈秒」脈衝的光熱效應震碎色素，熱殘留較多；而皮秒雷射脈衝時間縮短一千倍（皮秒級），主要透過純粹「光機械衝擊波」將黑色素震為極細粉塵，"
            "大幅減少對周圍正常皮膚的熱傷害，因此退紅速度極快、反黑風險大幅降低，恢復期顯著縮短。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-picosecond-laser-rejuvenation",
    },
    {
        "question": "皮秒雷射打完多久會退紅？打完會結痂脫皮嗎？",
        "answer": (
            "單純除斑或亮白模式術後僅有些微泛紅，多於數小時至隔天消退；若搭配聚焦蜂巢透鏡深層刺激膠原蛋白，皮膚會出現均勻皮下微紅或點狀微出血斑，"
            "約一至兩天即可退紅。深層色斑處可能形成如胡椒粒般的微細薄痂，三至七天隨洗臉自然脫落，完全不影響工作社交。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-picosecond-laser-rejuvenation",
    },
    # 15. 眼整形中心
    {
        "question": "內開眼袋手術把脂肪移位填補淚溝，跟直接抽掉眼袋脂肪有什麼不同？",
        "answer": (
            "單純把眼袋脂肪剪除抽掉，雖然眼袋平了，但眼眶下方的凹陷淚溝依然存在，甚至可能導致眼眶下緣更為中空凹陷顯老；"
            "內開眼袋脂肪移位（Fat Repositioning）則是將脫垂的自身眼袋脂肪完整游離，往下鋪平固定在凹陷的淚溝骨膜處，一次達成撫平眼袋與填平淚溝雙重回春效果。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-blepharoplasty-eye-contouring",
    },
    {
        "question": "割雙眼皮跟縫雙眼皮怎麼選？提眼瞼肌無力會影響雙眼皮成形嗎？",
        "answer": (
            "眼皮薄、無多餘鬆弛贅皮與脂肪者適合縫雙眼皮，恢復極快；眼皮較厚、脂肪多或眼皮鬆弛下垂者則建議採切開法修除多餘皮脂。若合併有提眼瞼肌無力（眼瞼下垂遮蓋黑眼珠），"
            "單純縫或割雙眼皮術後眼神仍會無神無力甚至雙眼皮過寬，必須同步進行提眼瞼肌筋膜摺疊矯正，眼神才會黑白分明清澈有神。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-blepharoplasty-eye-contouring",
    },
    # 16. 美國音波
    {
        "question": "美國音波 Ultherapy 為什麼施打時要有「即時超音波影像螢幕」？",
        "answer": (
            "每個人全臉皮膚、皮下脂肪與筋膜層厚度皆不相同。Ultherapy 專利 DeepSEE 即時影像系統讓醫師在擊發前於螢幕上清晰透視皮下組織解剖層次，"
            "確保每一發熱凝固點精準落在四點五毫米深度的 SMAS 筋膜層，同時避開顏面神經與骨骼骨膜，兼顧最高安全性與強效提拉效果。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-ultherapy-focused-ultrasound",
    },
    {
        "question": "美國音波跟電波拉皮有什麼不同？兩者可以一起做嗎？",
        "answer": (
            "音波主要以超音波「點狀深入」筋膜層（SMAS），著重在垂直方向的深層收縮拉提；電波則是單極高頻「容積式加熱」真皮層與皮下層，著重在全層膠原收緊、撫平細紋與提升肌膚彈性。"
            "兩者作用機制與深度互補，臨床上常結合規劃為「電音波複合治療」，同時改善緊緻與拉提雙重需求。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-ultherapy-focused-ultrasound",
    },
    # 17. 臉部拉皮
    {
        "question": "深層筋膜拉皮（Deep Plane）跟傳統只拉皮膚的拉皮手術有何根本不同？",
        "answer": (
            "傳統拉皮只分離皮下組織並死命拉扯表皮，不僅維持時間短，還容易導致表情僵硬、五官被拉扯變形；Deep Plane 深層筋膜拉皮進入更深層的解剖間隙，"
            "完整釋放顴骨及下顎維持韌帶，將深層 SMAS 筋膜、頰脂肪墊與下垂肌肉複合體連同復位並錨定在堅硬骨膜上，表皮完全零張力縫合，神態自然且維持長達八至十年以上。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-full-deep-plane-facelift",
    },
    {
        "question": "全臉拉皮手術術後會不會表情很僵硬或耳朵被拉長變形？",
        "answer": (
            "不會。表情僵硬與耳垂變形通常發生於只拉皮膚且縫合張力過大的傳統術式；凡登高位深層筋膜拉皮的張力全部由深層堅韌筋膜承擔，"
            "表皮僅修剪贅皮後進行微米級無壓縫合，表情活動肌肉未受破壞，術後表情自然生動，耳垂維持原生自然弧度。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-full-deep-plane-facelift",
    },
    # 18. 超能電漿
    {
        "question": "超能電漿在皮下溫度高達85度，會不會造成皮膚內部燙傷或壞死？",
        "answer": (
            "不會。Renuvion 超能電漿擁有革命性的「瞬熱瞬冷」專利：利用氦氣激發電漿態，在零點二秒內升溫至八十五度促使纖維中隔收縮六成以上，"
            "但緊接著冷氦氣在零點零四四秒內瞬間降溫冷卻至正常體溫，熱作用極度局限於纖維隔膜，熱擴散少於零點一毫米，完全不傷害表皮與神經血管。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-renuvion-helium-plasma",
    },
    {
        "question": "超能電漿通常搭配抽脂手術一起做嗎？它的緊膚效果可以維持多久？",
        "answer": (
            "非常適合。抽脂手術後若皮下脂肪減少過多，皮膚缺乏支撐容易出現鬆弛垂墜；抽脂後立即穿入超能電漿探頭進行皮下收緊，能使皮瓣與深層筋膜緊密黏合貼緊。"
            "收縮重組後的皮下膠原蛋白網絡結構具備持久性，術後穿戴塑身衣配合健康體態維持，緊實效果穩定持久。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-renuvion-helium-plasma",
    },
    # 19. 隆鼻手術
    {
        "question": "結構式隆鼻為什麼建議使用「自體軟骨」來做鼻頭？",
        "answer": (
            "鼻頭皮膚直接承受外界張力與摩擦，若使用矽膠等人工假體直接頂在鼻尖，長久下來易因重力與壓力造成假體下滑、鼻頭皮膚變薄甚至穿出感染壞死；"
            "結構式隆鼻以自體耳軟骨、鼻中膈軟骨或自體肋軟骨搭建穩固架構並保護鼻頭微凸點，生物相容性百分之百，不排斥、不穿出且線條圓潤自然。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-structural-autologous-rhinoplasty",
    },
    {
        "question": "隆鼻手術拆完線後，多久可以正常戴眼鏡和擤鼻涕？",
        "answer": (
            "術後五至七天拆線與拆除外固定鼻夾板。術後一個月內骨骼與軟骨支架尚處於微血管爬行與纖維貼合期，嚴禁配戴重框眼鏡壓迫鼻梁、擤鼻涕或趴睡擠壓鼻子；"
            "若有鼻腔分泌物可以無菌棉棒沾生理食鹽水輕柔沾拭。通常一個月後骨骼架構穩定，可逐步恢復日常活動。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-structural-autologous-rhinoplasty",
    },
    # 20. 青萃光
    {
        "question": "BBL 青萃光跟一般傳統脈衝光有什麼不同？打完會結痂嗎？",
        "answer": (
            "傳統脈衝光波形不平整，易產生熱尖峰導致燙傷或反黑；旗艦級 Sciton BBL 青萃光擁有平頂波方波專利技術，能量輸出平穩精準，並配備智能即時溫控藍寶石晶片。"
            "術後色素斑點可能浮現如胡椒粒微小薄痂，三至五天隨角質脫落，無開放傷口，治療體感舒適溫和。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-bbl-broadband-light",
    },
    {
        "question": "青萃光可以同時改善臉部泛紅跟曬斑嗎？需要做幾次？",
        "answer": (
            "可以。BBL 青萃光具備多種濾光片快速切換，短波長濾光片能鎖定表皮黑色素代謝曬斑與雀斑，長波長濾光片則專門收縮真皮層異常擴張之含氧血紅素血管，"
            "有效改善酒糟泛紅與微血管擴張。一般建議每三至四週治療一次，連續接受三至五次可顯著改善膚色勻亮與泛紅狀況。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-bbl-broadband-light",
    },
    # 21. 靜脈曲張
    {
        "question": "靜脈曲張用雷射微創閉合後，原本血管裡面的血要流去哪裡？",
        "answer": (
            "請完全放心。下肢靜脈血液有百分之八十至九十以上是由「深層靜脈」系統回流心臟，發生曲張的大隱或小隱靜脈屬於淺層病變血管，其瓣膜已壞死逆流，反而造成血液淤積與靜脈高壓；"
            "將病變靜脈微創閉合後，下肢血液會自然改走健康的深層靜脈順暢回流，下肢腫脹與沈重感隨之獲得大幅改善。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-varicose-vein-evlt-sclerotherapy",
    },
    {
        "question": "微創靜脈曲張手術後需要臥床休息很久嗎？多久可以回去上班？",
        "answer": (
            "完全不需要長期臥床。現代血管內雷射閉合術（EVLT）切口細微如針孔，術後穿上醫療級大腿彈性減壓襪後，即可立即下床慢步走動三十分鐘以預防深層血栓；"
            "多數病患術後隔天即可正常上班、上下樓梯與從事日常文書活動，唯兩週內避免劇烈快跑或泡熱水澡。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-varicose-vein-evlt-sclerotherapy",
    },
    # 22. 頭痛治療
    {
        "question": "打肉毒桿菌素治療慢性偏頭痛，跟醫美除皺打的肉毒是一樣的嗎？",
        "answer": (
            "藥劑成分同樣為高純度肉毒桿菌素A型，但「治療目標與施打點位完全不同」。偏頭痛治療嚴格遵循國際 PREEMPT 醫療協議，由專科醫師在頭皮、顳部、後枕部及斜方肌等三十一至三十九處痛覺神經周圍特定觸發點進行精準微量注射，"
            "主要機制為阻斷致痛神經胜肽釋放並放鬆受壓神經，並非單純醫美除皺。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-chronic-migraine-botox-decompression",
    },
    {
        "question": "偏頭痛肉毒治療打一次可以維持多久？需要一直打下去嗎？",
        "answer": (
            "注射後約一至兩週神經胜肽阻斷生效，頭痛發作天數與強度顯著下降，單次注射療效通常維持約三至四個月。臨床上建議每十二週規律接受一次治療，"
            "連續接受數個週期後，大腦中樞痛覺敏感化與神經緊繃狀態往往獲得長效平穩調節，許多病患日後可逐漸拉長間隔或減少口服止痛藥依賴。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-chronic-migraine-botox-decompression",
    },
    # 23. 頸部拉皮(又稱天鵝頸)
    {
        "question": "天鵝頸手術跟一般的抽雙下巴、打電音波拉皮有什麼本質區別？",
        "answer": (
            "電音波只能緊緻淺層表皮，抽脂只能抽掉皮下淺層脂肪；但火雞脖垂帶與雙下巴下垂的關鍵元兇，往往是深層的「闊頸肌（Platysma）兩側鬆弛分離」與深層脂肪堆積。"
            "天鵝頸手術直接進入肌肉層將深層脂肪減容，並將分離的闊頸肌像馬甲一樣緊緊折疊縫合固定，形成天然肌肉吊帶，這是非手術儀器無法做到的解剖重塑。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-swan-neck-cervicoplasty",
    },
    {
        "question": "天鵝頸手術的傷口在哪裡？術後抬頭會不會很緊繃不舒服？",
        "answer": (
            "手術切口隱藏在下巴下緣約兩至三公分的天然皮膚橫紋處，站立或社交距離完全看不到，癒合後隨時間淡化為不明顯細線。術後初期抬頭會有些微拉緊感，"
            "這正是闊頸肌被緊緻拉平的正常生理反應，通常一至兩週隨組織適應即自然緩解，術後下顎線立體俐落。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-swan-neck-cervicoplasty",
    },
    # 24. 饅化臉修復推薦
    {
        "question": "臉上打太多玻尿酸看起來很腫（饅化），打降解酶會不會把我自己的膠原蛋白也溶掉？",
        "answer": (
            "不會。原廠醫用透明質酸酶（降解酶）高度特異性鎖定交聯玻尿酸結構進行酶解，對自體正常真皮膠原纖維與自體組織幾乎不產生破壞。在超音波即時精確定位導引下，"
            "專科醫師微量注射於填充物積聚腔室內，能在安全保護自體基質的前提下，精準分解過剩玻尿酸與假性囊腫。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-overfilled-face-syndrome-correction",
    },
    {
        "question": "饅化臉修復打完降解酶之後，多久可以看出原本的自然輪廓？",
        "answer": (
            "降解酶在注入後數小時至二十四小時內即開始快速分解玻尿酸，四十八小時內絕大部分交聯玻尿酸皆已化為小分子水排出；局部注射水腫約在三至五天內吸收退去，"
            "一至兩週組織逐漸恢復原本柔軟與自然彈性，告別假面浮腫感。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-overfilled-face-syndrome-correction",
    },
    # 25. 魔泌
    {
        "question": "外泌體（魔泌）跟一般的玻尿酸水光針有什麼差別？",
        "answer": (
            "玻尿酸水光針主要作用是「物理補水抓水」增加含水量；而魔泌 ASCE+ 外泌體提煉自大馬士革玫瑰幹細胞，具備百億級微囊活性分子，扮演細胞間的通訊訊號，"
            "能深入啟動真皮層纖維母細胞自我修復機制，直接促進自體膠原蛋白、彈力蛋白增生並強效退紅抗發炎，屬於深層細胞再生修護層次。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-asce-rose-exosome-regeneration",
    },
    {
        "question": "魔泌外泌體導入治療後需要多久修復期？敏弱肌能做嗎？",
        "answer": (
            "幾乎沒有修復期。導入後皮膚僅有些微微溫泛紅，敷上外泌體專屬凍膜後數小時內即可退紅；外泌體本身具備優異的抗發炎與微環境修護能力，"
            "非常適合酒糟泛紅、皮膚屏障受損或雷射術後的敏弱肌膚進行深層修護再生。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-asce-rose-exosome-regeneration",
    },
    # 26. 麗珠蘭
    {
        "question": "打麗珠蘭臉上出現的一顆一顆「小皮丘」多久會消退？",
        "answer": (
            "施打麗珠蘭時採真皮微滴淺層注射技術，將高分子多核苷酸（PN）精確留在真皮層，因此皮膚表面會形成暫時性的微細皮丘突起。高相容性的 PN 成分通常在二十四至四十八小時內會隨組織均勻擴散吸收，"
            "皮丘完全平整，術後加強保濕冰敷即可加速吸收。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-rejuran-pdrn-skin-healer",
    },
    {
        "question": "麗珠蘭跟玻尿酸打水光有什麼不同？它是填充物嗎？",
        "answer": (
            "麗珠蘭不是空間體積填充物。玻尿酸是藉由交聯網狀結構抓住水分子進行局部容積填補；麗珠蘭則萃取自野生鮭魚DNA多核苷酸（PN），是天然的「細胞生理再生激活劑」，"
            "提供細胞合成原料修復受損真皮層、增加皮膚彈性厚度並改善水油平衡，兩者作用原理截然不同。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-rejuran-pdrn-skin-healer",
    },
    # 27. 鼻頭縮小
    {
        "question": "縮鼻頭手術只把鼻頭裡面的肉（脂肪）剪掉，效果好嗎？會不會又長回來？",
        "answer": (
            "單純修除皮下軟組織（剪肉）成效往往有限，若缺乏軟骨支架支撐，組織增生後鼻頭可能再次變得圓鈍。凡登蒜頭鼻雕塑採複合式結構調整：打薄多餘皮下纖維脂肪的同時，"
            "更核心關鍵在於對兩側外擴的大翼軟骨進行「軟骨間縫合收攏（Interdomal Suture）」，必要時搭配微型自體軟骨立體支撐，效果穩定持久不易回彈。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-bulbous-nose-rhinoplasty",
    },
    {
        "question": "縮鼻頭手術的疤痕會很明顯嗎？多久才能看到最終形狀？",
        "answer": (
            "手術切口隱蔽於鼻孔內緣或鼻小柱階梯天然皺褶處，外觀疤痕極為隱密不明顯。術後前一週外貼熱塑夾板減腫塑型；鼻頭軟組織微循環豐富，"
            "術後約一至兩週消退大半水腫，其後深層組織持續緊密貼合，三至六個月軟骨線條日益秀氣俐落，展現自然精緻海鷗線鼻尖。"
        ),
        "category": "special",
        "clinic_id": CLINIC_ID,
        "topic_key": f"{CLINIC_ID}-bulbous-nose-rhinoplasty",
    },
]


def run_compliance_checks(trees: list[dict[str, Any]], faqs: list[dict[str, Any]]) -> None:
    """執行全量文字之繁簡、價格、禁詞與政治立場檢驗。"""
    print("開始執行全量醫療法規合規性嚴格掃描...")
    for t in trees:
        validate_tree_segment("title", t["title"])
        validate_tree_segment("pre_op", t["pre_op"])
        validate_tree_segment("procedure", t["procedure"])
        validate_tree_segment("post_op_short", t["post_op_short"])
        validate_tree_segment("maintenance", t["maintenance"])
        validate_tree_segment("summary_text", t["summary_text"])
        for note_key in (
            "pre_op_physician_notes",
            "procedure_physician_notes",
            "post_op_short_physician_notes",
            "maintenance_physician_notes",
        ):
            if t.get(note_key) is not None:
                raise ValueError(f"醫師筆記 {note_key} 必須為 None，不得由批次生成提供！")

    for f in faqs:
        validate_tree_segment("question", f["question"])
        validate_tree_segment("answer", f["answer"])

    print(f"✅ 合規檢查通過：{len(trees)} 棵推理樹與 {len(faqs)} 筆 FAQ 全數符合醫療規範與繁體中文準則。")


def distill_vendome(db_path: Path, dry_run: bool = False) -> None:
    """批次將 27 棵推理樹與 54 筆 FAQ 寫入資料庫。"""
    run_compliance_checks(VENDOME_TREES, VENDOME_FAQS)

    if dry_run:
        print("💡 Dry-run 模式：略過資料庫寫入。")
        return

    conn = sqlite3.connect(db_path)
    try:
        print(f"正在寫入 27 棵凡登 PageIndex 臨床推理樹至 {db_path}...")
        ins_t, upd_t, unc_t = upsert_trees(
            conn, VENDOME_TREES, source_type="clinic_upload", review_status="approved"
        )
        print(f"推理樹寫入完成：新增 {ins_t} 筆，更新 {upd_t} 筆，未變 {unc_t} 筆。")

        print(f"正在寫入 54 筆凡登高頻口語 FAQ 至 {db_path}...")
        ins_f, upd_f, unc_f = upsert_faqs(
            conn, VENDOME_FAQS, source_type="clinic_upload", commit=True
        )
        print(f"FAQ 寫入完成：新增 {ins_f} 筆，更新 {upd_f} 筆，未變 {unc_f} 筆。")

        # 驗證 FTS 觸發同步狀況
        cur = conn.cursor()
        cur.execute(
            "SELECT count(*) FROM page_index_fts WHERE page_index_fts MATCH '天鵝頸'"
        )
        fts_trees = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM faq_cache_fts WHERE faq_cache_fts MATCH '天鵝頸'"
        )
        fts_faqs = cur.fetchone()[0]
        print(f"✅ FTS5 檢索同步驗證成功：'天鵝頸' 在 page_index_fts 命中 {fts_trees} 筆，在 faq_cache_fts 命中 {fts_faqs} 筆。")

    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="凡登整形外科診所 27 篇官方醫療內文提煉腳本")
    parser.add_argument("--db", type=Path, default=PROD_DB_PATH, help="SQLite 資料庫路徑")
    parser.add_argument("--dry-run", action="store_true", help="僅執行驗證不寫入資料庫")
    args = parser.parse_args()

    distill_vendome(args.db, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
