import json
from pathlib import Path


GLOSSARY_PATH = Path(__file__).resolve().parents[1] / "config" / "zh_glossary.json"


def test_heathrow_uses_taiwan_rendering():
    glossary = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))

    assert glossary["translate"]["Heathrow Airport"] == "希斯洛機場"
    assert "希思羅" in glossary["forbidden_zh"]["Heathrow Airport"]
    assert "希思羅機場" in glossary["forbidden_zh"]["Heathrow Airport"]
