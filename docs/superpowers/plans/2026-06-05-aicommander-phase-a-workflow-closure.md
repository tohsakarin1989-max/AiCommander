# AiCommander Phase A Workflow Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase A minimum workflow loop: case entry readiness -> deterministic background review -> read-only suggestion queue -> safe action routing.

**Architecture:** Keep existing pages and APIs. Strengthen pure presentation/model helpers first, then wire backend batch review and suggestion queue behavior behind explicit API calls. `GET /api/suggestions/` remains read-only; write operations stay on explicit POST/PATCH endpoints.

**Tech Stack:** FastAPI, SQLAlchemy, pytest, React 18, TypeScript, TanStack Query, Vitest, existing AiCommander CSS.

---

## Scope

This plan implements only Phase A from `docs/superpowers/specs/2026-06-05-aicommander-abc-upgrade-roadmap-design.md`.

Included:

- Save-before-case-entry readiness signals.
- Backend batch review result contract.
- Suggestion queue categories and routes.
- Guardrail that suggestions GET does not mutate cases.
- Frontend summary and action buttons for the workflow loop.

Excluded:

- Phase B AI report prompt redesign.
- Phase C dashboard layout changes.
- Persistent background job table.
- Public map auto-completion.
- Patrol dispatch or execution workflows.

## File Structure

- Modify: `backend/app/api/suggestions.py`
  - Generate read-only work suggestions from cases, alerts, events, conclusions, meetings, and area risk.
- Modify: `backend/app/api/cases.py`
  - Keep `POST /api/cases/batch-review` and `GET /api/cases/batch-review/{job_id}` as the explicit write/processing path.
- Test: `backend/tests/test_suggestions.py`
  - Lock queue categories, safe wording, safe routes, and read-only GET behavior.
- Test: `backend/tests/test_batch_review.py`
  - Lock batch review progress and issue contract.
- Modify: `frontend/src/pages/Cases/caseEntryReadiness.ts`
  - Pure helper for entry readiness cards.
- Test: `frontend/src/pages/Cases/caseEntryReadiness.test.ts`
  - Lock readiness behavior before page wiring.
- Modify: `frontend/src/pages/Cases/batchReviewPresentation.ts`
  - Pure helper for batch review summary.
- Test: `frontend/src/pages/Cases/batchReviewPresentation.test.ts`
  - Lock aggregate wording and avoid amount exposure.
- Modify: `frontend/src/pages/Suggestions/suggestionPresentation.ts`
  - Pure helper for suggestion labels, filters, stats, and safe routes.
- Test: `frontend/src/pages/Suggestions/suggestionPresentation.test.ts`
  - Lock upgraded categories and route boundaries.
- Modify: `frontend/src/services/cases.ts`
  - Add `batchReviewCases()` and `getBatchReviewJob()`.
- Modify: `frontend/src/services/suggestions.ts`
  - Keep suggestion response types aligned with backend.
- Modify: `frontend/src/types/index.ts`
  - Add or align `BatchReviewResult`, `BatchReviewIssue`, and preprocess result types.
- Modify: `frontend/src/pages/Cases/Cases.tsx`
  - Show readiness and batch review entry/result.
- Modify: `frontend/src/pages/Suggestions/Suggestions.tsx`
  - Execute safe actions and route everything else.
- Modify: `frontend/src/pages/Cases/Cases.css`
  - Style readiness and batch review summary blocks with stable spacing.
- Modify: `frontend/src/pages/Suggestions/Suggestions.css`
  - Style queue filters and item cards with stable two-column item layout.

---

### Task 1: Lock Suggestion Queue Boundaries

**Files:**
- Test: `backend/tests/test_suggestions.py`
- Modify: `backend/app/api/suggestions.py`
- Test: `frontend/src/pages/Suggestions/suggestionPresentation.test.ts`
- Modify: `frontend/src/pages/Suggestions/suggestionPresentation.ts`

- [ ] **Step 1: Write the backend failing test**

Add these tests to `backend/tests/test_suggestions.py`:

```python
def test_suggestions_unifies_real_review_work_items_without_patrol_dispatch():
    db = _session()
    client = _client(db)
    case = _seed_work_items(db)

    response = client.get("/api/suggestions/", params={"limit": 50})

    assert response.status_code == 200
    payload = response.json()
    items = payload["suggestions"]
    assert payload["total"] == len(items)
    types = {item["type"] for item in items}
    assert {
        "data_quality",
        "analysis",
        "bonus",
        "alert",
        "review",
        "experience",
        "report_quality",
        "workflow",
    }.issubset(types)
    actions = {item["action"] for item in items}
    assert "create_patrol" not in actions
    assert "review_prevention_reference" in actions
    assert "open_alert_triage_pack" in actions
    assert any(item["action"] == "review_bonus_data" and item["target_id"] == case.id for item in items)
    assert not any("派发巡逻" in str(item) or "生成巡逻" in str(item) for item in items)


def test_suggestions_get_does_not_mutate_case_quality_or_experience_card():
    db = _session()
    client = _client(db)
    now = datetime.utcnow()
    case = Case(
        case_number="SUG-READ-ONLY",
        occurred_time=now - timedelta(days=1),
        location="萨中作业区",
        case_type="涉油盗窃",
        description="现场发现涉油车辆和软管，待后续人工处理。",
        status="pending",
    )
    db.add(case)
    db.commit()
    db.refresh(case)

    response = client.get("/api/suggestions/", params={"limit": 50})

    assert response.status_code == 200
    db.refresh(case)
    assert case.quality_issues is None
    assert case.quality_score is None
    assert case.features is None
    assert any(
        item["action"] == "generate_experience_card" and item["target_id"] == case.id
        for item in response.json()["suggestions"]
    )
```

