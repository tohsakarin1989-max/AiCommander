# Dashboard Command Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved B1-C v4 command screen on the existing Dashboard page.

**Architecture:** Keep the Dashboard as the page owner, but move data aggregation into a pure TypeScript model helper so it can be tested. Add one lightweight auto-scroll list component for repeated panels, reuse the existing SVG `viewBox` map interactions, and avoid backend schema changes.

**Tech Stack:** React 18, TypeScript, Vite, Vitest, TanStack Query, existing AiCommander CSS design tokens.

---

## File Structure

- Create: `frontend/src/pages/Dashboard/dashboardCommandModel.ts`
  - Pure functions for weekly trends, KPI/readiness summaries, list items, focus cards, and chain map line projection.
- Create: `frontend/src/pages/Dashboard/dashboardCommandModel.test.ts`
  - Vitest coverage for data aggregation and chain link safety boundaries.
- Create: `frontend/src/pages/Dashboard/AutoScrollList.tsx`
  - Small presentational component that duplicates items for slow CSS-based looping and falls back to an empty state.
- Modify: `frontend/src/pages/Dashboard/Dashboard.tsx`
  - Replace the old two-column map/rail page with the approved three-column leadership view while preserving WebSocket, map controls, zoom, drag, fullscreen, and existing queries.
- Modify: `frontend/src/pages/Dashboard/Dashboard.css`
  - Replace old layout CSS with command-screen grid, cards, auto-scroll animation, map source badges, and responsive constraints.

---

### Task 1: Data Model Helpers

**Files:**
- Create: `frontend/src/pages/Dashboard/dashboardCommandModel.ts`
- Test: `frontend/src/pages/Dashboard/dashboardCommandModel.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from 'vitest'
import type { Case, ChainLink } from '../../types'
import {
  buildDashboardModel,
  buildWeeklyTrend,
  projectChainLinks,
} from './dashboardCommandModel'

const baseCase = (id: number, patch: Partial<Case>): Case => ({
  id,
  case_number: `CASE-${id}`,
  occurred_time: '2026-05-01T00:00:00.000Z',
  status: 'pending',
  ...patch,
})

describe('dashboardCommandModel', () => {
  it('builds seven weekly trend buckets from real case dates', () => {
    const cases = [
      baseCase(1, { occurred_time: '2026-05-09T00:00:00.000Z' }),
      baseCase(2, { occurred_time: '2026-05-08T00:00:00.000Z' }),
      baseCase(3, { occurred_time: '2026-04-20T00:00:00.000Z' }),
    ]

    const trend = buildWeeklyTrend(cases, new Date('2026-05-10T00:00:00.000Z'))

    expect(trend).toHaveLength(7)
    expect(trend[6]).toMatchObject({ label: 'W7', count: 2 })
    expect(trend.some(item => item.count === 1)).toBe(true)
  })

  it('projects only non-rejected chain links with complete coordinates', () => {
    const link: ChainLink = {
      id: 1,
      case_id_a: 1,
      case_id_b: 2,
      link_type: 'upstream_transport',
      status: 'inferred',
      confidence: 0.82,
      distance_km: 3.5,
      time_diff_days: 4,
      from_case: {
        id: 1,
        case_number: 'A',
        chain_position: 'upstream',
        chain_label: '盗采环节',
        latitude: 46.6,
        longitude: 125.1,
      },
      to_case: {
        id: 2,
        case_number: 'B',
        chain_position: 'midstream',
        chain_label: '运输环节',
        latitude: 46.62,
        longitude: 125.12,
      },
    }

    const rejected = { ...link, id: 2, status: 'rejected' as const }
    const missingCoordinate = {
      ...link,
      id: 3,
      to_case: { ...link.to_case!, latitude: undefined },
    }

    const lines = projectChainLinks([link, rejected, missingCoordinate])

    expect(lines).toHaveLength(1)
    expect(lines[0]).toMatchObject({ id: 1, status: 'inferred', confidence: 0.82 })
  })

  it('creates empty-state dashboard lists instead of fake numbers when data is missing', () => {
    const model = buildDashboardModel({
      cases: [],
      chainLinks: [],
      areaRisks: [],
      hotspots: [],
      statistics: { total_cases: 0, today_cases: 0, pending_cases: 0, resolved_cases: 0, this_week_cases: 0, this_month_cases: 0 },
      now: new Date('2026-05-10T00:00:00.000Z'),
    })

    expect(model.kpis.materialReadiness.value).toBe('待补录')
    expect(model.aiOutputs[0].tone).toBe('empty')
    expect(model.qualityItems[0].tone).toBe('empty')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- src/pages/Dashboard/dashboardCommandModel.test.ts`

