import pytest

from app.services.case_semantic_service import build_semantic_profile


@pytest.mark.parametrize("text,kind", [
    ("无罐车", "negated"),
    ("罐车不在现场", "negated"),
    ("罐车未到场", "negated"),
    ("未发现罐车", "negated"),
    ("不能排除罐车", "uncertain"),
    ("并非没有罐车", "uncertain"),
    ("没有发现罐车和货车", "uncertain"),
])
def test_shared_profile_does_not_promote_negative_mentions(text, kind):
    assertions = build_semantic_profile({"description": text})["assertions"]
    assert assertions
    assert all(item["kind"] == kind for item in assertions)


def test_public_classifier_preserves_custom_terms_and_unicode_references():
    from app.services.case_semantic_mentions import extract_term_assertions

    text = "🚗未发现罐车，但发现油桶；疑似软管。"
    result = extract_term_assertions(
        {"description": text},
        {"vehicle": {"罐车": "tanker"}, "tool": {"油桶": "bucket", "软管": "hose"}},
    )
    assert {(item["value"], item["kind"]) for item in result["assertions"]} == {
        ("tanker", "negated"), ("bucket", "stated"), ("hose", "uncertain"),
    }
    for item in result["assertions"]:
        reference = item["reference"]
        assert text[reference["start"]:reference["end"]] == reference["quote"]
        assert text[slice(*item["mention_span"])] in {"罐车", "油桶", "软管"}
        assert item["reference_verified"] is True
        assert item["is_official_fact"] is False


@pytest.mark.parametrize("text,term,kind", [
    ("无牌车辆", "无牌", "stated"),
    ("现场未上锁", "未上锁", "stated"),
    ("现场无照明", "无照明", "stated"),
    ("未发现无牌", "无牌", "negated"),
    ("疑似未上锁", "未上锁", "uncertain"),
    ("并非无照明", "无照明", "negated"),
])
def test_negation_inside_business_term_is_not_self_negation(text, term, kind):
    from app.services.case_semantic_mentions import extract_term_assertions

    result = extract_term_assertions({"description": text}, {"condition": {term: "condition"}})
    assert result["assertions"][0]["kind"] == kind


def test_fields_and_contrast_have_independent_scope():
    from app.services.case_semantic_mentions import extract_term_assertions

    result = extract_term_assertions(
        {"description": "未发现罐车但发现油桶", "location": "软管在场"},
        {"terms": {"罐车": "罐车", "油桶": "油桶", "软管": "软管"}},
    )
    assert {(item["value"], item["kind"]) for item in result["assertions"]} == {
        ("罐车", "negated"), ("油桶", "stated"), ("软管", "stated"),
    }


def test_budget_is_global_and_partial_is_explicit():
    from app.services.case_semantic_mentions import extract_term_assertions

    result = extract_term_assertions(
        {"description": "油桶。" * 205, "location": "油桶"}, {"tool": {"油桶": "油桶"}},
    )
    assert len(result["assertions"]) == 200
    assert result["information_gaps"] == [{"code": "extraction_limit", "field": "description"}]


def test_exact_budget_is_not_marked_partial():
    from app.services.case_semantic_mentions import extract_term_assertions

    result = extract_term_assertions({"description": "油桶。" * 200}, {"tool": {"油桶": "油桶"}})
    assert len(result["assertions"]) == 200
    assert result["information_gaps"] == []


def test_profile_lineage_entries_also_respect_global_budget():
    result = build_semantic_profile({
        "description": "油桶。" * 200,
        "upstream_source": "北区某井",
        "downstream_destination": "东区站点",
    })
    assert len(result["assertions"]) == 200
    assert any(gap["code"] == "extraction_limit" for gap in result["information_gaps"])


def test_classifier_rejects_derived_or_structured_text_values():
    from app.services.case_semantic_mentions import extract_term_assertions

    with pytest.raises(ValueError, match="unsupported_semantic_source_field"):
        extract_term_assertions({"features": "软管"}, {"tool": {"软管": "软管"}})
    with pytest.raises(ValueError, match="invalid_semantic_source_value"):
        extract_term_assertions({"vehicle_info": {"套牌": False}}, {"vehicle": {"套牌": "套牌"}})
