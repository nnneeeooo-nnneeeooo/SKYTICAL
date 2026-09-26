"""Offline regression tests for deterministic evidence binding v2.

Run from repository root:
    python tests/test_evidence_binding.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.environ["AVWIRE_DATA_DIR"] = tempfile.mkdtemp(prefix="skytical-evidence-")
sys.path.insert(0, str(REPO / "pipeline"))

import write  # noqa: E402

CHECKS = 0
FAILED = 0


def check(name, condition):
    global CHECKS, FAILED
    CHECKS += 1
    print(("PASS " if condition else "FAIL ") + name)
    if not condition:
        FAILED += 1


GROUP = {
    "id": "g-evidence-v2",
    "primarySource": "Fixture",
    "items": [{
        "source": "Fixture",
        "url": "https://example.test/story",
        "title": "KLM plans A321XLR service update",
        "summary": (
            "On September 23, 2026, KLM said it plans A321XLR service. "
            "The FAA identified the aircraft as a Eurocopter AS332 Super Puma. "
            "Two crew members were on board and the event occurred at 14:55."
        ),
        "fulltext": "",
    }],
}

good_facts = [{
    "factId": "F1",
    "claim": "On September 23, 2026, KLM said it plans A321XLR service.",
    "sourceQuote": "On September 23, 2026, KLM said it plans A321XLR service.",
}]
check(
    "claim atoms supported by the same quote pass",
    write.claim_evidence_problem(good_facts) is None,
)

bad_date = [{
    "factId": "F1",
    "claim": "The agreement was signed in New York on 23 September 2026.",
    "sourceQuote": "The deal was finalized in New York during the UN General Assembly this week.",
}]
check(
    "date borrowed from outside a fact quote is rejected",
    write.claim_evidence_problem(bad_date) is not None,
)

bad_model = [{
    "factId": "F1",
    "claim": "The aircraft was a Eurocopter AS332 Super Puma.",
    "sourceQuote": "The helicopter was conducting water drops near Ostrander Lake.",
}]
check(
    "aircraft model borrowed from another fact is rejected",
    write.claim_evidence_problem(bad_model) is not None,
)

good_entities = {
    "entities": {
        **{key: [] for key in write.ENTITY_KEYS},
        "organizations": ["KLM"],
        "aircraft_models": ["A321XLR"],
        "event_dates": ["September 23, 2026"],
    },
    "entityEvidence": [
        {
            "entityType": "organizations",
            "value": "KLM",
            "sourceQuote": "On September 23, 2026, KLM said it plans A321XLR service.",
            "sourceUrl": "https://example.test/story",
        },
        {
            "entityType": "aircraft_models",
            "value": "A321XLR",
            "sourceQuote": "On September 23, 2026, KLM said it plans A321XLR service.",
            "sourceUrl": "https://example.test/story",
        },
        {
            "entityType": "event_dates",
            "value": "September 23, 2026",
            "sourceQuote": "On September 23, 2026, KLM said it plans A321XLR service.",
            "sourceUrl": "https://example.test/story",
        },
    ],
}
clean, evidence, problem = write.verify_entity_evidence(
    good_entities, GROUP, "fixture")
check("source-bound entities verify", problem is None)
check("verified entities are retained", clean.get("organizations") == ["KLM"])
check("evidence rows are persisted-ready", len(evidence) == 3)

missing = {
    "entities": {**{key: [] for key in write.ENTITY_KEYS},
                 "organizations": ["KLM"]},
    "entityEvidence": [],
}
check(
    "entity without evidence is rejected",
    write.verify_entity_evidence(missing, GROUP, "fixture")[2] is not None,
)

invented_alias = {
    "entities": {**{key: [] for key in write.ENTITY_KEYS},
                 "organizations": ["KLM Royal Dutch Airlines"]},
    "entityEvidence": [{
        "entityType": "organizations",
        "value": "KLM Royal Dutch Airlines",
        "sourceQuote": "On September 23, 2026, KLM said it plans A321XLR service.",
        "sourceUrl": "https://example.test/story",
    }],
}
check(
    "unquoted canonicalized entity alias is rejected",
    write.verify_entity_evidence(
        invented_alias, GROUP, "fixture")[2] is not None,
)

wrong_quote = {
    "entities": {**{key: [] for key in write.ENTITY_KEYS},
                 "organizations": ["KLM"]},
    "entityEvidence": [{
        "entityType": "organizations",
        "value": "KLM",
        "sourceQuote": "KLM invented quote that is not in the source.",
        "sourceUrl": "https://example.test/story",
    }],
}
check(
    "fabricated entity quote is rejected",
    write.verify_entity_evidence(wrong_quote, GROUP, "fixture")[2] is not None,
)

if FAILED:
    print(f"{FAILED}/{CHECKS} evidence-binding checks failed")
    raise SystemExit(1)
print(f"PASS: {CHECKS} evidence-binding checks")