Expected: FAIL because `dashboardCommandModel.ts` does not exist.

- [ ] **Step 3: Write minimal implementation**

Implement:

```ts
export function buildWeeklyTrend(cases: Case[], now = new Date()): TrendBucket[]
export function projectChainLinks(links: ChainLink[]): ProjectedChainLine[]
export function buildDashboardModel(input: DashboardModelInput): DashboardModel
```

Required behavior:

- Weekly trend always returns seven buckets labeled `W1` to `W7`.
- Chain links exclude `rejected` and exclude links missing either endpoint coordinate.
- Empty AI/material/quality sections return explicit empty-state list items instead of hard-coded fake metrics.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- src/pages/Dashboard/dashboardCommandModel.test.ts`

Expected: PASS.

---

### Task 2: Auto-Scroll List Component

**Files:**
- Create: `frontend/src/pages/Dashboard/AutoScrollList.tsx`
- Modify: `frontend/src/pages/Dashboard/Dashboard.css`

- [ ] **Step 1: Write the failing test through the model contract**

Extend `dashboardCommandModel.test.ts` with:

```ts
it('marks panels with enough display rows for unattended screen rotation', () => {
  const model = buildDashboardModel({
    cases: [
      baseCase(1, { latitude: 46.6, longitude: 125.1, facility_type: '管线', quality_score: 91 }),
      baseCase(2, { latitude: 46.62, longitude: 125.12, facility_type: '油罐车', quality_score: 65 }),
    ],
    chainLinks: [],
    areaRisks: [],
    hotspots: [],
    statistics: { total_cases: 2, today_cases: 0, pending_cases: 2, resolved_cases: 0, this_week_cases: 2, this_month_cases: 2 },
    now: new Date('2026-05-10T00:00:00.000Z'),
  })

  expect(model.riskChanges.length).toBeGreaterThanOrEqual(3)
  expect(model.materialTrends.length).toBeGreaterThanOrEqual(3)
})
```

Expected first run: FAIL until the helper returns enough rows for a useful loop.

- [ ] **Step 2: Implement `AutoScrollList`**

```tsx
import type { DashboardListItem } from './dashboardCommandModel'

interface AutoScrollListProps {
  items: DashboardListItem[]
  durationSeconds?: number
}