- [ ] **Step 2: Run backend test to verify it fails or exposes current gaps**

Run:

```bash
cd backend && source venv/bin/activate && pytest tests/test_suggestions.py -v
```

Expected before implementation: FAIL if `/suggestions` still commits quality/experience changes, omits upgraded categories, or emits patrol-dispatch wording. If the test passes because local work already covers the behavior, inspect `backend/app/api/suggestions.py` and confirm it does not call `refresh_case_quality()` or `build_experience_card()` from the GET handler before marking the backend implementation step complete.

- [ ] **Step 3: Make suggestion generation read-only**

In `backend/app/api/suggestions.py`, ensure quality checks use deterministic evaluation without commit and experience-card checks read existing data only:

```python
quality = case.quality_issues or CaseQualityService.evaluate_case(db, case)

experience = _existing_experience_card(case)
if experience:
    if experience.get("manual_review_status") != "confirmed":
        add_item(
            item_id=f"case-experience-{case.id}",
            item_type="experience",
            priority="medium",
            title=f"复核经验卡：{case.case_number}",
            description="该案件已生成经验卡，需人工确认事实、推断和建议边界后进入经验资产库。",
            target_type="case",
            target_id=case.id,
            action="review_experience_card",
            created_at=case.updated_at or case.created_at,
            meta={"manual_review_status": experience.get("manual_review_status")},
        )
elif _has_experience_card_inputs(case):
    add_item(
        item_id=f"case-experience-{case.id}",
        item_type="experience",
        priority="medium",
        title=f"生成经验卡：{case.case_number}",
        description="该案件可沉淀作案条件、发现方式、防护短板、证据缺口和可复用建议，建议进入批处理或案件研判页生成。",
        target_type="case",
        target_id=case.id,
        action="generate_experience_card",
        created_at=case.updated_at or case.created_at,
        meta={"manual_review_status": "not_generated"},
    )
```

Do not call `CaseQualityService.refresh_case_quality()` or `CaseIntelligenceService.build_experience_card()` from `GET /api/suggestions/`.

- [ ] **Step 4: Write frontend route and label test**

Add this coverage to `frontend/src/pages/Suggestions/suggestionPresentation.test.ts`:

```ts
it('routes only to low-risk review and navigation surfaces', () => {
  expect(getSuggestionRoute(suggestion({ action: 'review_bonus_data', target_id: 188 }))).toBe('/cases/bonus?caseId=188')
  expect(getSuggestionRoute(suggestion({ action: 'review_conclusion', target_id: 12 }))).toBe('/conclusions?conclusionId=12')
  expect(getSuggestionRoute(suggestion({ action: 'open_alert_triage_pack', target_id: 9 }))).toBe('/intelli-inspect?alertId=9')
  expect(getSuggestionRoute(suggestion({ action: 'review_experience_card', target_id: 7 }))).toBe('/case-intelligence?caseId=7')
  expect(getSuggestionRoute(suggestion({ action: 'review_prevention_reference', target_id: '萨中北线' }))).toBe('/case-intelligence?area=%E8%90%A8%E4%B8%AD%E5%8C%97%E7%BA%BF')
  expect(getSuggestionRoute(suggestion({ action: 'create_patrol', target_id: '萨中北线' }))).toBeNull()
})
```

- [ ] **Step 5: Implement frontend labels and safe routes**

In `frontend/src/pages/Suggestions/suggestionPresentation.ts`, keep the action map explicit:

```ts
export const ACTION_LABELS: Record<string, string> = {
  open_case: '查看案件',
  preprocess_case: '执行预处理',
  review_conclusion: '进入结论复核',
  convert_event_to_case: '转为案件',
  generate_conclusion_from_meeting: '打开研判包',
  open_analysis_package: '打开研判包',
  review_bonus_data: '进入奖金核算',
  review_bonus_materials: '进入奖金核算',
  open_alert_triage_pack: '打开研判包',
  review_experience_card: '复核经验卡',
  generate_experience_card: '生成经验卡',
  review_prevention_reference: '查看防控参考',
}
```

And keep route handling constrained:

