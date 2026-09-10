"""结构化案件字段的冻结与路径引用；不伪造原文字符位置。"""
import hashlib
import json
from typing import Any


FIELDS = frozenset({"vehicle_info", "involved_items"})


def _encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_encode(value).encode("utf-8")).hexdigest()


def resolve_reference(snapshot: dict, reference: dict) -> Any:
    if snapshot.get("field") not in FIELDS or reference.get("field") != snapshot["field"]:
        raise ValueError("structured_reference_field_mismatch")
    digest = _digest(snapshot["value"])
    if snapshot.get("sha256") != digest or reference.get("source_sha256") != digest:
        raise ValueError("structured_reference_hash_mismatch")
    path = reference.get("path")
    if not isinstance(path, list) or len(path) > 8:
        raise ValueError("invalid_structured_reference_path")
    value = snapshot["value"]
    for part in path:
        if isinstance(value, dict) and isinstance(part, str) and part in value:
            value = value[part]
        elif isinstance(value, list) and type(part) is int and 0 <= part < len(value):
            value = value[part]
        else:
            raise ValueError("invalid_structured_reference_path")
    if isinstance(value, (dict, list)) or _encode(value) != _encode(reference.get("value")):
        raise ValueError("structured_reference_value_mismatch")
    return value


def extract_structured_sources(values: dict[str, Any]) -> dict:
    if set(values) - FIELDS:
        raise ValueError("unsupported_structured_source_field")
    snapshots, entries, gaps = [], [], []
    for field, raw in sorted(values.items()):
        if raw is None:
            continue
        try:
            encoded = _encode(raw)
        except (TypeError, ValueError, RecursionError):
            gaps.append({"field": field, "code": "invalid_structured_source"})
            continue
        if len(encoded.encode("utf-8")) > 1024 * 1024:
            gaps.append({"field": field, "code": "structured_source_too_large"})
            continue
        # JSON副本避免后续调用方原地修改影响已经冻结的结果。
        frozen = json.loads(encoded)
        snapshot = {"field": field, "sha256": _digest(frozen), "value": frozen}
        snapshots.append(snapshot)
        pending = [([], frozen)]
        count = 0
        while pending:
            path, value = pending.pop()
            if len(path) > 8 or count >= 200:
                gaps.append({"field": field, "code": "structured_extraction_limit"})
                break
            if isinstance(value, dict):
                pending.extend((path + [key], item) for key, item in reversed(sorted(value.items())))
            elif isinstance(value, list):
                pending.extend((path + [index], item) for index, item in reversed(list(enumerate(value))))
            else:
                reference = {"field": field, "source_sha256": snapshot["sha256"], "path": path, "value": value}
                resolve_reference(snapshot, reference)
                entries.append({"reference": reference, "kind": "recorded_value", "is_official_fact": False})
                count += 1
    return {"snapshots": snapshots, "entries": entries, "information_gaps": gaps}
