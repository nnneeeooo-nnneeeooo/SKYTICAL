"""Offline policy, cost isolation and fair-queue regression checks."""
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
from editorial_policy import news_policy, eligible_providers
import news_retry


def story(title, summary="", n=0):
    return {"id": str(n), "items": [{"title": title, "summary": summary,
            "url": f"https://example.com/{n}", "publishedUtc": f"2026-10-{10+n:02}T00:00Z"}]}


def main():
    examples = [
        ("Airbus Helicopters completes H140 hot-and-high tests in the US", ""),
        ("Southwest's second-seat refund depends on flight occupancy", ""),
        ("BETA Technologies receives FAA certification to fly customers", "Special Airworthiness Certificate for market surveys"),
        ("Civil Air Patrol orders 21 Cessna aircraft", ""),
        ("WCC Aviation Holdings agrees to acquire 30% of PhilJets", "Business aviation and helicopter services"),
        ("WestJet sold 27 Boeing 737-700s but will keep flying 17", ""),
        ("US Navy remotely controls MQ-25A Stingray", ""),
        ("SyberJet unveils SJ36 mockup and single-pilot avionics", ""),
        ("Saudia and Riyadh Air route Riyadh passengers through Al Qassim Airport",
         "Onward bus transfers after King Khalid International Airport reopened with restrictions."),
        ("European governments weigh expanded drone powers for infrastructure operators", ""),
        ("Emirates cancels three nonstop A380 routes this winter", ""),
    ]
    free = SimpleNamespace(name="gemini", model="gemini-3.6-flash")
    nim = SimpleNamespace(name="nvidia", model="nvidia/nemotron-3-super-120b-a12b")
    router = SimpleNamespace(name="openrouter", model="test:free")
    paid = [SimpleNamespace(name=n, model=m) for n, m in (
        ("openai", "gpt-6"), ("wechat", "Deepseek-v4-flash"),
        ("openrouter", "paid/model"), ("anthropic", "claude"),
        ("gemini", "gemini-pro-paid"))]
    for title, summary in examples:
        group = story(title, summary)
        assert news_policy(group).priority == "niche", (title, news_policy(group))
        assert eligible_providers(group, paid + [free, nim, router]) == [free, nim, router]
        if "BETA" in title:
            assert news_policy(story("BETA receives FAA certificate to fly customers on ALIA eVTOL")).priority == "niche"
        # Neither stale flags nor historical accident context can buy a call.
        group.update(editorialPriority="major", mustReport=True,
                     archiveContext={"title": "Fatal aircraft crash"})
        assert not news_policy(group).paid_allowed
        assert not eligible_providers(group, paid)

    for title in ("Airliner crash at airport", "FAA grounds all Boeing 737 aircraft",
                  "Airport closed after power failure", "Nationwide strike causes mass cancellations",
                  "Airport closed after drone incursions",
                  "Airline suspends routes after airspace closure",
                  "Emirates cancels hundreds of flights after airport closure",
                  "BETA receives type certificate", "BETA begins commercial passenger service"):
        group = story(title)
        assert news_policy(group).paid_allowed, title
        assert eligible_providers(group, paid) == paid
    for title in ("Airbus aims for type certification in 2028",
                  "BETA plans to obtain a type certificate",
                  "Why aircraft crash during testing",
                  "Airbus completes aircraft crash tests"):
        assert not news_policy(story(title)).paid_allowed, title
    current = story("Airbus completes H140 flight tests")
    current["items"].append({"title": "Fatal aircraft crash", "backgroundCompanion": True})
    assert not news_policy(current).paid_allowed

    for title, reason in (
            ("Airlines fly Riyadh passengers to an airport four hours away", "local_passenger_rerouting"),
            ("Europe considers giving private companies powers to shoot down drones", "regional_counter_drone_policy"),
            ("Emirates switches its London route from A380 to Boeing 777 this winter", "routine_route_schedule"),
            ("阿聯酋航空本冬季取消三條不停站A380航線", "routine_route_schedule"),
            ("歐洲研議擴大關鍵基礎設施業者反制無人機權限", "regional_counter_drone_policy"),
            ("Saudia與Riyadh Air改道經Al Qassim Airport接送利雅德旅客", "local_passenger_rerouting")):
        policy = news_policy(story(title))
        assert (policy.priority, policy.paid_allowed, policy.reason) == ("niche", False, reason), title
    taiwan = news_policy(story("EVA Air adjusts winter routes from Taipei"))
    assert taiwan.priority == "standard" and taiwan.paid_allowed

    for title, summary in (
            ("Taiwan airline signs small cooperation agreement", ""),
            ("EVA Air unveils aircraft mockup", ""),
            ("華航出售飛機並安排售後租回", ""),
            ("星宇調整冬季航線", ""),
            ("外籍航空因颱風取消桃園往返航班", ""),
            ("松山機場國內線明日停飛", ""),
            ("澎湖、金門航班受颱風影響延誤", ""),
            ("颱風影響航班", "花蓮與臺東機場公布異動資訊"),
            ("Airline adjusts flight schedule", "Flights to Taiwan are affected by a typhoon."),
            ("Foreign airline suspends TPE flights due to typhoon", ""),
            ("Flights at Songshan (TSA) delayed by typhoon", ""),
            ("如何查詢颱風期間臺灣航班異動？", ""),
            ("漢翔公布航空研發測試進度", "")):
        group = story(title, summary)
        policy = news_policy(group)
        assert (policy.priority, policy.paid_allowed, policy.reason) == (
            "standard", True, "taiwan_relevance"), (title, policy)
        assert eligible_providers(group, paid + [free]) == paid + [free]
    caa = story("民航局公布颱風期間國內線取消資訊")
    caa["items"][0]["source"] = "CAA Taiwan"
    assert eligible_providers(caa, paid) == paid
    # Background, stale metadata and an unrelated overseas typhoon cannot
    # grant Taiwan spending eligibility or invent cancelled flights.
    foreign = story("Airline cancels Okinawa flights due to typhoon")
    foreign["items"].append({"title": "Taiwan flights cancelled",
                              "source": "CAA Taiwan", "backgroundCompanion": True})
    foreign.update(taiwanRelevance=True, archiveContext={"title": "Taipei flights"})
    assert not news_policy(foreign).paid_allowed
    assert not eligible_providers(foreign, paid)
    assert not news_policy(story("TSA introduces new US airport screening procedures")).paid_allowed
    assert news_policy(story("颱風將接近臺灣", "尚未宣布航班取消")).priority == "standard"

    # Do not classify actual drone incidents or ordinary new routes as one of
    # these low-priority follow-up categories merely because of a shared word.
    assert news_policy(story("Airport detects drone near runway")).priority == "standard"
    assert news_policy(story("Airline announces new route to Paris")).priority == "standard"

    now = datetime(2026, 10, 22, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as tmp, patch.object(news_retry, "DATA_DIR", Path(tmp)):
        ledger = news_retry.RetryLedger(now)
        regular = [story(f"Airline announces new route {i}", n=i) for i in range(10)]
        niche = [story("SyberJet unveils aircraft mockup", n=i) for i in range(10, 15)]
        chosen, deferred = ledger.plan(regular + list(reversed(niche)), 10)
        assert len(chosen) == 10 and sum(news_policy(g).priority == "niche" for g in chosen) == 1
        assert chosen[2] is niche[0], "oldest niche gets an early reserved slot"
        ledger.failure(niche[0], content=False)
        assert niche[0] in ledger.plan(niche, 10)[1]
        ledger.now += timedelta(hours=2)
        chosen, _ = ledger.plan(regular + niche, 10)
        assert niche[0] in chosen, "due free-only retry survives fresh discovery"
        assert len(ledger.plan(niche, 10)[0]) == 2
        # Only a critical current event can upgrade a queued niche story.
        niche[0]["items"][0]["title"] = "SyberJet aircraft crash"
        assert news_policy(niche[0]).paid_allowed
    print("PASS eleven owner examples, paid isolation, urgent exceptions and fair queue")


if __name__ == "__main__":
    main()
