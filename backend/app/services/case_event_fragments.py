"""内网事件片段：保留句内共现，不把共现提升为主体、来源或因果关系。"""
from dataclasses import asdict
import re

from app.services.case_semantic_evidence import SourceText, TextReference, text_hash


FRAGMENT_VERSION = "event-fragments-5.1-1"
MAX_FRAGMENTS = 100
SENTENCES = re.compile(r"[^。；;！!？?\n]+[。；;！!？?]?")
PARTS = re.compile(r"[^，,。；;！!？?\n]+")
ACTIONS = {
    "打孔盗油": "打孔盗油", "打眼盗油": "打孔盗油",
    "盗取": "盗取", "盗窃": "盗取", "抽取": "抽取", "抽油": "抽取",
    "转运": "转运", "装运": "装运", "装油": "装载", "卸油": "卸载",
    "储存": "储存", "囤储": "储存", "囤油": "储存", "存放": "存放",
    "销售": "销售", "销赃": "销赃", "收购": "收购",
}
ACTION_PATTERN = re.compile("|".join(map(re.escape, sorted(ACTIONS, key=len, reverse=True))))
UNCERTAIN = re.compile(
    r"可能|疑似|不详|不确定|不能|无法|不排除|未排除|并非没有|不是没有|"
    r"没有证据|未证实|否认|假设|如果|是否|[?？]|忽略|指令|提示词|system|assistant|[“”\"「」]",
    re.IGNORECASE,
)
NEGATION = re.compile(r"未|没有|无|不|并非|不是")
DIMENSIONS = {
    "time": {"time_condition"}, "facility": {"facility"}, "oil": {"oil"},
    "place": {"place_condition"}, "upstream": {"upstream_clue"},
    "downstream": {"downstream_clue"},
}


def action_kind(text: str, start: int) -> str:
    if UNCERTAIN.search(text):
        return "uncertain"
    before = text[:start].rstrip()
    if re.search(r"(?:未(?:曾|进行)?|没有(?:进行)?|并未|不曾|并非|不是)$", before):
        return "negated"
    # 复杂否定的作用范围不由动作词前缀猜测。
    return "uncertain" if NEGATION.search(text) else "stated"


def build_event_fragments(sources: tuple[SourceText, ...], assertions: list[dict],
                          time_intervals: list[dict], information_gaps: list[dict]) -> dict:
    fragments, omitted = [], 0
    for source in sources:
        for sentence in SENTENCES.finditer(source.text):
            reference = TextReference(source.field, source.sha256, sentence.start(),
                                      sentence.end(), sentence.group())
            actions = []
            for clause in PARTS.finditer(sentence.group()):
                # 转折两侧分别判断；不跨逗号继承主体、时间或否定范围。
                for part in re.finditer(r"(?:(?!但是|但|然而|不过).)+", clause.group()):
                    text = part.group()
                    offset = sentence.start() + clause.start() + part.start()
                    for match in ACTION_PATTERN.finditer(text):
                        action_ref = TextReference(source.field, source.sha256, offset + match.start(),
                                                   offset + match.end(), match.group())
                        action_ref.validate(source)
                        # 句末问号和引用提示作用于整个片段，不在分词后丢失。
                        kind = "uncertain" if UNCERTAIN.search(sentence.group()) else action_kind(text, match.start())
                        actions.append({"value": ACTIONS[match.group()], "kind": kind,
                                        "reference": asdict(action_ref), "is_official_fact": False})

            def contained(item):
                ref = item.get("reference") or {}
                return (ref.get("field") == source.field and ref.get("source_sha256") == source.sha256
                        and sentence.start() <= ref.get("start", -1)
                        and ref.get("end", len(source.text) + 1) <= sentence.end())

            indices = [index for index, item in enumerate(assertions) if contained(item)]
            times = [index for index, item in enumerate(time_intervals) if contained(item)]
            if not actions and not indices and not times:
                continue
            if len(fragments) >= MAX_FRAGMENTS:
                omitted += 1
                continue
            reference.validate(source)
            stated_categories = {assertions[index]["category"] for index in indices
                                 if assertions[index]["kind"] == "stated"}
            missing = [key for key, categories in DIMENSIONS.items()
                       if not stated_categories.intersection(categories) and not (key == "time" and times)]
            if not any(action["kind"] == "stated" for action in actions):
                missing.insert(0, "action")
            fragments.append({
                "id": text_hash(f"{FRAGMENT_VERSION}:{source.field}:{source.sha256}:{sentence.start()}:{sentence.end()}"),
                "reference": asdict(reference), "actions": actions,
                "assertion_indices": indices, "time_interval_indices": times,
                "missing_dimensions": missing,
                "information_gaps": [item for item in information_gaps if contained(item)],
                "relation_status": "sentence_cooccurrence_only", "is_official_fact": False,
            })
    input_partial = any(item.get("code") == "extraction_limit" for item in information_gaps)
    return {
        "schema_version": FRAGMENT_VERSION, "items": fragments,
        "coverage": {"limit": MAX_FRAGMENTS, "omitted_fragments": omitted,
                     "input_assertions_partial": input_partial,
                     "state": "partial" if omitted or input_partial else "rule_scan_complete"},
        "deep_model_status": "not_enabled",
        "boundary": "事件片段仅组织原文中的动作和句内条件；共现不证明同一主体、来源去向、因果或实际轨迹。未命中规则不等于没有事件。",
    }
