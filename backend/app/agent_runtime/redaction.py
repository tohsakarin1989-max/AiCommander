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
CASE_REF_RE = re.compile(r"^case:(\d+)$")
ASSET_REF_RE = re.compile(r"^asset:(\d+)$")

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
        redacted = self._redact_value(payload, key=None)
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

    def _redact_value(self, value: Any, key: str | None) -> Any:
        normalized_key = (key or "").lower()
        if normalized_key == "case_id" and value is not None:
            return self._case_alias(value)
        if normalized_key == "asset_id" and value is not None:
            return self._asset_alias(value)
        if isinstance(value, dict):
            return {
                child_key: self._redact_value(child, str(child_key))
                for child_key, child in value.items()
                if str(child_key).lower() not in DROP_KEYS
            }
        if isinstance(value, list):
            return [self._redact_value(child, key) for child in value]
        if isinstance(value, tuple):
            return [self._redact_value(child, key) for child in value]
        if isinstance(value, str):
            case_match = CASE_REF_RE.match(value)
            if case_match:
                return f"case:{self._case_alias(case_match.group(1))}"
            asset_match = ASSET_REF_RE.match(value)
            if asset_match:
                return f"asset:{self._asset_alias(asset_match.group(1))}"
            return self._redact_text(value)
        return value

    def _redact_text(self, value: str) -> str:
        text = value
        for secret in sorted(self._secrets, key=len, reverse=True):
            text = text.replace(secret, "[REDACTED]")
        text = IDENTITY_RE.sub("[ID]", text)
        text = PHONE_RE.sub("[PHONE]", text)
        text = PLATE_RE.sub("[PLATE]", text)
        return text