```ts
export function getSuggestionRoute(suggestion: WorkSuggestion): string | null {
  const targetId = numericTargetId(suggestion)
  switch (suggestion.action) {
    case 'open_case':
      return targetId ? `/cases?caseId=${targetId}` : '/cases'
    case 'review_bonus_data':
    case 'review_bonus_materials':
      return targetId ? `/cases/bonus?caseId=${targetId}` : '/cases/bonus'
    case 'review_conclusion':
      return suggestion.target_id
        ? `/conclusions?conclusionId=${encodeURIComponent(String(suggestion.target_id))}`
        : '/conclusions'
    case 'generate_conclusion_from_meeting':
    case 'open_analysis_package':
      return `/reports?meetingId=${encodeURIComponent(String(suggestion.target_id))}`
    case 'open_alert_triage_pack':
      return targetId ? `/intelli-inspect?alertId=${targetId}` : '/intelli-inspect'
    case 'review_experience_card':
    case 'generate_experience_card':
      return targetId ? `/case-intelligence?caseId=${targetId}` : '/case-intelligence'
    case 'review_prevention_reference':
      return `/case-intelligence?area=${encodeURIComponent(String(suggestion.target_id))}`
    default:
      return null
  }
}
```

- [ ] **Step 6: Run task tests**

Run:

```bash
cd backend && source venv/bin/activate && pytest tests/test_suggestions.py -v
cd frontend && npm run test -- src/pages/Suggestions/suggestionPresentation.test.ts
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/tests/test_suggestions.py backend/app/api/suggestions.py frontend/src/pages/Suggestions/suggestionPresentation.test.ts frontend/src/pages/Suggestions/suggestionPresentation.ts
git commit -m "fix: keep suggestion queue read-only"
```

---

### Task 2: Entry Readiness Before Save

**Files:**
- Test: `frontend/src/pages/Cases/caseEntryReadiness.test.ts`
- Modify: `frontend/src/pages/Cases/caseEntryReadiness.ts`
- Modify: `frontend/src/pages/Cases/Cases.tsx`
- Modify: `frontend/src/pages/Cases/Cases.css`

- [ ] **Step 1: Write failing readiness tests**

In `frontend/src/pages/Cases/caseEntryReadiness.test.ts`, ensure these tests exist:

```ts
it('marks map, preprocessing and experience work as needing attention when core entry data is missing', () => {
  const items = buildCaseEntryReadiness({
    description: '现场发现异常',
  })

  expect(items.find(item => item.key === 'map_analysis')?.status).toBe('attention')
  expect(items.find(item => item.key === 'ai_preprocess')?.status).toBe('attention')
  expect(items.find(item => item.key === 'experience_card')?.action).toContain('作案条件')
})

it('marks analysis features ready when coordinate and enough case description exist', () => {
  const items = buildCaseEntryReadiness({
    latitude: 46.59,
    longitude: 125.12,
    location: '新站作业区',
    description: '夜间巡护时发现管线附近有新鲜车辙和疑似盗采痕迹，现场已封控并记录处置情况。',
    case_type: '管线周边盗采',
  })

  expect(items.find(item => item.key === 'map_analysis')?.status).toBe('ready')
  expect(items.find(item => item.key === 'ai_preprocess')?.status).toBe('ready')
  expect(items.find(item => item.key === 'conclusion_layering')?.status).toBe('ready')
  expect(items.find(item => item.key === 'experience_card')?.status).toBe('ready')
})

it('keeps bonus accounting idle until the user opens a relevant accounting scope', () => {
  const items = buildCaseEntryReadiness({
    description: '现场抓获1人，查扣皮卡车1台。',
    initial_vehicles: [{ plate_number: '黑E12345' }],
    initial_persons: [{ name: '张某' }],
    bonus_has_vehicle: false,
    bonus_has_person: false,
  })

  expect(items.find(item => item.key === 'bonus_accounting')?.status).toBe('idle')
})
```

- [ ] **Step 2: Run test to verify it fails or exposes gaps**

Run:

```bash
cd frontend && npm run test -- src/pages/Cases/caseEntryReadiness.test.ts
```

Expected before implementation: FAIL if the helper is missing or does not classify readiness as specified.

- [ ] **Step 3: Implement readiness helper**

In `frontend/src/pages/Cases/caseEntryReadiness.ts`, implement the pure helper with this shape:

