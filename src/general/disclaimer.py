"""一般醫療諮詢之免責聲明與就醫提示固定文字。

本模組為所有一般諮詢固定文字的唯一權威來源。
全部輸出文字皆為繁體中文、無價格數字、無保證療效用語。
本模組為純函式與字串常數集合，不引入 logging，無副作用。
"""

DISCLAIMER_TEXT = (
    "【免責宣告】本系統所提供之內容僅為一般衛教與健康資訊參考，非醫療指示與處方，"
    "亦不構成任何醫療診斷或醫囑。相關資訊無法取代專業醫師之面對面親自診察與評估。"
    "若您有任何身體不適或健康疑慮，建議儘速就醫，尋求合格專業醫師之診斷與協助。"
)

RED_FLAG_DISCLAIMER_TEXT = (
    "【就醫提醒】本系統僅提供一般衛教諮詢，不構成任何醫療診斷或醫囑，"
    "亦無法取代急症處置。請務必以現場醫療專業人員之評估與指示為準。"
)

EMERGENCY_MESSAGE = (
    "【緊急就醫警示】偵測到可能危及生命之緊急醫療徵候。請立即撥打 119，"
    "或請他人協助儘速前往最近醫院急診就醫評估！請勿等待線上回覆或耽擱就醫時間。"
)

URGENT_MESSAGE = (
    "【儘速就醫建議】您所描述的症狀需要由醫師進行專業評估，建議於當日內前往就近醫療院所就診。"
    "若症狀持續加劇，或出現呼吸困難、意識改變、大量出血等緊急狀況，請立即撥打 119 或前往最近醫院急診。"
)

FILLER_OCCLUSION_ADDENDUM = (
    "【重要補充】若此情形發生在注射填充劑（如玻尿酸、水光針等微整療程）之後，"
    "請同時儘速聯絡當初施作的診所或醫師，並明確告知注射時間與部位，以利及時評估處置。"
)

ANSWERED_MESSAGE = "以下為資料庫中與您問題相關的一般衛教資訊："

NO_MATCH_MESSAGE = (
    "目前資料庫沒有與您問題直接相關的一般衛教資料。"
    "建議您諮詢專業醫師或藥師，若有身體不適請儘速就醫，由合格醫療人員為您評估。"
)


def message_for_red_flag(level: str, rule_id: str) -> str:
    """依據紅旗等級與規則識別碼產生對應的就醫提示訊息。

    Args:
        level: 紅旗等級，必須為 "emergency" 或 "urgent"。
        rule_id: 規則編號，例如 "E01"、"E08"、"U02"。

    Returns:
        對應之繁體中文就醫指引字串。若為 E08 則會額外附加填充劑血管阻塞補充提示。

    Raises:
        ValueError: 若傳入不支援的 level。
    """
    if level == "emergency":
        if rule_id == "E08":
            return EMERGENCY_MESSAGE + "\n" + FILLER_OCCLUSION_ADDENDUM
        return EMERGENCY_MESSAGE
    if level == "urgent":
        return URGENT_MESSAGE
    raise ValueError(f"不支援的紅旗等級: {level}")
