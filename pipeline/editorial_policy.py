"""Deterministic news priority and per-story spending gates.

Only current source headlines/excerpts participate; archive context, model
output and persisted priority flags cannot grant paid fallback permission.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from common import is_taiwan_airline_story


def matches(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.I) is not None


@dataclass(frozen=True)
class NewsPolicy:
    priority: str
    paid_allowed: bool
    reason: str


def news_policy(group: dict) -> NewsPolicy:
    items = [item for item in group.get("items", [])
             if isinstance(item, dict) and not item.get("backgroundCompanion")]
    # Headline-led signals prevent a routine story's historical background
    # (including accidents or future certification goals) buying a paid call.
    title = " ".join(str(item.get("title") or "") for item in items)
    excerpt = " ".join(str(item.get("summary") or "") for item in items)
    text = title + " " + excerpt
    safety = matches(
        r"\b(?:crash(?:es|ed)?|fatal(?:ities)?|deadly|midair collision|"
        r"runway (?:collision|excursion|incursion)|emergency landing|"
        r"uncontained engine failure)\b|墜機|空難|跑道碰撞|衝出跑道|迫降", title)
    disruption = matches(
        r"\b(?:fleet[- ]wide grounding|grounds? (?:all|entire)|"
        r"airport (?:closed|closure)|airspace (?:closed|closure)|"
        r"mass cancellations?|nationwide (?:strike|outage)|bankruptcy|ceases all operations|"
        r"hundreds of (?:flights|cancellations)|thousands of (?:flights|passengers))\b"
        r"|全面停飛|機場關閉|空域關閉|大規模取消|全國罷工|聲請破產|全面停航", title)
    # Specific limited authorizations are not full type/commercial approvals.
    limited = matches(r"special airworthiness|market surveys?|特別適航|市場調查", text)
    major_approval = not limited and matches(
        r"\b(?:type certification|type certificate|commercial passenger (?:service|operations))\b"
        r"|型別認證|型別合格證|正式商業載客", title) and matches(
        r"\b(?:receives?|grants?|awarded|approved|obtains?|begins?|launches?)\b"
        r"|取得|獲得|核發|核准|開始|啟動", title)
    explainer = matches(
        r"^(?:why|how|what|when|could|can|will|does|do|is|are|should)\b"
        r"|[?？]|為何|如何|是否", title)
    if matches(r"\bcrash[- ]tests?\b|crashworthiness|碰撞測試|墜落測試", title):
        safety = False
    if matches(r"\b(?:aims?|plans?|targets?|expects?|seeks?|could|may|will)\b"
               r"|目標|計畫|預計|力拚", title):
        major_approval = False
    if not explainer and (safety or disruption or major_approval):
        return NewsPolicy("urgent", True, "safety_or_major_operational_event")

    development_test = (
        matches(r"\b(?:test(?:s|ing)?|tested|trial|demonstrat\w*)\b|測試|試驗|展示", title)
        and matches(r"\b(?:aircraft|airplane|helicopters?|prototype|H140|eVTOL|"
                    r"drone|flight|navy|air force)\b|飛機|直升機|無人機|飛行|海軍|空軍", text))
    military_test = (
        matches(r"\b(?:military|navy|air force|MQ-25)\b|軍用|海軍|空軍", title)
        and (matches(r"\b(?:test|trial|demonstrat\w*)\b|測試|試驗", excerpt)
             or matches(r"remotely controls?|remote control|control link|遠端控制", title)))
    niche = None
    if limited or (
            matches(r"\beVTOL\b|advanced air mobility|electric aircraft|電動飛機", text)
            and matches(r"certificat\w*|authori[sz]\w*|allows?|approval|認證|授權|允許", title)):
        niche = "limited_certification"
    elif matches(r"second[- ]seat|customer of size|第二.{0,2}座位|大體型旅客", text):
        niche = "local_passenger_policy"
    elif matches(r"mock[- ]?up|concept (?:aircraft|jet)|全尺寸模型|概念機", title):
        niche = "concept_display"
    elif development_test or military_test:
        niche = "routine_development_or_military_test"
    elif (matches(r"\b(?:civil air patrol|cessna|piston aircraft|general aviation)\b"
                  r"|通用航空|活塞飛機|塞斯納", text)
          and matches(r"\b(?:orders?|purchas\w*|buys?)\b|訂購|採購", title)):
        niche = "general_aviation_procurement"
    elif (matches(r"\b(?:acquir\w*|acquisition|stake|merger)\b|收購|股權|併購", title)
          and matches(r"\b(?:business aviation|business jets?|charter|"
                      r"helicopter services?|philjets)\b"
                      r"|商務航空|商務噴射機|包機|直升機服務", text)):
        niche = "small_aviation_services_transaction"
    elif matches(r"\b(?:sold|sells?|sale[- ]and[- ]leaseback|retires?|"
                 r"retirement|fleet renewal)\b|出售|售出|售後租回|汰換|退役", title):
        niche = "routine_fleet_assets"
    taiwan = (
        is_taiwan_airline_story({"items": [{"title": title, "summary": excerpt}]})
        or matches(r"\b(?:taiwan|taipei|taoyuan|kaohsiung)\b"
                   r"|臺灣|台灣|桃園|高雄|臺北|台北", title))
    if niche:
        return NewsPolicy("standard" if taiwan else "niche", False, niche)
    return NewsPolicy("standard", False, "taiwan_relevance" if taiwan else "ordinary_news")


def is_free_provider(provider):
    """Existing free-quota routes; subscription/pay-per-call routes fail closed.

    Gemini/NVIDIA use the project's existing free-quota credentials. OpenRouter
    must explicitly select :free, regardless of AVWIRE_PROVIDER_ORDER overrides.
    """
    name = getattr(provider, "name", "")
    if name == "nvidia":
        return True
    if name == "gemini":
        return getattr(provider, "model", "") in {"gemini-3.6-flash", "gemini-3.5-flash"}
    return name == "openrouter" and str(getattr(provider, "model", "")).endswith(":free")


def eligible_providers(group, providers):
    if news_policy(group).paid_allowed:
        return list(providers)
    return [provider for provider in providers if is_free_provider(provider)]
