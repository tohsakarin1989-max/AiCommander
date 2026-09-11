"""Compare existing grounded profile terms, not repeated case interpretation."""
from collections import defaultdict
from itertools import groupby

from app.models.case import Case
from app.models.case_pipeline import CaseAnalysisProfile
from app.services.case_semantic_evidence import SourceText, TextReference, freeze_sources, snapshot_payload, ASSERTION_KINDS
from app.services.case_semantic_service import TEXT_FIELDS

CATEGORIES = {'method', 'place_condition', 'time_condition'}
VERSION = 'situation-semantic-changes-4.4-1'


def semantic_window(db, area_id, start, end):
    if 'authorized_area_ids' not in db.info:
        raise PermissionError('situation_read_scope_required')
    allowed = db.info['authorized_area_ids']
    if allowed is not None and area_id not in allowed:
        raise PermissionError('situation_area_forbidden')
    query = db.query(Case, CaseAnalysisProfile).outerjoin(CaseAnalysisProfile,
        (CaseAnalysisProfile.case_id == Case.id) & CaseAnalysisProfile.is_current.is_(True)).filter(
        Case.operational_area_id == area_id, Case.occurred_time >= start, Case.occurred_time < end)
    rows = query.populate_existing().order_by(Case.id, CaseAnalysisProfile.id).yield_per(100)
    groups, evidence, rules = defaultdict(set), defaultdict(list), set()
    total, readable = 0, 0
    unavailable = []
    for case_id, batch in groupby(rows, key=lambda row: row[0].id):
        entries = list(batch)
        total += 1
        case, profile = entries[0]
        if len(entries) != 1 or profile is None:
            unavailable.append({'case_id': case_id, 'reason': 'missing_or_ambiguous_current_profile'})
            continue
        try:
            semantics = profile.payload['semantics']
            # This comparison consumes only text-derived terms. Check all exact
            # source fields in one case row, without rerunning extraction or
            # querying vehicle/person tables once per case.
            expected = snapshot_payload(freeze_sources({field: getattr(case, field) for field in TEXT_FIELDS}))
            if semantics['source_snapshot'] != expected:
                raise ValueError('semantic_text_changed')
            rule = semantics['rule_version']
            if not isinstance(rule, str) or not rule:
                raise ValueError('semantic_rule_missing')
            sources = {row['field']: SourceText(**row) for row in expected['fields']}
            assertions = semantics['assertions']
            if not isinstance(assertions, list):
                raise ValueError('semantic_assertions_invalid')
            verified = {}
            for assertion in assertions:
                if assertion['category'] not in CATEGORIES:
                    continue
                if (assertion['kind'] not in ASSERTION_KINDS or not isinstance(assertion['value'], str)
                        or not assertion['value'].strip()):
                    raise ValueError('semantic_assertion_invalid')
                reference = TextReference(**assertion['reference'])
                reference.validate(sources[reference.field])
                key = (assertion['category'], assertion['value'], assertion['kind'])
                verified.setdefault(key, {'case_id': case_id, 'profile_id': profile.id,
                    'profile_version': profile.profile_version, 'reference': assertion['reference']})
            # Limited extraction cannot be treated as a complete case profile.
            if any(gap.get('code') == 'extraction_limit' for gap in semantics.get('information_gaps', [])):
                raise ValueError('semantic_extraction_partial')
        except (KeyError, TypeError, ValueError, AttributeError):
            unavailable.append({'case_id': case_id, 'reason': 'stale_invalid_or_partial_semantics'})
            continue
        readable += 1
        rules.add(rule)
        for key, reference in verified.items():
            groups[key].add(case_id)
            evidence[key].append(reference)
    return {'case_count': total, 'readable_case_count': readable, 'rule_versions': sorted(rules),
            'unavailable': unavailable, 'terms': [
                {'category': key[0], 'value': key[1], 'kind': key[2], 'case_count': len(identifiers),
                 'case_ids': sorted(identifiers), 'evidence': evidence[key]}
                for key, identifiers in sorted(groups.items())]}


def semantic_changes(previous, current):
    comparable = (previous['case_count'] == previous['readable_case_count']
                  and current['case_count'] == current['readable_case_count']
                  and len(set(previous['rule_versions'] + current['rule_versions'])) <= 1)
    result = {'algorithm_version': VERSION, 'state': 'comparable' if comparable else 'incomparable',
        'previous': previous, 'current': current, 'changes': [],
        'boundary': '统计原文表述涉及的案件数量，单案重复表述只计一次。肯定、否定、疑似及推断分列，均不等于已核实事实；没有词项不等于现实不存在该条件。'}
    if not comparable:
        result['information_gaps'] = ['画像缺失、过期、截断或规则版本不同，不能将两期数量差异直接解释为业务变化。']
        return result
    before = {(row['category'], row['value'], row['kind']): row['case_count'] for row in previous['terms']}
    after = {(row['category'], row['value'], row['kind']): row['case_count'] for row in current['terms']}
    result['changes'] = [{'category': key[0], 'value': key[1], 'kind': key[2],
                          'previous_count': before.get(key, 0), 'current_count': after.get(key, 0),
                          'case_count_change': after.get(key, 0) - before.get(key, 0)}
                         for key in sorted(before.keys() | after.keys())]
    result['information_gaps'] = ['只覆盖现有提取词典与已录入原文，复杂语境仍需结合证据判断。']
    return result