```ts
export type CaseEntryReadinessStatus = 'ready' | 'attention' | 'idle'

export interface CaseEntryReadinessItem {
  key: 'map_analysis' | 'ai_preprocess' | 'bonus_accounting' | 'conclusion_layering' | 'experience_card'
  label: string
  status: CaseEntryReadinessStatus
  impact: string
  action: string
}

export function buildCaseEntryReadiness(
  values: CaseEntryReadinessValues,
  bonusHints: CaseBonusEntryHint[] = buildBonusEntryHints(values)
): CaseEntryReadinessItem[] {
  const hasCoordinate = hasValidCoordinate(values)
  const hasLocation = hasText(values.location)
  const descLength = descriptionLength(values)
  const hasEnoughDescription = descLength >= 30
  const hasBasicDescription = descLength >= 12
  const bonusScopeEnabled = hasBonusScope(values)
  const blockingBonusHints = bonusHints.filter(item => item.blocking)

  const mapItem: CaseEntryReadinessItem = hasCoordinate
    ? {
        key: 'map_analysis',
        label: '地图研判',
        status: 'ready',
        impact: '可进入空间分布、附近要素和链条距离计算。',
        action: '坐标已具备，可保存后参与地图研判。',
      }
    : {
        key: 'map_analysis',
        label: '地图研判',
        status: 'attention',
        impact: hasLocation ? '已填写地点文本，但系统无法稳定计算距离和热区。' : '缺少地点或坐标，地图类分析只能待补。',
        action: '建议用地图选点或填写经纬度；道路、村屯等公共要素由地图参考层补充。',
      }

  const preprocessItem: CaseEntryReadinessItem = hasEnoughDescription
    ? {
        key: 'ai_preprocess',
        label: 'AI 预处理',
        status: 'ready',
        impact: '案情描述足以提取时间、地点、对象和处置线索。',
        action: '可点击自动提取，生成结构化字段供后续研判复用。',
      }
    : {
        key: 'ai_preprocess',
        label: 'AI 预处理',
        status: 'attention',
        impact: hasBasicDescription ? '案情已有基础内容，但发现方式、对象或处置结果可能提取不完整。' : '案情描述偏短，模型只能生成很弱的结构化结果。',
        action: '建议补充发现方式、涉案对象、处置结果、作案条件和证据来源。',
      }

  const bonusItem: CaseEntryReadinessItem = blockingBonusHints.length
    ? {
        key: 'bonus_accounting',
        label: '奖金核算',
        status: 'attention',
        impact: `已开启核算范围，但仍缺 ${blockingBonusHints.map(item => item.label).join('、')}。`,
        action: '案件可以保存；补齐会影响金额的指标前，整案奖金暂不测算。',
      }
    : bonusScopeEnabled
      ? {
          key: 'bonus_accounting',
          label: '奖金核算',
          status: 'ready',
          impact: '已开启的核算范围暂无关键指标缺口。',
          action: '保存后可进入奖金核算页查看材料佐证和人工复核。',
        }
      : {
          key: 'bonus_accounting',
          label: '奖金核算',
          status: 'idle',
          impact: '当前未开启奖金条目，不会参与奖金测算。',
          action: '如案件涉及车辆、人员、涉油或公安佐证，再打开对应开关填写。',
        }

  const conclusionItem: CaseEntryReadinessItem = hasBasicDescription && (hasCoordinate || hasLocation)
    ? {
        key: 'conclusion_layering',
        label: '结论分层',
        status: 'ready',
        impact: '具备事实、推断和建议分层的最低输入条件。',
        action: '保存后系统会在案件详情中展示事实依据、推断边界和建议。',
      }
    : {
        key: 'conclusion_layering',
        label: '结论分层',
        status: 'attention',
        impact: '缺少案情或地点基础信息，结论分层容易只剩泛化表述。',
        action: '至少补齐案发地点和关键事实，再让系统生成分层结论。',
      }

  const experienceItem: CaseEntryReadinessItem = hasEnoughDescription && (hasCoordinate || hasLocation || hasText(values.case_type))
    ? {
        key: 'experience_card',
        label: '经验卡',
        status: 'ready',
        impact: '具备沉淀作案条件、发现方式和复用建议的基础信息。',
        action: '保存后会自动生成经验卡，可在同类案件中复用。',
      }
    : {
        key: 'experience_card',
        label: '经验卡',
        status: 'attention',
        impact: '案情要素不足，经验卡会缺少作案条件或可复用建议。',
        action: '建议补充作案条件、发现方式、防护短板和证据缺口。',
      }

  return [mapItem, preprocessItem, bonusItem, conclusionItem, experienceItem]
}
```

Keep helper functions local in this file: `hasText`, `numeric`, `hasValidCoordinate`, `descriptionLength`, and `hasBonusScope`.

- [ ] **Step 4: Wire readiness cards into case form**

In `frontend/src/pages/Cases/Cases.tsx`, compute readiness from the current form draft:

```tsx
const caseEntryReadiness = useMemo(() => buildCaseEntryReadiness({
  ...formData,
  initial_vehicles: vehicleDrafts,
  initial_persons: personDrafts,
}), [formData, vehicleDrafts, personDrafts])

const readinessAttentionCount = caseEntryReadiness.filter(item => item.status === 'attention').length
const readinessReadyCount = caseEntryReadiness.filter(item => item.status === 'ready').length
```

Render the cards near the form action area:

```tsx
<div className="case-entry-readiness">
  <div className="case-entry-readiness-head">
    <span>保存前预检</span>
    <b>{readinessReadyCount} 项就绪 · {readinessAttentionCount} 项需关注</b>
  </div>
  <div className="case-entry-readiness-grid">
    {caseEntryReadiness.map(item => (
      <div key={item.key} className={`case-readiness-card ${item.status}`}>
        <strong>{item.label}</strong>
        <span>{item.impact}</span>
        <small>{item.action}</small>
      </div>
    ))}
  </div>
</div>
```

- [ ] **Step 5: Add compact styles**

In `frontend/src/pages/Cases/Cases.css`, add:

```css
.case-entry-readiness {
  border: 1px solid var(--line);
  background: var(--panel);
  padding: 12px;
  margin: 12px 0;
}

.case-entry-readiness-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  color: var(--text);
  font-size: 13px;
}

.case-entry-readiness-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 8px;
  margin-top: 10px;
}

.case-readiness-card {
  border: 1px solid var(--line-soft);
  padding: 10px;
  min-height: 98px;
}

.case-readiness-card strong,
.case-readiness-card span,
.case-readiness-card small {
  display: block;
}

.case-readiness-card strong {
  color: var(--text);
  margin-bottom: 6px;
}

.case-readiness-card span {
  color: var(--muted);
  line-height: 1.45;
}

.case-readiness-card small {
  color: var(--muted-2);
  margin-top: 8px;
  line-height: 1.4;
}

.case-readiness-card.ready {
  border-color: color-mix(in srgb, var(--ok) 45%, var(--line));
}

.case-readiness-card.attention {
  border-color: color-mix(in srgb, var(--warn) 45%, var(--line));
}
```

