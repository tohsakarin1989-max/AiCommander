"""
批量预处理：由 Claude Code 直接分析案件数据并生成 features JSON，
不依赖外部 LLM API，基于结构化字段进行规则化提取。

运行：
  cd backend && python3 batch_preprocess_features.py
"""

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "aicommander.db"


# ── 工具函数 ───────────────────────────────────────────────────────


def safe_json(text: str | None) -> dict | list | None:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def extract_region(location: str | None) -> str:
    """从地址提取行政区名"""
    if not location:
        return "大庆市"
    for kw in ["杜蒙县", "肇源县", "泰来县", "林甸县", "安达市",
               "红岗区", "让胡路区", "大同区", "萨尔图区", "龙凤区"]:
        if kw in location:
            return kw
    for kw in ["大庆", "齐齐哈尔", "绥化"]:
        if kw in location:
            return kw
    return location[:8]


def place_type_from_facility(facility: str | None) -> str:
    mapping = {
        "油井": "油田作业区",
        "管线": "管线沿线",
        "输油管线": "管线沿线",
        "集输站": "集输站场",
        "储油罐": "储油设施",
        "油罐车": "道路/运输途中",
        "加油站": "加油站",
        "油库": "油库",
        "炼油厂": "炼化厂区",
    }
    if not facility:
        return "未知地点"
    for k, v in mapping.items():
        if k in (facility or ""):
            return v
    return facility


def modus_from_case(case_type: str | None, modus: str | None, desc: str | None) -> list[str]:
    """提取作案手法列表"""
    result = []
    text = " ".join(filter(None, [case_type, modus, desc]))
    patterns = [
        ("开井盗油", "开井/穿孔盗取"),
        ("打孔盗油", "打孔盗取管线原油"),
        ("非法转运", "非法转运原油"),
        ("非法存储", "非法储存油品"),
        ("非法买卖", "非法买卖油品"),
        ("非法加工", "非法炼制加工"),
        ("入库盗窃", "潜入作业区盗窃"),
    ]
    for kw, label in patterns:
        if kw in text:
            result.append(label)
    if not result:
        result.append(modus or case_type or "盗取油品")
    return list(dict.fromkeys(result))  # 去重


def extract_tools(desc: str | None) -> list[str]:
    tools = []
    if not desc:
        return tools
    if re.search(r"罐车|油罐车|槽车|奥驰|农用", desc):
        tools.append("运输车辆")
    if re.search(r"软管|水泵|油泵|泵|抽油机", desc):
        tools.append("抽油泵管")
    if re.search(r"铁桶|油桶|容器", desc):
        tools.append("储油容器")
    if re.search(r"挖掘机|铲车", desc):
        tools.append("工程机械")
    if not tools:
        tools.append("简单工具")
    return tools


def time_pattern(hour: int | None) -> list[str]:
    if hour is None:
        return ["时间不明"]
    if 0 <= hour < 6:
        return ["深夜（0-6时）"]
    if 6 <= hour < 12:
        return ["上午（6-12时）"]
    if 12 <= hour < 18:
        return ["下午（12-18时）"]
    return ["傍晚/夜间（18-24时）"]


def risk_level(oil_value: int | None, security: str | None, case_type: str | None) -> str:
    if security in ("特重大", "重大"):
        return "高风险"
    if oil_value and oil_value >= 50000:
        return "高风险"
    if oil_value and oil_value >= 10000:
        return "中风险"
    if case_type and "打孔" in case_type:
        return "高风险"
    return "低风险"


def risk_factors(case: dict) -> list[str]:
    factors = []
    if (case.get("oil_value") or 0) >= 50000:
        factors.append("涉案金额较大（≥5万元）")
    if case.get("case_type") and "打孔" in case["case_type"]:
        factors.append("破坏管线安全设施")
    if case.get("modus_operandi") and "团伙" in (case.get("description") or ""):
        factors.append("疑似团伙作案")
    if not factors:
        factors.append("常规涉油盗窃风险")
    return factors


def economic_impact(oil_value: int | None) -> str:
    if not oil_value:
        return "较小"
    if oil_value >= 100000:
        return "特别重大"
    if oil_value >= 50000:
        return "重大"
    if oil_value >= 10000:
        return "一般"
    return "较小"


def generate_tags(case: dict) -> list[str]:
    tags = []
    ct = case.get("case_type") or ""
    ft = case.get("facility_type") or ""
    loc = case.get("location") or ""

    if "盗油" in ct or "开井" in ct:
        tags.append("盗油")
    if "转运" in ct:
        tags.append("非法转运")
    if "加工" in ct or "炼制" in ct:
        tags.append("非法炼制")
    if "管线" in ft:
        tags.append("管线安全")
    if "油罐车" in ft or "罐车" in (case.get("description") or ""):
        tags.append("油罐车")
    for area in ["杜蒙县", "肇源县", "让胡路区", "大同区", "红岗区"]:
        if area in loc:
            tags.append(area)
            break
    if case.get("oil_volume") and float(case["oil_volume"]) >= 10:
        tags.append("大宗盗窃")
    return list(dict.fromkeys(tags)) or ["涉油案件"]


