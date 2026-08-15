from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_manual_image_relation_switch_defaults_on_and_loads_behavior():
    template = (ROOT / "templates" / "manual.html").read_text(encoding="utf-8")
    script = (ROOT / "static" / "manual-image-relation.js").read_text(
        encoding="utf-8"
    )

    assert 'id="image-direct-relation" type="checkbox" checked' in template
    assert "manual-image-relation.js" in template
    assert 'image.provider !== "AVWIRE manual upload"' in script
    assert "image.manualDirectRelation = directlyRelated" in script
    assert 'directlyRelated ? "event_photo" : "file_photo"' in script