- [ ] **Step 6: Run task tests**

Run:

```bash
cd frontend && npm run test -- src/pages/Cases/caseEntryReadiness.test.ts
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/Cases/caseEntryReadiness.test.ts frontend/src/pages/Cases/caseEntryReadiness.ts frontend/src/pages/Cases/Cases.tsx frontend/src/pages/Cases/Cases.css
git commit -m "feat: add case entry readiness checks"
```

---

### Task 3: Batch Review Contract and Summary

**Files:**
- Test: `backend/tests/test_batch_review.py`
- Modify: `backend/app/api/cases.py`
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/services/cases.ts`
- Test: `frontend/src/pages/Cases/batchReviewPresentation.test.ts`
- Modify: `frontend/src/pages/Cases/batchReviewPresentation.ts`
- Modify: `frontend/src/pages/Cases/Cases.tsx`

- [ ] **Step 1: Write backend batch review test**

Add this test to `backend/tests/test_batch_review.py`:

```python
def test_batch_review_runs_with_deterministic_fallback_and_exposes_progress():
    db = _session()
    client = _client(db)
    _seed(db)

    created = client.post(
        "/api/cases/batch-review",
        json={"limit": 10, "use_llm": False},
    )

    assert created.status_code == 200
    payload = created.json()
    assert payload["job_id"]
    assert payload["status"] == "completed"
    assert payload["progress"] == 100
    assert payload["processed"] == 2
    assert payload["failed"] == 0
    assert payload["issues"]
    assert any(issue["type"] in {"data_quality", "experience", "bonus"} for issue in payload["issues"])

    fetched = client.get(f"/api/cases/batch-review/{payload['job_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["job_id"] == payload["job_id"]
```

- [ ] **Step 2: Run backend test to verify it fails or exposes gaps**

Run:

```bash
cd backend && source venv/bin/activate && pytest tests/test_batch_review.py -v
```

Expected before implementation: FAIL if `batch-review` is missing, lacks `job_id/progress/issues`, or does not expose the stored job by id.

- [ ] **Step 3: Implement backend batch review response**

In `backend/app/api/cases.py`, keep an in-memory job registry for Phase A:

```python
BATCH_REVIEW_JOBS: Dict[str, Dict[str, Any]] = {}
```

Use this request model:

```python
class BatchReviewRequest(BaseModel):
    case_ids: Optional[List[int]] = None
    only_missing: bool = False
    limit: Optional[int] = None
    use_llm: bool = False
```

Implement the explicit processing endpoint:

```python
@router.post("/batch-review")
def create_batch_review_job(
    payload: Optional[BatchReviewRequest] = None,
    db: Session = Depends(get_db),
):
    payload = payload or BatchReviewRequest()
    if payload.limit is not None and payload.limit <= 0:
        raise HTTPException(status_code=400, detail="limit 必须大于 0")

    from app.services.case_intelligence_service import CaseIntelligenceService
    from app.services.preprocess_service import CasePreprocessService

    query = db.query(Case).order_by(Case.occurred_time.desc(), Case.id.desc())
    if payload.case_ids:
        query = query.filter(Case.id.in_(payload.case_ids))
    candidates = query.all()
    total_candidates = len(candidates)
    if payload.limit is not None:
        candidates = candidates[:payload.limit]
    selected_ids = [case.id for case in candidates]

    job_id = str(uuid4())
    job = {
        "job_id": job_id,
        "status": "running",
        "progress": 0,
        "processed": 0,
        "failed": 0,
        "skipped": max(0, total_candidates - len(candidates)),
        "issues": [],
        "started_at": datetime.utcnow().isoformat(),
        "finished_at": None,
        "preprocess": None,
    }
    BATCH_REVIEW_JOBS[job_id] = job

    if not selected_ids:
        job.update({
            "status": "completed",
            "progress": 100,
            "finished_at": datetime.utcnow().isoformat(),
        })
        return job

    try:
        job["preprocess"] = CasePreprocessService.preprocess_cases(
            db,
            case_ids=selected_ids,
            only_missing=payload.only_missing,
            limit=None,
            use_llm=payload.use_llm,
        )
    except Exception as exc:
        job["issues"].append({
            "type": "analysis",
            "priority": "medium",
            "title": "批量预处理降级",
            "detail": f"批量预处理失败，后续质量和门禁检查继续执行：{exc}",
        })

    for index, case_id in enumerate(selected_ids, start=1):
        case = db.query(Case).filter(Case.id == case_id).first()
        if not case:
            job["skipped"] += 1
            continue
        try:
            quality = CaseQualityService.refresh_case_quality(db, case)
            if case.latitude is None or case.longitude is None:
                job["issues"].append({
                    "type": "data_quality",
                    "priority": "medium",
                    "target_type": "case",
                    "target_id": case.id,
                    "title": f"坐标缺口：{case.case_number}",
                    "detail": "缺少经纬度，路径条件复盘、热点识别和地图展示会受限。",
                })

            missing_required = quality.get("missing_required") or []
            if quality.get("level") == "low" or (quality.get("score") or 100) < 70:
                job["issues"].append({
                    "type": "data_quality",
                    "priority": "high" if (quality.get("score") or 0) < 50 else "medium",
                    "target_type": "case",
                    "target_id": case.id,
                    "title": f"案件质量偏低：{case.case_number}",
                    "detail": f"质量分 {quality.get('score')}，缺项 {len(missing_required)} 个。",
                })

            experience = CaseIntelligenceService.build_experience_card(db, case.id)
            if experience.get("manual_review_status") != "confirmed":
                job["issues"].append({
                    "type": "experience",
                    "priority": "medium",
                    "target_type": "case",
                    "target_id": case.id,
                    "title": f"经验卡待复核：{case.case_number}",
                    "detail": "经验卡已生成，需人工确认事实、推断和建议边界。",
                })

            if not case.description:
                job["issues"].append({
                    "type": "report_quality",
                    "priority": "medium",
                    "target_type": "case",
                    "target_id": case.id,
                    "title": f"报告摘要依据不足：{case.case_number}",
                    "detail": "缺少案情描述，报告摘要和经验沉淀可引用内容不足。",
                })

            if settings.ENABLE_BONUS_ACCOUNTING:
                bonus = CaseAutomationService.build_bonus_assessment(db, case)
                calculation_gate = bonus.get("calculation_gate") or {}
                material_gate = bonus.get("material_gate") or {}
                if calculation_gate.get("status") == "blocked_by_data":
                    job["issues"].append({
                        "type": "bonus",
                        "priority": "high",
                        "target_type": "case",
                        "target_id": case.id,
                        "title": f"奖金核算指标缺口：{case.case_number}",
                        "detail": "存在影响奖金金额的关键字段缺口，整案暂不测算。",
                        "missing_items": calculation_gate.get("missing_items") or [],
                    })
                if material_gate.get("status") != "ready" and material_gate.get("missing_materials"):
                    job["issues"].append({
                        "type": "bonus",
                        "priority": "medium",
                        "target_type": "case",
                        "target_id": case.id,
                        "title": f"奖金佐证材料缺口：{case.case_number}",
                        "detail": "材料用于奖金复核佐证，补齐前不能进入发放确认。",
                        "missing_materials": material_gate.get("missing_materials") or [],
                    })

            job["processed"] += 1
        except Exception as exc:
            db.rollback()
            job["failed"] += 1
            job["issues"].append({
                "type": "workflow",
                "priority": "medium",
                "target_type": "case",
                "target_id": case.id,
                "title": f"批处理失败：{case.case_number}",
                "detail": str(exc),
            })
        finally:
            job["progress"] = int(index / len(selected_ids) * 100)

    job["status"] = "completed"
    job["progress"] = 100
    job["finished_at"] = datetime.utcnow().isoformat()
    return job
```

And expose lookup:

```python
@router.get("/batch-review/{job_id}")
def get_batch_review_job(job_id: str):
    job = BATCH_REVIEW_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="批处理任务不存在")
    return job
