"""
全功能激活脚本：对已导入的 2025/2026 案件数据运行所有系统功能。
包含：部署分析、热点分析、串案图谱、团伙识别、巡逻规划、
      案件预处理（取前N条）、圆桌会议（取1个典型案件）

运行前确保后端在 http://localhost:8080 运行：
  uvicorn app.main:app --port 8080

运行：
  python3 run_all_features.py
"""

import json
import time
import sys
import sqlite3
from pathlib import Path
import urllib.request
import urllib.parse
import urllib.error

BASE_URL = "http://localhost:8080"
DB_PATH  = Path(__file__).parent / "aicommander.db"

# ── HTTP 工具 ─────────────────────────────────────────────────

def get(path: str, params: dict | None = None) -> dict | list | None:
    url = BASE_URL + path
    if params:
        qs = urllib.parse.urlencode(params)
        url = url + "?" + qs
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"  [HTTP {e.code}] GET {path}: {e.read().decode()[:200]}")
        return None
    except Exception as e:
        print(f"  [ERR] GET {path}: {e}")
        return None


def post(path: str, data: dict | list, timeout: int = 60) -> dict | list | None:
    url = BASE_URL + path
    body = json.dumps(data).encode()
    req  = urllib.request.Request(url, data=body,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode()[:300]
        print(f"  [HTTP {e.code}] POST {path}: {body_txt}")
        return None
    except Exception as e:
        print(f"  [ERR] POST {path}: {e}")
        return None


def ok(label: str, result) -> bool:
    if result is not None:
        print(f"  ✓ {label}")
        return True
    print(f"  ✗ {label}")
    return False


# ── 获取案件 ID 列表 ─────────────────────────────────────────

def get_case_ids(limit: int = 200) -> list[int]:
    conn = sqlite3.connect(str(DB_PATH))
    cur  = conn.cursor()
    cur.execute(
        "SELECT id FROM cases WHERE case_number LIKE 'AI202%' ORDER BY occurred_time",
    )
    ids = [r[0] for r in cur.fetchall()[:limit]]
    conn.close()
    return ids


def get_cases_with_oil(limit: int = 10) -> list[int]:
    conn = sqlite3.connect(str(DB_PATH))
    cur  = conn.cursor()
    cur.execute(
        "SELECT id FROM cases WHERE case_number LIKE 'AI202%' AND oil_volume > 1 ORDER BY oil_volume DESC LIMIT ?",
        (limit,),
    )
    ids = [r[0] for r in cur.fetchall()]
    conn.close()
    return ids


# ── 各功能测试 ────────────────────────────────────────────────

def test_case_list_and_filter(all_ids: list[int]) -> None:
    print("\n【1】案件列表 & 筛选")

    r = get("/api/cases/", {"limit": 10, "skip": 0})
    ok(f"GET /api/cases/ (limit=10)，返回 {len(r) if r else 0} 条", r)

    r = get("/api/cases/", {"limit": 50, "status": "pending"})
    ok(f"筛选 status=pending，返回 {len(r) if r else 0} 条", r)

    r = get("/api/cases/", {"limit": 50, "case_type": "开井盗油"})
    ok(f"筛选 case_type=开井盗油，返回 {len(r) if r else 0} 条", r)

    r = get("/api/cases/", {"limit": 50, "start_date": "2025-01-01", "end_date": "2025-03-31"})
    ok(f"筛选 2025 Q1，返回 {len(r) if r else 0} 条", r)

    r = get("/api/cases/", {"limit": 50, "has_geo": "true"})
    ok(f"筛选 has_geo=true，返回 {len(r) if r else 0} 条", r)

    if all_ids:
        r = get(f"/api/cases/{all_ids[0]}")
        ok(f"GET /api/cases/{all_ids[0]} 单条", r)

        r = get(f"/api/cases/{all_ids[0]}/nearby", {"radius_km": 15})
        ok(f"周边案件 radius=15km，返回 {len(r) if r else 0} 条", r)


def test_geo_analysis(all_ids: list[int]) -> None:
    print("\n【2】地理分析")

    # 热点
    r = get("/api/cases/geo/hotspots", {"radius_km": 15, "min_cases": 2})
    if r:
        hotspots = r if isinstance(r, list) else r.get("hotspots", r.get("results", [r]))
        print(f"  ✓ 热点识别，发现 {len(hotspots)} 个热点区域")
        for h in hotspots[:3]:
            if isinstance(h, dict):
                print(f"    - {h.get('center_location', h.get('location','?'))} | {h.get('case_count',0)} 案 | 风险={h.get('risk_level','?')}")
    else:
        ok("热点识别", r)

    # 串案分析（取高涉油量案件）
    oil_ids = get_cases_with_oil(20)
    if oil_ids:
        ids_str = ",".join(str(i) for i in oil_ids)
        r = get(f"/api/cases/geo/serial-cases",
                {"case_ids": ids_str, "max_distance_km": 30, "time_window_days": 60})
        if r:
            edges = r.get("edges", []) if isinstance(r, dict) else []
            nodes = r.get("nodes", []) if isinstance(r, dict) else []
            print(f"  ✓ 串案分析：{len(nodes)} 节点，{len(edges)} 关联")
        else:
            ok("串案分析", r)


def test_graphs(all_ids: list[int]) -> None:
    print("\n【3】关系图谱")

    oil_ids = get_cases_with_oil(30)
    if not oil_ids:
        print("  (跳过，无案件)")
        return

    r = post("/api/graphs/serial?radius_km=25", oil_ids[:30])
    if r:
        nodes = r.get("nodes", [])
        edges = r.get("edges", [])
        print(f"  ✓ 关系图谱：{len(nodes)} 节点，{len(edges)} 边")
    else:
        ok("关系图谱 POST /api/graphs/serial", r)


def test_deployment(all_ids: list[int]) -> None:
    print("\n【4】工作部署")

    r = get("/api/deployment/temporal-patterns", {"days": 365})
    ok(f"时间规律分析 /temporal-patterns", r)

    r = get("/api/deployment/target-patterns")
    ok("目标设施分析 /target-patterns", r)

    r = get("/api/deployment/patrol-routes", {"radius_km": 20})
    if r:
        print(f"  ✓ 巡逻路线 /patrol-routes：{len(r)} 条路线建议")
    else:
        ok("巡逻路线", r)

    r = get("/api/deployment/resource-allocation")
    ok("资源分配 /resource-allocation", r)

    r = get("/api/deployment/prevention-measures")
    ok("防控措施 /prevention-measures", r)

    r = get("/api/deployment/report", {"days": 365})
    ok("部署报告 /report", r)


def test_smart_analysis() -> None:
    print("\n【5】智能研判（一键）")

    r = post("/api/deployment/smart-analysis", {
        "time_window_days": 365,
        "min_cases": 2,
        "include_deployment": True,
    })
    if r:
        summary = r.get("summary", {})
        risk    = summary.get("overall_risk_level", "?")
        pa_cnt  = len(r.get("priority_actions", []))
        print(f"  ✓ 智能研判完成 | 风险等级={risk} | 优先行动={pa_cnt} 项")
        mods = r.get("modules", {})
        for m, v in mods.items():
            if isinstance(v, dict):
                print(f"    {m}: {json.dumps(v)[:80]}")
    else:
        ok("智能研判", r)


def test_gangs(all_ids: list[int]) -> None:
    print("\n【6】团伙分析")

    r = post("/api/gangs/identify", {
        "case_ids": all_ids,
        "min_similarity": 0.3,
        "min_cases": 3,
        "time_window_days": 365,
    })
    if r:
        gangs = r if isinstance(r, list) else r.get("gangs", [])
        print(f"  ✓ 识别到 {len(gangs)} 个潜在团伙")
        for g in gangs[:3]:
            print(f"    - {g.get('gang_id','?')} | {g.get('case_count',0)} 案 | 区域={g.get('primary_area','?')}")
    else:
        ok("团伙识别", r)


def test_patrols(all_ids: list[int]) -> None:
    print("\n【7】巡逻规划")

    # 刷新区域风险
    r = post("/api/patrols/areas/refresh-risks", {})
    ok("刷新区域风险评分", r)

    # 读取风险列表
    r = get("/api/patrols/areas/risks")
    if r:
        print(f"  ✓ 区域风险列表：{len(r)} 个区域")
        for a in r[:3]:
            print(f"    - {a.get('area_name','?')} | 风险={a.get('risk_score',0):.2f} | 7日案件={a.get('case_count_7d',0)}")
    else:
        ok("区域风险列表", r)

    # 创建几个典型巡逻任务
    patrol_plans = [
        {"area_name": "龙虎泡作业区",  "patrol_type": "targeted",  "officer_count": 4,
         "officer_names": "测巡逻A,测巡逻B,测巡逻C,测巡逻D",
         "area_coordinates": [{"lat": 46.882, "lng": 124.422}]},
        {"area_name": "敖南作业区",    "patrol_type": "routine",   "officer_count": 3,
         "officer_names": "测巡逻E,测巡逻F,测巡逻G",
         "area_coordinates": [{"lat": 45.726, "lng": 124.706}]},
        {"area_name": "新站作业区",    "patrol_type": "emergency", "officer_count": 5,
         "officer_names": "测巡逻H,测巡逻I,测巡逻J,测巡逻K,测巡逻L",
         "area_coordinates": [{"lat": 45.558, "lng": 124.814}]},
        {"area_name": "敖古拉作业区",  "patrol_type": "targeted",  "officer_count": 3,
         "officer_names": "测巡逻M,测巡逻N,测巡逻O",
         "area_coordinates": [{"lat": 46.720, "lng": 124.376}]},
        {"area_name": "齐家作业区",    "patrol_type": "routine",   "officer_count": 2,
         "officer_names": "测巡逻P,测巡逻Q",
         "area_coordinates": [{"lat": 46.671, "lng": 124.837}]},
    ]

    patrol_ids = []
    for plan in patrol_plans:
        r = post("/api/patrols/", plan)
        if r:
            patrol_ids.append(r["id"])
            print(f"  ✓ 创建巡逻 #{r['id']} | {plan['area_name']} | {plan['patrol_type']}")

    # 标记几个为"执行中"
    for pid in patrol_ids[:2]:
        r = post(f"/api/patrols/{pid}/start", {})
        ok(f"  启动巡逻 #{pid}", r)

    # 完成其中一个
    if patrol_ids:
        r = post(f"/api/patrols/{patrol_ids[0]}/complete", {
            "findings": "发现可疑车辆痕迹，已加强区域监控",
            "issues_found": 1,
            "actions_taken": "拍照取证，上报保卫大队",
            "effectiveness_score": 0.8,
        })
        ok(f"  完成巡逻 #{patrol_ids[0]}", r)


def test_preprocess(all_ids: list[int], max_cases: int = 15) -> list[int]:
    """对前 max_cases 条案件做预处理，返回处理成功的 ID"""
    print(f"\n【8】案件预处理（前 {max_cases} 条）")

    # 优先选涉油量大的案件（数据更丰富）
    conn = sqlite3.connect(str(DB_PATH))
    cur  = conn.cursor()
    cur.execute("""
        SELECT id FROM cases
        WHERE case_number LIKE 'AI202%'
          AND oil_volume IS NOT NULL
          AND oil_volume > 0.5
        ORDER BY oil_volume DESC
        LIMIT ?
    """, (max_cases,))
    target_ids = [r[0] for r in cur.fetchall()]
    conn.close()

    if not target_ids:
        target_ids = all_ids[:max_cases]

    ok_ids = []
    for i, cid in enumerate(target_ids):
        r = post(f"/api/cases/{cid}/preprocess", {}, timeout=120)
        if r and ("result" in r or r.get("status") not in ("error", None)):
            ok_ids.append(cid)
            title = (r.get("result") or {}).get("basic", {}).get("title", "?") if isinstance(r, dict) else "?"
            print(f"  [{i+1}/{len(target_ids)}] ✓ 案件 #{cid} 预处理完成 | {title}")
        else:
            print(f"  [{i+1}/{len(target_ids)}] ✗ 案件 #{cid} 预处理失败 | {str(r)[:80]}")
        time.sleep(0.3)

    print(f"  预处理完成: {len(ok_ids)}/{len(target_ids)}")
    return ok_ids


def test_meetings(preprocessed_ids: list[int]) -> int | None:
    """选 3-5 个高质量案件开圆桌会议"""
    print("\n【9】圆桌会议")

    # 从已预处理的案件中取最多5个
    meeting_ids = preprocessed_ids[:5]
    if len(meeting_ids) < 2:
        print("  (跳过，预处理案件不足 2 个)")
        return None

    # 获取模型 ID
    models_r = get("/api/models/")
    if not models_r:
        print("  (跳过，无法获取模型)")
        return None

    moderator_id   = next((m["id"] for m in models_r if m.get("role") == "moderator"), None)
    analyst_ids    = [m["id"] for m in models_r if m.get("role") == "analyst"]

    if not moderator_id or not analyst_ids:
        print(f"  (跳过，模型配置不足: moderator={moderator_id}, analysts={analyst_ids})")
        return None

    print(f"  使用: moderator=#{moderator_id}, analysts={analyst_ids}")

    r = post("/api/meetings/", {
        "case_ids":           meeting_ids,
        "moderator_model_id": moderator_id,
        "analyst_model_ids":  analyst_ids[:2],
    })

    if r:
        mid = r.get("id")
        print(f"  ✓ 创建会议 #{mid} | status={r.get('status','?')} | cases={meeting_ids}")
        return mid
    else:
        ok("圆桌会议", r)
        return None


def test_conclusions(case_ids: list[int]) -> None:
    print("\n【10】结论生成")

    if not case_ids:
        print("  (跳过，无预处理案件)")
        return

    for cid in case_ids[:3]:
        r = post(f"/api/conclusions/generate?case_id={cid}", {}, timeout=120)
        if r:
            print(f"  ✓ 案件 #{cid} → 结论 #{r.get('id','?')} | 风险={r.get('risk_level','?')} | 置信={r.get('confidence',0):.2f}")
        else:
            print(f"  ✗ 案件 #{cid} 结论生成失败")
        time.sleep(0.3)

    # 结论列表筛选测试
    r = get("/api/conclusions/", {"min_confidence": "0.5"})
    ok(f"结论筛选 min_confidence=0.5，返回 {len(r) if r else 0} 条", r)


def test_reports(meeting_id: int | None) -> None:
    print("\n【11】报告")

    r = get("/api/reports/", {"limit": 10})
    ok(f"报告列表，返回 {len(r) if r else 0} 条", r)

    if meeting_id:
        r = get(f"/api/meetings/{meeting_id}/report")
        ok(f"会议 #{meeting_id} 报告", r)


# ── 主流程 ────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("AiCommander 全功能激活测试")
    print("=" * 60)

    # 0. 连通性检查
    health = get("/health") or get("/api/cases/?limit=1")
    if health is None:
        print("[ERROR] 后端未响应，请先启动：uvicorn app.main:app --port 8080")
        sys.exit(1)
    print(f"后端连通 ✓")

    all_ids = get_case_ids()
    print(f"导入案件数: {len(all_ids)}")

    # 1. 案件列表 & 筛选
    test_case_list_and_filter(all_ids)

    # 2. 地理分析
    test_geo_analysis(all_ids)

    # 3. 关系图谱
    test_graphs(all_ids)

    # 4. 工作部署
    test_deployment(all_ids)

    # 5. 智能研判
    test_smart_analysis()

    # 6. 团伙分析
    test_gangs(all_ids)

    # 7. 巡逻规划
    test_patrols(all_ids)

    # 8. 案件预处理（需要 LLM，前15条）
    preprocessed = test_preprocess(all_ids, max_cases=15)

    # 9. 圆桌会议（需要 LLM）
    meeting_id = test_meetings(preprocessed)

    # 10. 结论生成（需要 LLM）
    test_conclusions(preprocessed)

    # 11. 报告
    test_reports(meeting_id)

    print("\n" + "=" * 60)
    print("全功能激活测试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
