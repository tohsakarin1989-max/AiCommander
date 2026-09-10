from dataclasses import replace

import pytest

from app.services.case_semantic_evidence import (
    SourceText, TextReference, freeze_sources, grounded_assertion, snapshot_payload,
)


def test_unicode_reference_keeps_original_whitespace_and_emoji():
    source, = freeze_sources({"description": "  🚗未发现罐车。\n"})
    reference = TextReference(source.field, source.sha256, 3, 8, "未发现罐车")
    result = grounded_assertion(source, reference, category="vehicle", normalized_value="罐车", kind="negated")
    assert result["kind"] == "negated"
    assert result["reference_verified"] is True
    assert result["is_official_fact"] is False
    assert source.text == "  🚗未发现罐车。\n"


@pytest.mark.parametrize("change", [
    {"field": "location"}, {"source_sha256": "0" * 64}, {"start": -1},
    {"start": True}, {"end": 100}, {"end": 0}, {"quote": "伪造原文"},
])
def test_bad_reference_cannot_become_grounded_assertion(change):
    source, = freeze_sources({"description": "发现罐车"})
    reference = TextReference(source.field, source.sha256, 0, 4, source.text)
    with pytest.raises(ValueError):
        grounded_assertion(source, replace(reference, **change), category="vehicle", normalized_value="罐车", kind="stated")


def test_modified_source_invalidates_old_reference_but_frozen_source_remains_readable():
    old, = freeze_sources({"description": "发现罐车"})
    new, = freeze_sources({"description": "未见罐车"})
    reference = TextReference(old.field, old.sha256, 0, 4, old.text)
    reference.validate(old)
    with pytest.raises(ValueError, match="source_mismatch"):
        reference.validate(new)


def test_snapshot_is_deterministic_and_rejects_unrelated_fields():
    left = freeze_sources({"description": "未发现原油", "location": "某井附近"})
    right = freeze_sources({"location": "某井附近", "description": "未发现原油"})
    assert snapshot_payload(left) == snapshot_payload(right)
    with pytest.raises(ValueError):
        freeze_sources({"api_key": "must-not-enter-context"})
    with pytest.raises(ValueError):
        snapshot_payload(left + left)
    with pytest.raises(ValueError):
        SourceText("description", "原文", "invented-hash")


def test_missing_text_does_not_generate_fabricated_reference():
    assert freeze_sources({"description": None, "upstream_source": ""}) == ()
    assert snapshot_payload(())["fields"] == []