```

- [ ] **Step 4: Add frontend types and service methods**

In `frontend/src/types/index.ts`, add:

```ts
export interface BatchReviewIssue {
  type: 'data_quality' | 'analysis' | 'review' | 'workflow' | 'bonus' | 'alert' | 'experience' | 'report_quality' | string
  priority: 'high' | 'medium' | 'low' | string
  target_type?: string
  target_id?: number | string
  title: string
  detail: string
  missing_items?: unknown[]
  missing_materials?: string[]
}

export interface BatchReviewResult {
  job_id: string
  status: 'running' | 'completed' | 'failed' | string
  progress: number
  processed: number
  failed: number
  skipped: number
  issues: BatchReviewIssue[]
  started_at?: string
  finished_at?: string | null
  preprocess?: unknown
}
```

In `frontend/src/services/cases.ts`, add:

```ts
batchReviewCases: async (payload?: {
  case_ids?: number[]
  only_missing?: boolean
  limit?: number
  use_llm?: boolean
}): Promise<BatchReviewResult> => {
  const response = await api.post<BatchReviewResult>('/cases/batch-review', payload ?? {})
  return response.data
},

getBatchReviewJob: async (jobId: string): Promise<BatchReviewResult> => {
  const response = await api.get<BatchReviewResult>(`/cases/batch-review/${jobId}`)
  return response.data
},
```

- [ ] **Step 5: Write frontend summary test**

In `frontend/src/pages/Cases/batchReviewPresentation.test.ts`, add:

```ts
it('summarizes successful full background processing without exposing bonus details', () => {
  const summary = summarizeBatchReview({
    job_id: 'job-1',
    status: 'completed',
    progress: 100,
    processed: 188,
    failed: 0,
    skipped: 0,
    issues: [
      { type: 'bonus', priority: 'high', title: '奖金核算指标缺口', detail: '缺少车辆考核类别' },
      { type: 'experience', priority: 'medium', title: '经验卡待复核', detail: '需人工确认' },
    ],
  } as BatchReviewResult)

  expect(summary.severity).toBe('success')
  expect(summary.message).toContain('188 起已处理')
  expect(summary.description).toContain('2 条待办')
  expect(summary.description).not.toContain('¥')
  expect(summary.description).not.toContain('金额')
})
```

- [ ] **Step 6: Implement batch summary helper**

In `frontend/src/pages/Cases/batchReviewPresentation.ts`, implement:

```ts
import type { BatchReviewResult } from '../../types'