const AutoScrollList: React.FC<AutoScrollListProps> = ({ items, durationSeconds = 46 }) => {
  const safeItems = items.length > 0
    ? items
    : [{ title: '暂无数据', detail: '等待案件、链条或材料数据接入。', tone: 'empty' as const }]
  const loopItems = [...safeItems, ...safeItems]
  return (
    <div className="db-auto-list" style={{ '--scroll-duration': `${durationSeconds}s` } as React.CSSProperties}>
      <div className="db-auto-track">
        {loopItems.map((item, index) => (
          <div className={`db-list-item db-list-item--${item.tone || 'normal'}`} key={`${item.title}-${index}`}>
            <strong>{item.title}</strong>
            <span>{item.detail}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default AutoScrollList
```

- [ ] **Step 3: Add CSS behavior**

Add CSS classes:

```css
.db-auto-list { position: relative; height: 100%; overflow: hidden; }
.db-auto-list::before,
.db-auto-list::after { content: ""; position: absolute; left: 0; right: 0; height: 16px; z-index: 2; pointer-events: none; }
.db-auto-list::before { top: 0; background: linear-gradient(to bottom, var(--bg-1), transparent); }
.db-auto-list::after { bottom: 0; background: linear-gradient(to top, var(--bg-1), transparent); }
.db-auto-track { display: grid; gap: 8px; padding: 10px; animation: dbAutoScroll var(--scroll-duration, 46s) linear infinite; }
.db-auto-list:hover .db-auto-track { animation-play-state: paused; }
@keyframes dbAutoScroll {
  0%, 16% { transform: translateY(0); }
  84%, 100% { transform: translateY(-50%); }
}
@media (prefers-reduced-motion: reduce) {
  .db-auto-list { overflow-y: auto; }
  .db-auto-track { animation: none; }
}
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && npm run test -- src/pages/Dashboard/dashboardCommandModel.test.ts`

Expected: PASS.

---

### Task 3: Dashboard Layout and Map

**Files:**
- Modify: `frontend/src/pages/Dashboard/Dashboard.tsx`
- Modify: `frontend/src/pages/Dashboard/Dashboard.css`

- [ ] **Step 1: Add data queries**

Add queries for:

```ts
const { data: queriedCases = [] } = useQuery<Case[]>({
  queryKey: ['dashboard-cases'],
  queryFn: () => caseApi.getCases({ limit: 100 }),
  refetchInterval: 60_000,
})

const { data: chainMapData } = useQuery({
  queryKey: ['dashboard-chain-map-data'],
  queryFn: () => caseApi.getChainMapData(),
  refetchInterval: 120_000,
})
```

Use `dashboardCases = cases.length > 0 ? cases : queriedCases`.

- [ ] **Step 2: Build the page model**

```ts
const dashboardModel = useMemo(() => buildDashboardModel({
  cases: dashboardCases,
  chainLinks: chainMapData?.chain_links ?? [],
  areaRisks,
  hotspots: rawHotspots as DashboardHotspot[],
  statistics,
}), [dashboardCases, chainMapData, areaRisks, rawHotspots, statistics])
```

- [ ] **Step 3: Replace the page return**

Use class names:

- `db-command-main`
- `db-command-summary`
- `db-command-board`
- `db-command-map`
- `db-command-focus-grid`

The board must map to:

- `caseTrend`
- `riskChanges`
- `materialTrends`
- `geoMap`
- `weeklyFocus`
- `aiOutputs`
- `reviewItems`
- `qualityItems`

- [ ] **Step 4: Render map sources and chain links**

Map must show:

- real case points by chain position;
- projected chain lines from `projectChainLinks`;
- hotspots from `hotspotSvg`;
- fixed source bar: `坐标=案件经纬度`, `热区=30天密度`, `关系=链条接口`, `缺口=坐标/材料`;
- map controls: `＋`, `−`, `复位`, fullscreen.

- [ ] **Step 5: Build**

Run: `cd frontend && npm run build`

Expected: PASS.

---

### Task 4: Browser Verification

**Files:**
- No source file changes unless verification reveals layout defects.

- [ ] **Step 1: Start or reuse the frontend dev server**

Run: `cd frontend && npm run dev -- --host 127.0.0.1`

Expected: Vite serves the app.

- [ ] **Step 2: Open `/dashboard`**

Open: `http://localhost:3000/dashboard` or the Vite fallback port.

- [ ] **Step 3: Verify layout**

Check:

- Three-column layout renders.
- “本周研判重点” aligns with left/right third row.
- Lists auto-scroll slowly and pause on hover.
- Map zoom, reset, fullscreen button are visible.
- No major text overlap at 1170×642 and 1280×720.

- [ ] **Step 4: Fix any visual defects**

If screenshot reveals overlap, update CSS and rerun build.

---

## Self-Review

Spec coverage:

- Three-column B1-C v4 layout: Task 3.
- Data source boundaries and empty states: Task 1 and Task 3.
- Auto-scroll lists: Task 2.
- Map zoom and data-source bar: Task 3.
- Build and browser verification: Task 4.

Placeholder scan:

- No `TBD`, `TODO`, or vague “handle later” tasks.

Type consistency:

- All plan snippets use existing exported `Case` and `ChainLink` types from `frontend/src/types/index.ts`.