def extract_known_vehicles(vehicle_info_raw: str | None, desc: str | None) -> list[dict]:
    """从 vehicle_info JSON 和描述中提取已知车辆"""
    vehicles = []

    # 从结构化字段
    vi = safe_json(vehicle_info_raw)
    if isinstance(vi, dict):
        items = vi.get("items", [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("plate"):
                    vehicles.append({
                        "plate": item["plate"],
                        "type": item.get("type", "未知车型"),
                        "suspected_fake_plate": False,
                    })

    # 从描述中用正则补充
    if desc:
        plates = re.findall(
            r"[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤川青藏琼宁夏][A-Z][0-9A-Z]{5}",
            desc,
        )
        existing = {v["plate"] for v in vehicles}
        for p in plates:
            if p not in existing:
                vehicles.append({"plate": p, "type": "未知车型", "suspected_fake_plate": False})
                existing.add(p)

    return vehicles


def extract_known_roles(suspect_roles_raw: str | None, desc: str | None) -> list[str]:
    roles = []
    sr = safe_json(suspect_roles_raw)
    if isinstance(sr, dict):
        for k, v in sr.items():
            if v:
                roles.append(str(v))
    elif isinstance(sr, list):
        roles.extend([str(r) for r in sr if r])

    if not roles and desc:
        for kw in ["司机", "驾驶员", "嫌疑人", "犯罪嫌疑人", "盗油者", "主犯", "从犯"]:
            if kw in desc:
                roles.append(kw)
    return list(dict.fromkeys(roles)) or ["嫌疑人（待确认）"]


def build_features(row: tuple) -> dict:
    (cid, case_number, case_type, location, description, occurred_time,
     oil_type, oil_volume, oil_value, facility_type, facility_owner,
     modus_operandi, security_level, upstream_source, downstream_destination,
     suspect_roles_raw, vehicle_info_raw, lat, lng) = row

    # 解析时间
    hour = None
    try:
        dt = datetime.fromisoformat(occurred_time) if occurred_time else None
        hour = dt.hour if dt else None
    except Exception:
        dt = None

    # 生成标题
    loc_short = (location or "")[:10]
    ct = case_type or "涉油"
    title = f"{loc_short}{ct}案"[:30]

    # 生成摘要
    summary = (description or "").strip()
    if len(summary) > 400:
        summary = summary[:380] + "……"

    # 作案手法列表
    modus_list = modus_from_case(case_type, modus_operandi, description)

    # 工具
    tools = extract_tools(description)

    # 下游去向
    dd = safe_json(downstream_destination)
    if isinstance(dd, list):
        downstream_list = [str(x) for x in dd if x]
    elif isinstance(dd, str):
        downstream_list = [dd] if dd else []
    else:
        downstream_list = []

    # 构造 features
    features = {
        "basic": {
            "title": title,
            "summary": summary,
            "case_type": case_type or "涉油",
            "time": occurred_time,
            "location": location or "未知",
        },
        "geo": {
            "latitude": lat,
            "longitude": lng,
            "region": extract_region(location),
            "place_type": place_type_from_facility(facility_type),
        },
        "modus": {
            "target_object": facility_type or "油田设施",
            "modus_operandi": modus_list,
            "tools": tools,
            "time_pattern": time_pattern(hour),
            "weather_pattern": [],
        },
        "actors": {
            "facts": {
                "known_roles": extract_known_roles(suspect_roles_raw, description),
                "known_vehicles": extract_known_vehicles(vehicle_info_raw, description),
            },
            "clues": {
                "possible_roles": [],
                "notes": None,
            },
            "hypotheses": {
                "suspected_structure": None,
            },
        },
        "oil": {
            "facts": {
                "oil_type": oil_type or "原油",
                "volume": float(oil_volume) if oil_volume else 0,
                "value": int(oil_value) if oil_value else 0,
                "facility_type": facility_type or "未知",
                "facility_owner": facility_owner or None,
            },
            "clues": {
                "scene_observations": [],
            },
            "hypotheses": {
                "possible_risk": None,
            },
        },
        "flow": {
            "upstream_source": upstream_source or None,
            "downstream_destination": downstream_list,
            "economic_impact": economic_impact(int(oil_value) if oil_value else 0),
        },
        "risk": {
            "level": risk_level(
                int(oil_value) if oil_value else 0,
                security_level,
                case_type,
            ),
            "factors": risk_factors({
                "oil_value": int(oil_value) if oil_value else 0,
                "case_type": case_type,
                "modus_operandi": modus_operandi,
                "description": description,
            }),
        },
        "tags": generate_tags({
            "case_type": case_type,
            "facility_type": facility_type,
            "location": location,
            "oil_volume": oil_volume,
            "description": description,
        }),
        "confidence": 0.75,  # 规则化提取置信度
    }
    return features


def run() -> None:
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    cur.execute("""
        SELECT id, case_number, case_type, location, description, occurred_time,
               oil_type, oil_volume, oil_value, facility_type, facility_owner,
               modus_operandi, security_level, upstream_source, downstream_destination,
               suspect_roles, vehicle_info, latitude, longitude
        FROM cases
        WHERE case_number LIKE 'AI202%'
          AND (features IS NULL OR features = '{}' OR features = '')
        ORDER BY id
    """)
    rows = cur.fetchall()
    print(f"待处理: {len(rows)} 条案件")

    ok, err = 0, 0
    for row in rows:
        cid = row[0]
        try:
            feat = build_features(row)
            cur.execute(
                "UPDATE cases SET features = ? WHERE id = ?",
                (json.dumps(feat, ensure_ascii=False), cid),
            )
            ok += 1
            if ok % 20 == 0:
                conn.commit()
                print(f"  已处理 {ok}/{len(rows)}")
        except Exception as e:
            print(f"  [ERROR] #{cid}: {e}")
            err += 1

    conn.commit()
    conn.close()
    print(f"\n完成: 成功 {ok} 条，失败 {err} 条")


if __name__ == "__main__":
    run()
