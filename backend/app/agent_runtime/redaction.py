"""外部模型输入脱敏。

原始案件、人员、井点名称和精确位置只在内网工具中使用。该模块在任何
外部模型调用之前，把真实标识转换为单次运行内的临时别名。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict


PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
IDENTITY_RE = re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)")
PLATE_RE = re.compile(r"[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼][A-Z][A-Z0-9]{5,6}")
CASE_REF_RE = re.compile(r"(?i)\bcase:(\d+)\b")
ASSET_REF_RE = re.compile(r"(?i)\b(?:asset|map_asset):(\d+)\b")
CHINESE_CASE_ID_RE = re.compile(r"案件\s*#?\s*(\d+)\b")
CHINESE_ASSET_ID_RE = re.compile(r"(?:地图资源|井点|设施)\s*#?\s*(\d+)\b")

DROP_KEYS = {
    "case_number",
    "description",
    "location",
    "address",
    "name",
    "external_id",
    "latitude",
    "longitude",
    "geometry",
    "attributes",
    "tags",
    "source",
    "source_type",
    "modus_operandi",
    "occurred_time",
    "created_at",
    "updated_at",
    "last_seen_at",
    "police_phone",
    "phone",
    "id_card",
    "identity_number",
    "plate_number",
    "source_signature",
}
SECRET_KEYS = DROP_KEYS | {
    "title",
    "summary",
    "query",
    "asset_name",
    "well_name",
    "person_name",
    "owner_note",
}


@dataclass
class RedactionResult:
    payload: Dict[str, Any]
    aliases: Dict[str, Dict[str, str]] = field(default_factory=dict)


class AgentPayloadRedactor:
    """确定性、可测试的外发上下文脱敏器。"""

    def __init__(self) -> None:
        self._case_aliases: Dict[str, str] = {}
        self._asset_aliases: Dict[str, str] = {}
        self._secrets: set[str] = set()

    def redact(self, payload: Dict[str, Any]) -> RedactionResult:
        self._collect_secrets(payload)
        redacted = self._redact_value(payload, key=None, entity_kind=None)
        return RedactionResult(
            payload=redacted if isinstance(redacted, dict) else {},
            aliases={
                "cases": dict(self._case_aliases),
                "assets": dict(self._asset_aliases),
            },
        )

    def _case_alias(self, value: Any) -> str:
        token = str(value)
        if token not in self._case_aliases:
            self._case_aliases[token] = f"CASE-{len(self._case_aliases) + 1:03d}"
        return self._case_aliases[token]

    def _asset_alias(self, value: Any) -> str:
        token = str(value)
        if token not in self._asset_aliases:
            self._asset_aliases[token] = f"ASSET-{len(self._asset_aliases) + 1:03d}"
        return self._asset_aliases[token]

    def _collect_secrets(self, value: Any, key: str | None = None) -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                self._collect_secrets(child, str(child_key).lower())
            return
        if isinstance(value, (list, tuple)):
            for child in value:
                self._collect_secrets(child, key)
            return
        if key in SECRET_KEYS and value is not None:
            text = str(value).strip()
            if len(text) >= 2:
                self._secrets.add(text)

    @staticmethod
    def _entity_kind(value: dict[str, Any], parent_key: str | None) -> str | None:
        parent = (parent_key or "").lower()
        target_type = str(value.get("target_type") or "").lower()
        if "case" in parent or "case" in target_type or "case_id" in value:
            return "case"
        if (
            parent in {"asset", "production_target", "well", "facility"}
            or any(token in target_type for token in ("asset", "map", "well", "facility"))
            or "asset_id" in value
            or "asset_type" in value
        ):
            return "asset"
        return None

    def _redact_value(
        self,
        value: Any,
        key: str | None,
        entity_kind: str | None,
    ) -> Any:
        normalized_key = (key or "").lower()
        if normalized_key == "case_id" and value is not None:
            return self._case_alias(value)
        if normalized_key == "asset_id" and value is not None:
            return self._asset_alias(value)
        if normalized_key == "case_ids" and isinstance(value, (list, tuple)):
            return [self._case_alias(child) for child in value]
        if normalized_key == "asset_ids" and isinstance(value, (list, tuple)):
            return [self._asset_alias(child) for child in value]
        if normalized_key in {"id", "target_id"} and value is not None:
            if entity_kind == "case":
                return self._case_alias(value)
            if entity_kind == "asset":
                return self._asset_alias(value)
            return "[INTERNAL-ID]"
        if normalized_key.endswith("_id") and value is not None:
            return "[INTERNAL-ID]"
        if normalized_key.endswith("_ids") and isinstance(value, (list, tuple)):
            return ["[INTERNAL-ID]" for _ in value]
        if isinstance(value, dict):
            dictionary_kind = self._entity_kind(value, key) or entity_kind
            return {
                child_key: self._redact_value(child, str(child_key), dictionary_kind)
                for child_key, child in value.items()
                if str(child_key).lower() not in DROP_KEYS
            }
        if isinstance(value, list):
            return [self._redact_value(child, key, entity_kind) for child in value]
        if isinstance(value, tuple):
            return [self._redact_value(child, key, entity_kind) for child in value]
        if isinstance(value, str):
            return self._redact_text(value)
        return value

    def _redact_text(self, value: str) -> str:
        text = value
        for secret in sorted(self._secrets, key=len, reverse=True):
            text = text.replace(secret, "[REDACTED]")
        text = IDENTITY_RE.sub("[ID]", text)
        text = PHONE_RE.sub("[PHONE]", text)
        text = PLATE_RE.sub("[PLATE]", text)
        text = CASE_REF_RE.sub(lambda match: f"case:{self._case_alias(match.group(1))}", text)
        text = ASSET_REF_RE.sub(lambda match: f"asset:{self._asset_alias(match.group(1))}", text)
        text = CHINESE_CASE_ID_RE.sub(
            lambda match: f"案件 {self._case_alias(match.group(1))}",
            text,
        )
        text = CHINESE_ASSET_ID_RE.sub(
            lambda match: f"地图资源 {self._asset_alias(match.group(1))}",
            text,
        )
        return text
