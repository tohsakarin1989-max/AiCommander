"""共享的有原文引用词项分类器；不把复杂否定或待核表述转成肯定事实。"""
from __future__ import annotations

import re
from typing import Mapping

from app.services.case_semantic_evidence import TextReference, freeze_sources, grounded_assertion


UNCERTAIN = re.compile(
    r"可能|疑似|不详|不确定|不能确定|无法确定|不能排除|不排除|未排除|并非没有|不是没有|"
    r"没有证据|未证实|未确认|待核|待查|不清楚|否认|假设|如果|是否|\?|？|"
    r"忽略|指令|提示词|system|assistant|[“”\"「」]",
    re.IGNORECASE,
)
# 保留公开常量供原有模型引用校验使用；词项分类另作保守的作用域检查。
NEGATED = re.compile(r"未发现|未见|未查获|未使用|未携带|没有|不存在|不是|并非|不在|未到场|未出现")
CLAUSE = re.compile(r"[^，,。；;！!\n]+")
CONTRAST = re.compile(r"但是|然而|不过|但")
NEGATIVE_MARKER = re.compile(r"没有|并非|不是|未|无|不")
DIRECT_PREFIX = re.compile(
    r"(?:未发现|未见|未查获|未使用|未携带|没有(?:发现)?|不存在|不是|并非|无|不见)$"
)
DIRECT_SUFFIXES = frozenset({"未见", "未发现", "不存在", "不在现场", "不在场", "未到场", "未出现"})


def mention_kind(text: str, start: int, end: int) -> str:
    """只分类一次词项表述；词项内部的“无牌/未上锁”等不是自身否定。"""
    before, after = text[:start].strip(), text[end:].strip()
    # 留一个不可匹配的占位字符，不让前后文字拼成新的否定/不确定词。
    outside = before + "\ufffc" + after
    if UNCERTAIN.search(outside):
        return "uncertain"
    negatives = list(NEGATIVE_MARKER.finditer(outside))
    if not negatives:
        return "stated"
    # 双重否定和复杂作用域不自动化简成肯定或否定。
    if len(negatives) != 1:
        return "uncertain"
    if (DIRECT_PREFIX.search(before) and not after) or (after in DIRECT_SUFFIXES and not before):
        return "negated"
    return "uncertain"


def extract_term_assertions(
    values: Mapping[str, str | None],
    terms: Mapping[str, Mapping[str, str]],
    *,
    limit: int = 200,
) -> dict:
    """用调用方的固定词典提取标准引用；预算对整个调用生效。

    ``terms`` 为 ``{category: {原始词项: 归一值}}``。输入仅接受既有原文
    字段白名单及字符串，不将 JSON 键、布尔值或派生 features 当作原文。
    未命中不代表不存在；达到预算只有发现额外命中时才标记不完整。
    """
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError("invalid_semantic_assertion_limit")
    sources = freeze_sources(values)
    patterns = []
    for category, vocabulary in terms.items():
        if not isinstance(category, str) or not category.strip() or not isinstance(vocabulary, Mapping):
            raise ValueError("invalid_semantic_terms")
        if any(not isinstance(term, str) or not term.strip() or
               not isinstance(value, str) or not value.strip() for term, value in vocabulary.items()):
            raise ValueError("invalid_semantic_terms")
        if vocabulary:
            pattern = "|".join(re.escape(term) for term in sorted(vocabulary, key=lambda term: (-len(term), term)))
            patterns.append((category, vocabulary, re.compile(pattern)))
    assertions = []
    for source in sources:
        for clause in CLAUSE.finditer(source.text):
            offset = clause.start()
            boundaries = list(CONTRAST.finditer(clause.group()))
            ranges = []
            cursor = 0
            for boundary in boundaries:
                ranges.append((cursor, boundary.start()))
                cursor = boundary.end()
            ranges.append((cursor, len(clause.group())))
            for part_start, part_end in ranges:
                start = offset + part_start
                text = source.text[start:offset + part_end]
                for category, vocabulary, pattern in patterns:
                    for match in pattern.finditer(text):
                        if len(assertions) >= limit:
                            return {"assertions": assertions, "information_gaps": [
                                {"code": "extraction_limit", "field": source.field},
                            ]}
                        reference = TextReference(source.field, source.sha256, start, start + len(text), text)
                        assertion = grounded_assertion(
                            source, reference, category=category,
                            normalized_value=vocabulary[match.group()],
                            kind=mention_kind(text, match.start(), match.end()),
                        )
                        assertion["mention_span"] = [start + match.start(), start + match.end()]
                        assertions.append(assertion)
    return {"assertions": assertions, "information_gaps": []}
