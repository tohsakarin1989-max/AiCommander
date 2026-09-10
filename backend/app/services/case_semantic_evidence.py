"""案件语义提取的内网原文快照与引用契约，不执行推理或外发。"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Mapping


SOURCE_FIELDS = frozenset({
    "description", "location", "modus_operandi", "facility_type", "oil_type",
    "vehicle_info", "involved_items", "upstream_source", "downstream_destination",
})
ASSERTION_KINDS = frozenset({"stated", "negated", "uncertain", "inferred"})


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SourceText:
    field: str
    text: str
    sha256: str

    def __post_init__(self) -> None:
        if self.field not in SOURCE_FIELDS or not isinstance(self.text, str):
            raise ValueError("invalid_semantic_source")
        if self.sha256 != text_hash(self.text):
            raise ValueError("semantic_source_hash_mismatch")


@dataclass(frozen=True)
class TextReference:
    """start包含、end不包含，索引单位为Unicode字符，绝非UTF-8字节。"""

    field: str
    source_sha256: str
    start: int
    end: int
    quote: str

    def validate(self, source: SourceText) -> None:
        if self.field != source.field or self.source_sha256 != source.sha256:
            raise ValueError("semantic_reference_source_mismatch")
        if type(self.start) is not int or type(self.end) is not int:
            raise ValueError("invalid_semantic_reference_span")
        if not 0 <= self.start < self.end <= len(source.text):
            raise ValueError("invalid_semantic_reference_span")
        if source.text[self.start:self.end] != self.quote:
            raise ValueError("semantic_reference_quote_mismatch")


def freeze_sources(values: Mapping[str, str | None]) -> tuple[SourceText, ...]:
    """仅接受明确的业务字段；不读取对象其他属性，不清洗原文字符位置。"""
    if set(values) - SOURCE_FIELDS:
        raise ValueError("unsupported_semantic_source_field")
    result = []
    for field, value in sorted(values.items()):
        if value is None or value == "":
            continue
        if not isinstance(value, str):
            raise ValueError("invalid_semantic_source_value")
        result.append(SourceText(field, value, text_hash(value)))
    return tuple(result)


def snapshot_payload(sources: tuple[SourceText, ...]) -> dict:
    fields = [source.field for source in sources]
    if len(fields) != len(set(fields)):
        raise ValueError("duplicate_semantic_source_field")
    records = [asdict(source) for source in sorted(sources, key=lambda item: item.field)]
    encoded = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {"schema_version": "semantic-source-1", "sha256": text_hash(encoded), "fields": records}


def grounded_assertion(
    source: SourceText, reference: TextReference, *, category: str,
    normalized_value: str, kind: str,
) -> dict:
    """校验出处而非证明内容为真；语义判定仍须由提取规则/内网模型验证。"""
    reference.validate(source)
    if kind not in ASSERTION_KINDS:
        raise ValueError("invalid_semantic_assertion_kind")
    if not isinstance(category, str) or not category.strip():
        raise ValueError("invalid_semantic_category")
    if not isinstance(normalized_value, str) or not normalized_value.strip():
        raise ValueError("invalid_semantic_normalized_value")
    return {
        "category": category, "value": normalized_value, "kind": kind,
        "reference": asdict(reference), "reference_verified": True,
        "is_official_fact": False,
    }
