"""No-network guards for shared budget persistence and CI placement."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_all_production_openai_jobs_share_lock_and_always_persist():
    for name in ("hourly.yml", "briefing.yml", "manual-draft.yml", "copilot.yml", "iata-audit.yml"):
        text = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
        assert "group: skytical-paid-api-${{ github.ref }}" in text
        assert "cancel-in-progress: false" in text
        assert "queue: max" in text
        assert 'AVWIRE_PAID_BUDGET_ENABLED: "true"' in text
        assert text.count("run: python pipeline/paid_budget_sync.py refresh") == 1
        assert text.count("run: python pipeline/paid_budget_sync.py persist") == 1
        step = text.split("- name: Persist paid API budget even after failure", 1)[1].split("- name:", 1)[0]
        assert "if: always()" in step
        assert text.index("paid_budget_sync.py refresh") < text.index('AVWIRE_PAID_BUDGET_ENABLED: "true"')
        assert text.index('AVWIRE_PAID_BUDGET_ENABLED: "true"') < text.index("paid_budget_sync.py persist")


def test_pr_regression_never_fetches_or_spends_paid_budget():
    text = (ROOT / ".github/workflows/hourly.yml").read_text(encoding="utf-8")
    regression = text.split("  regression:", 1)[1].split("  update:", 1)[0]
    assert "paid_budget_sync.py" not in regression
    assert "AVWIRE_PAID_BUDGET_ENABLED:" not in regression
    assert "test_paid_budget.py" in regression


def test_existing_daily_briefings_use_summary_budget_without_a_second_writer():
    text = (ROOT / "pipeline/briefing_writer.py").read_text(encoding="utf-8")
    assert 'budget_purpose = "summary"' in text
    assert 'BRIEFING_WRITER_CALLS_MAX' in text