export function summarizeBatchReview(result: BatchReviewResult): {
  severity: 'success' | 'warning'
  message: string
  description: string
} {
  const severity = result.failed > 0 ? 'warning' : 'success'
  const issueCount = result.issues.length
  return {
    severity,
    message: `后台处理完成：${result.processed} 起已处理，${result.failed} 起失败，${result.skipped} 起跳过`,
    description: `已形成 ${issueCount} 条待办：低质量案件、结论/报告质量、经验卡复核、奖金指标或材料缺口会进入待办中心。`,
  }
}
```

- [ ] **Step 7: Wire Cases page batch action**

In `frontend/src/pages/Cases/Cases.tsx`, add state and mutation:

```tsx
const [batchReviewResult, setBatchReviewResult] = useState<BatchReviewResult | null>(null)
const batchReviewSummary = useMemo(
  () => (batchReviewResult ? summarizeBatchReview(batchReviewResult) : null),
  [batchReviewResult]
)

const batchReviewMutation = useMutation({
  mutationFn: () => caseApi.batchReviewCases({ limit: 500, use_llm: false }),
  onSuccess: async (data) => {
    setBatchReviewResult(data)
    message.success(`后台处理完成：处理 ${data.processed} 起，发现 ${data.issues.length} 条待办`)
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['cases'] }),
      queryClient.invalidateQueries({ queryKey: ['suggestions'] }),
    ])
  },
  onError: (err: AxiosError<{ detail?: string }>) => {
    message.error(`后台处理失败: ${err.response?.data?.detail || err.message}`)
  },
})
```

Render the button and result:

```tsx
<button
  className="btn-primary"
  disabled={batchReviewMutation.isPending}
  onClick={() => batchReviewMutation.mutate()}
>
  <ApiOutlined /> {batchReviewMutation.isPending ? '后台处理中' : '一键后台处理'}
</button>

{batchReviewResult && batchReviewSummary && (
  <Alert
    showIcon
    closable
    type={batchReviewSummary.severity}
    onClose={() => setBatchReviewResult(null)}
    message={batchReviewSummary.message}
    description={batchReviewSummary.description}
  />
)}
```

- [ ] **Step 8: Run task tests**

Run:

```bash
cd backend && source venv/bin/activate && pytest tests/test_batch_review.py -v
cd frontend && npm run test -- src/pages/Cases/batchReviewPresentation.test.ts
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/tests/test_batch_review.py backend/app/api/cases.py frontend/src/types/index.ts frontend/src/services/cases.ts frontend/src/pages/Cases/batchReviewPresentation.test.ts frontend/src/pages/Cases/batchReviewPresentation.ts frontend/src/pages/Cases/Cases.tsx
git commit -m "feat: add case batch review workflow"
```

---

### Task 4: Suggestion Page Safe Actions

**Files:**
- Modify: `frontend/src/pages/Suggestions/Suggestions.tsx`
- Modify: `frontend/src/services/suggestions.ts`
- Modify: `frontend/src/pages/Suggestions/Suggestions.css`

- [ ] **Step 1: Align suggestion service types**

In `frontend/src/services/suggestions.ts`, keep the response type broad enough for backend categories:

```ts
export type SuggestionType =
  | 'data_quality'
  | 'analysis'
  | 'review'
  | 'workflow'
  | 'bonus'
  | 'alert'
  | 'experience'
  | 'report_quality'

export interface WorkSuggestion {
  id: string
  type: SuggestionType | string
  priority: 'high' | 'medium' | 'low'
  title: string
  description: string
  target_type: 'case' | 'event' | 'conclusion' | 'meeting' | 'area' | 'alert' | string
  target_id: number | string
  action: string
  status: string
  created_at: string
  meta?: Record<string, unknown>
}
```

- [ ] **Step 2: Wire safe actions**

In `frontend/src/pages/Suggestions/Suggestions.tsx`, keep direct mutations only for explicit safe actions:

```tsx
const preprocessMutation = useMutation({
  mutationFn: (caseId: number) => caseApi.preprocessCase(caseId),
  onSuccess: async (result) => {
    message.success(result.message || '预处理任务已提交')
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['suggestions'] }),
      queryClient.invalidateQueries({ queryKey: ['cases'] }),
    ])
  },
  onError: (error: Error) => message.error(`预处理失败：${error.message}`),
})

const convertEventMutation = useMutation({
  mutationFn: (eventId: number) => eventApi.convertToCase(eventId),
  onSuccess: async (result) => {
    message.success(result.message || '事件已转案件')
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['suggestions'] }),
      queryClient.invalidateQueries({ queryKey: ['events'] }),
      queryClient.invalidateQueries({ queryKey: ['cases'] }),
    ])
    navigate(`/cases?caseId=${result.case_id}`)
  },
  onError: (error: Error) => message.error(`转案件失败：${error.message}`),
})

