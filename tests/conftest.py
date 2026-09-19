"""Pytest collection policy for SKYTICAL's mixed test suite.

Several older regression modules are executable script checks: they set a
process-global AVWIRE_DATA_DIR and import pipeline modules whose path constants
are resolved at import time. Importing more than one of those scripts in the
same pytest process causes false cross-test contamination.

CI executes every legacy script in its own Python process, then pytest collects
all native pytest-compatible modules. This keeps the complete regression suite
while preserving the isolation those legacy checks were written to require.
"""

collect_ignore = [
    "test_pla.py",
    "test_usage.py",
    "test_grounded.py",
    "test_fulltext.py",
    "test_glossary.py",
    "test_companion.py",
    "test_briefing.py",
    "test_images.py",
]