const handleAction = (suggestion: WorkSuggestion) => {
  const targetId = numericTargetId(suggestion)
  switch (suggestion.action) {
    case 'preprocess_case':
      if (targetId) preprocessMutation.mutate(targetId)
      break
    case 'convert_event_to_case':
      if (targetId) convertEventMutation.mutate(targetId)
      break
    default:
      {
        const route = getSuggestionRoute(suggestion)
        if (route) {
          navigate(route)
        } else {
          message.info('该待办仅支持人工复核，不自动创建执行记录')
        }
      }
  }
}
```

- [ ] **Step 3: Keep queue rendering compact**

Render filter counts and item action buttons:

```tsx
<div className="sg-filter-row">
  {SUGGESTION_FILTERS.map(filter => (
    <button
      key={filter.value}
      className={`sg-filter${typeFilter === filter.value ? ' on' : ''}`}
      onClick={() => setTypeFilter(filter.value)}
    >
      {filter.label}
      {filter.value !== 'all' && <span>{stats.type[filter.value] || 0}</span>}
    </button>
  ))}
</div>
```

```tsx
<button
  className="btn-primary"
  disabled={actionBusy}
  onClick={() => handleAction(suggestion)}
>
  {ACTION_LABELS[suggestion.action] ?? '处理'}
</button>
```

- [ ] **Step 4: Add stable queue layout CSS**

In `frontend/src/pages/Suggestions/Suggestions.css`, add:

```css
.sg-filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.sg-filter {
  border: 1px solid var(--line);
  background: var(--panel);
  color: var(--text);
  padding: 6px 10px;
  cursor: pointer;
}

.sg-filter.on {
  border-color: var(--accent);
  color: var(--accent);
}

.sg-filter span {
  margin-left: 6px;
  color: var(--muted);
}

.sg-list {
  display: grid;
  gap: 10px;
}

.sg-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  align-items: center;
  border: 1px solid var(--line);
  padding: 12px;
}
```

- [ ] **Step 5: Run task tests**

Run:

```bash
cd frontend && npm run test -- src/pages/Suggestions/suggestionPresentation.test.ts
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Suggestions/Suggestions.tsx frontend/src/services/suggestions.ts frontend/src/pages/Suggestions/Suggestions.css
git commit -m "feat: wire suggestion queue actions"
```

---

### Task 5: Phase A Verification

**Files:**
- Verify only: no planned file edits.

- [ ] **Step 1: Run backend regression tests**

Run:

```bash
cd backend && source venv/bin/activate && pytest \
  tests/test_case_service.py \
  tests/test_case_automation.py \
  tests/test_case_intelligence.py \
  tests/test_suggestions.py \
  tests/test_batch_review.py \
  -v
```

Expected: PASS.

- [ ] **Step 2: Run frontend focused tests**

Run:

```bash
cd frontend && npm run test -- \
  src/pages/Cases/caseEntryReadiness.test.ts \
  src/pages/Cases/batchReviewPresentation.test.ts \
  src/pages/Suggestions/suggestionPresentation.test.ts
```

Expected: PASS.

- [ ] **Step 3: Run frontend build**

Run:

```bash
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 4: Start local services**

If no service is listening on ports 3000 and 8000, run:

```bash
cd backend && source venv/bin/activate && uvicorn app.main:app --reload
```

In another terminal:

```bash
cd frontend && npm run dev
```

Expected:

- Backend API available at `http://127.0.0.1:8000/docs`.
- Frontend available at `http://127.0.0.1:3000`.

- [ ] **Step 5: Browser smoke test**

Open and manually verify:

- `http://127.0.0.1:3000/cases`
  - Save-before-entry readiness cards render in the case form.
  - One-click background processing returns a summary.
- `http://127.0.0.1:3000/suggestions`
  - Categories include data quality, analysis, bonus, alert, review, experience, report quality, and workflow when fixtures trigger them.
  - `preprocess_case` triggers preprocessing.
  - `convert_event_to_case` converts an event.
  - review actions route to existing review pages.
  - unknown unsafe actions show the manual-review message and do not create patrol tasks.

- [ ] **Step 6: Commit verification notes if a tracked doc is updated**

If verification notes are added to a tracked file, commit them:

```bash
git add docs/superpowers/plans/2026-06-05-aicommander-phase-a-workflow-closure.md
git commit -m "docs: record phase a verification"
```

When verification produces no tracked file changes, stop after recording the command results in the handoff message.

---

## Self-Review Checklist

- Spec coverage:
  - Save-before-entry readiness is covered by Task 2.
  - Explicit background processing is covered by Task 3.
  - Suggestion queue categories and routes are covered by Tasks 1 and 4.
  - Read-only `GET /api/suggestions/` is covered by Task 1.
  - Phase A verification is covered by Task 5.
- No Phase B prompt rewrite is included.
- No Phase C dashboard layout work is included.
- No patrol dispatch action is introduced.
- Bonus accounting stays behind case/bonus routes and summary wording avoids amount exposure.
