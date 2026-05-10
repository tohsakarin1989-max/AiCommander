"""
脱敏导入脚本：从 321.xlsx 提取 2025、2026 案件数据，
对人名、身份证、电话、车牌等敏感信息进行脱敏后写入 SQLite。

运行方式:
  cd backend
  AICOMMANDER_CASE_IMPORT_XLSX=/path/to/案件明细.xlsx python import_cases_anonymized.py
"""

import json
import os
import random
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import openpyxl

# ── 路径配置 ───────────────────────────────────────────────────
EXCEL_PATH = Path(os.environ.get("AICOMMANDER_CASE_IMPORT_XLSX", "321.xlsx")).expanduser()
DB_PATH    = Path(__file__).parent / "aicommander.db"

# ── 脱敏名称池 ────────────────────────────────────────────────
FAKE_SURNAMES  = ["测", "示", "样", "例", "演"]
FAKE_GIVEN     = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]

# 省份代码保留，其余字符重新生成
PLATE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"
PLATE_DIGITS  = "0123456789"

# 目标 sheet（注意末尾空格）
TARGET_SHEETS = ["2025年案件明细 ", "2026年案件明细"]

# 位置坐标映射（县/区级别，加随机扰动避免点重叠）
LOCATION_COORDS: dict[str, tuple[float, float]] = {
    "肇源县": (45.57, 124.83),
    "杜蒙县": (46.87, 124.44),
    "杜尔伯特": (46.87, 124.44),
    "大同区": (46.06, 125.05),
    "红岗区": (46.60, 124.84),
    "泰来县": (46.39, 123.41),
    "让胡路区": (46.63, 124.87),
    "林甸": (47.18, 124.88),
    "大庆": (46.60, 124.86),
}

# 案件类型映射
CASE_TYPE_MAP = {
    "开井": "开井盗油",
    "收化炼": "收购炼油",
    "其他": "其他",
    "窃电": "盗窃电力",
    "非法转运油气": "非法转运",
    "内部联动": "内外勾联",
    "警企联动": "警企联动",
    "": "其他",
}

# ── 脱敏工具函数 ──────────────────────────────────────────────

_name_counter = 0
_name_cache: dict[str, str] = {}

def fake_person_name(real_name: str) -> str:
    """将真实人名替换为测试人名（同一真名每次得到同一假名）"""
    global _name_counter
    if real_name not in _name_cache:
        idx = _name_counter % (len(FAKE_SURNAMES) * len(FAKE_GIVEN))
        s = FAKE_SURNAMES[idx // len(FAKE_GIVEN)]
        g = FAKE_GIVEN[idx % len(FAKE_GIVEN)]
        _name_cache[real_name] = f"{s}{g}"
        _name_counter += 1
    return _name_cache[real_name]


def anonymize_id(id_str: str) -> str:
    """将真实 18 位身份证替换为格式一致的测试 ID"""
    if len(id_str) == 18:
        return f"999999{id_str[6:14]}0001"
    return "999999000000000001"


def anonymize_phone(phone: str) -> str:
    """将真实手机号替换为测试号码"""
    return f"130{'0' * 8}"


def anonymize_plate(plate: str) -> str:
    """保留省份代码，其余字符随机替换，保持格式"""
    if not plate:
        return plate
    province = plate[0]
    city_letter = plate[1] if len(plate) > 1 and plate[1].isalpha() else random.choice(PLATE_LETTERS)
    suffix = "".join(
        random.choice(PLATE_LETTERS if i < 3 else PLATE_DIGITS + PLATE_LETTERS)
        for i in range(5)
    )
    return f"{province}{city_letter}{suffix}"


# 正则：身份证（排除我们自己生成的 999999 假 ID）
RE_ID   = re.compile(r"(?<!9999)(?<![9]{6})\d{17}[\dXx]")
RE_ID_ALL = re.compile(r"\d{17}[\dXx]")  # 用于全量替换
# 正则：手机号
RE_TEL  = re.compile(r"1[3-9]\d{9}")
# 正则：车牌
RE_PLATE = re.compile(
    r"[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤川青藏琼宁夏][A-Z][0-9A-Z]{5}"
)
# 正则：人名（"姓名：X" / "姓名:X" 格式）
RE_NAME_EXPLICIT = re.compile(r"姓名[：:]\s*([^\s，,。；;、\n（(]{2,5})")
# 正则：直接列举人名（"X，女/男，年龄" 格式）
RE_NAME_GENDER = re.compile(r"([^\s，,。、\n（(]{2,4})，[男女]，年龄")
# 正则：出警人后的名单
RE_JINGUAN = re.compile(r"出警人[：:人]?\s*[:：]?\s*([^。\n]+)")
# 正则：家庭住址（替换为泛化描述）
RE_ADDRESS = re.compile(
    r"家庭?住址[：:]\s*([^\n。；]{5,60})"
)
# 正则：现住址
RE_ADDR2 = re.compile(
    r"(?:现住址|住址)[：:]\s*([^\n。；]{5,60})"
)
# 正则：家住址
RE_ADDR3 = re.compile(
    r"家住址[：:]\s*([^\n。；]{5,60})"
)


def anonymize_note(text: str) -> str:
    """对备注全文进行脱敏处理，返回脱敏后文本"""
    if not text:
        return text

    result = text

    # 1. 身份证（全部替换，包括已经是 999999 开头的，保持幂等）
    for m in RE_ID_ALL.finditer(result):
        result = result.replace(m.group(), anonymize_id(m.group()), 1)

    # 2. 手机
    for m in RE_TEL.finditer(result):
        result = result.replace(m.group(), anonymize_phone(m.group()), 1)

    # 3. 车牌
    found_plates: list[str] = RE_PLATE.findall(text)
    for real in found_plates:
        result = result.replace(real, anonymize_plate(real))

    # 4. 显式 "姓名：X" 人名
    for m in RE_NAME_EXPLICIT.finditer(text):
        real_name = m.group(1).strip()
        result = result.replace(real_name, fake_person_name(real_name))

    # 5. "X，女/男，年龄" 格式人名
    for m in RE_NAME_GENDER.finditer(text):
        real_name = m.group(1).strip()
        if real_name and 2 <= len(real_name) <= 4:
            result = result.replace(real_name, fake_person_name(real_name))

    # 6. 出警人名单（逗号分隔）
    for m in RE_JINGUAN.finditer(text):
        names_raw = m.group(1)
        names = re.split(r"[，,、\s]+", names_raw)
        for n in names:
            n = n.strip()
            if 2 <= len(n) <= 4 and n and not any(c.isdigit() for c in n):
                result = result.replace(n, fake_person_name(n))

    # 7. 家庭住址 / 现住址 / 家住址 → 泛化到省市级别
    for pat in (RE_ADDRESS, RE_ADDR2, RE_ADDR3):
        for m in pat.finditer(text):
            addr = m.group(1).strip()
            # 提取省/市/县 级别前缀
            mo = re.match(r"([^\s]{2,8}(?:省|市|县|区|旗))", addr)
            if mo:
                prefix = mo.group(1)
                result = result.replace(addr, f"{prefix}某地（已脱敏）")
            else:
                result = result.replace(addr, "（住址已脱敏）")

    return result


def extract_plates_from_note(text: str) -> list[dict[str, Any]]:
    """从备注中提取车辆信息（已脱敏车牌）"""
    if not text:
        return []
    vehicles = []
    # 找到所有车牌
    for plate in RE_PLATE.findall(text):
        vehicles.append({"plate_number": anonymize_plate(plate), "original_format": "省市式"})
    # 检测无牌
    if "无牌" in text or "无车牌" in text:
        vehicles.append({"plate_number": "无牌(测试)", "note": "现场无牌照"})
    return vehicles or [{}]


def extract_suspects_from_note(text: str) -> list[dict[str, Any]]:
    """从备注中提取嫌疑人信息（已脱敏）"""
    if not text:
        return []
    suspects = []
    for m in RE_NAME_EXPLICIT.finditer(text):
        real_name = m.group(1).strip()
        suspects.append({"name": fake_person_name(real_name), "role": "犯罪嫌疑人"})
    return suspects


def get_coords(location_text: str | None, district: str | None) -> tuple[float | None, float | None]:
    """根据地界文本返回近似坐标（±0.03度随机扰动）"""
    search_text = (location_text or "") + (district or "")
    base: tuple[float, float] | None = None
    for key, coords in LOCATION_COORDS.items():
        if key in search_text:
            base = coords
            break
    if base is None:
        base = LOCATION_COORDS["大庆"]
    lat = base[0] + random.uniform(-0.03, 0.03)
    lng = base[1] + random.uniform(-0.03, 0.03)
    return round(lat, 5), round(lng, 5)


def detect_facility(text: str) -> str:
    """从备注中推断设施类型"""
    if not text:
        return "油井"
    if "管线" in text:
        return "管线"
    if "油库" in text:
        return "油库"
    if "加油站" in text:
        return "加油站"
    if "罐车" in text or "背罐" in text or "油罐" in text:
        return "油罐车"
    return "油井"


def detect_modus(text: str, case_type: str) -> str:
    """从备注和案件类型推断作案手法"""
    if not text:
        return case_type or "其他"
    if "开井" in text or "开井放油" in text:
        return "开井盗油"
    if "打孔" in text:
        return "管线打孔"
    if "套牌" in text:
        return "套牌车运输"
    if "收化炼" in case_type or "炼油" in text:
        return "收购炼化"
    if "窃电" in text or "盗电" in text:
        return "盗窃油田电力"
    if case_type:
        return CASE_TYPE_MAP.get(case_type, case_type)
    return "盗运原油"


def parse_date_from_note(text: str, year: int) -> datetime | None:
    """从备注首行提取日期时间"""
    if not text:
        return None
    # 匹配 "2025年1月2日，21：20" 或 "2025年1月2日19:00"
    m = re.search(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日[，,]?\s*(\d{1,2})[：:：](\d{2})", text)
    if m:
        y, mo, d, h, mi = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
        try:
            return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)
        except ValueError:
            pass
    m = re.search(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime(y, mo, d, 12, 0, tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


# ── 主逻辑 ────────────────────────────────────────────────────

def extract_rows(wb: openpyxl.Workbook) -> list[dict[str, Any]]:
    """从目标 sheet 提取有效行，返回结构化列表"""
    all_rows: list[dict[str, Any]] = []

    for sh_target in TARGET_SHEETS:
        # 匹配（有些 sheet 名末尾有空格）
        matched = next((n for n in wb.sheetnames if n.strip() == sh_target.strip()), None)
        if not matched:
            print(f"[WARN] 未找到 sheet: {sh_target}")
            continue

        ws = wb[matched]
        rows = list(ws.rows)
        year_str = sh_target.strip()[:4]
        year = int(year_str)
        print(f"[INFO] 处理 {matched}，总行数={len(rows)}")

        for row_idx, row in enumerate(rows[3:], start=4):
            vals = [c.value for c in row]

            # 备注列（第29列，0-indexed=28）
            note_raw = vals[28] if len(vals) > 28 else None
            if not note_raw or not isinstance(note_raw, str) or note_raw.startswith("=") or len(note_raw.strip()) < 10:
                continue

            # 其他列（部分是公式，跳过公式值）
            def safe(idx: int) -> Any:
                v = vals[idx] if len(vals) > idx else None
                if isinstance(v, str) and v.startswith("="):
                    return None
                return v

            month_val    = safe(3)
            day_val      = safe(4)
            area         = safe(5)   # 涉案所属作业区
            district     = safe(6)   # 所属地界
            oil_volume   = safe(31)  # 回收原油
            sys_type     = safe(32)  # 系统案件类型
            reported     = safe(33)  # 是否报案
            filed        = safe(34)  # 是否立案
            case_type_col = safe(35) # 案件类型

            # 解析日期
            occurred = parse_date_from_note(note_raw, year)
            if occurred is None:
                # fallback: 用月/日列
                try:
                    mo = int(month_val) if month_val is not None else 1
                    d  = int(day_val)   if day_val  is not None else 1
                    occurred = datetime(year, mo, d, 12, 0, tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    occurred = datetime(year, 1, 1, 12, 0, tzinfo=timezone.utc)

            # 解析涉油量
            try:
                oil_vol_float = float(oil_volume) if oil_volume is not None else None
            except (TypeError, ValueError):
                # 有些是表达式 "5.2+12.4"
                if isinstance(oil_volume, str) and "+" in oil_volume:
                    try:
                        oil_vol_float = sum(float(x) for x in oil_volume.split("+"))
                    except ValueError:
                        oil_vol_float = None
                else:
                    oil_vol_float = None

            # 案件状态
            if str(filed).strip() in ("是", "1", "True"):
                status = "resolved"
            elif str(reported).strip() in ("是", "1", "True"):
                status = "processing"
            else:
                status = "pending"

            # 案件类型
            case_type_raw = str(sys_type or case_type_col or "").strip()
            mapped_type = CASE_TYPE_MAP.get(case_type_raw, case_type_raw or "其他")

            # 位置
            location_str = str(area or "").strip() or str(district or "").strip() or "未知地点"

            # 坐标
            lat, lng = get_coords(str(area or ""), str(district or ""))

            # 脱敏
            note_anon = anonymize_note(note_raw)
            vehicles  = extract_plates_from_note(note_raw)
            suspects  = extract_suspects_from_note(note_raw)

            facility = detect_facility(note_raw)
            modus    = detect_modus(note_raw, case_type_raw)

            all_rows.append({
                "year":        year,
                "occurred":    occurred,
                "location":    location_str,
                "district":    str(district or ""),
                "lat":         lat,
                "lng":         lng,
                "case_type":   mapped_type,
                "description": note_anon,
                "oil_vol":     oil_vol_float,
                "facility":    facility,
                "modus":       modus,
                "vehicles":    vehicles,
                "suspects":    suspects,
                "status":      status,
            })

    return all_rows


def insert_to_db(rows: list[dict[str, Any]]) -> int:
    """将脱敏行写入 SQLite，返回插入数量"""
    conn = sqlite3.connect(str(DB_PATH))
    cur  = conn.cursor()

    # 获取当前最大 ID
    cur.execute("SELECT COALESCE(MAX(id), 0) FROM cases")
    max_id = cur.fetchone()[0]

    # 获取已有 case_number 避免重复
    cur.execute("SELECT case_number FROM cases")
    existing = {r[0] for r in cur.fetchall()}

    seq_by_year: dict[int, int] = {2025: 1, 2026: 1}
    inserted = 0

    for row in rows:
        year = row["year"]
        seq  = seq_by_year.get(year, 1)

        while True:
            cn = f"AI{year}-{seq:05d}"
            if cn not in existing:
                break
            seq += 1

        seq_by_year[year] = seq + 1
        existing.add(cn)
        max_id += 1

        now = datetime.now(timezone.utc).isoformat()

        cur.execute(
            """
            INSERT INTO cases (
                id, case_number, occurred_time, location,
                latitude, longitude,
                case_type, description,
                involved_persons, involved_items,
                loss_amount,
                oil_type, oil_volume, oil_value,
                facility_type, modus_operandi,
                vehicle_info, suspect_roles,
                upstream_source, downstream_destination,
                status, features,
                created_at, updated_at
            ) VALUES (
                ?, ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?,
                ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?
            )
            """,
            (
                max_id,
                cn,
                row["occurred"].isoformat(),
                row["location"],
                row["lat"],
                row["lng"],
                row["case_type"],
                row["description"],
                json.dumps(row["suspects"], ensure_ascii=False),
                json.dumps([], ensure_ascii=False),
                None,
                "原油",
                row["oil_vol"],
                int(row["oil_vol"] * 4000) if row["oil_vol"] else None,
                row["facility"],
                row["modus"],
                json.dumps(row["vehicles"], ensure_ascii=False),
                json.dumps([s["role"] for s in row["suspects"]], ensure_ascii=False),
                None,
                None,
                row["status"],
                json.dumps({}, ensure_ascii=False),
                now,
                now,
            ),
        )
        inserted += 1

    conn.commit()
    conn.close()
    return inserted


def main() -> None:
    print(f"读取 Excel: {EXCEL_PATH}")
    wb = openpyxl.load_workbook(str(EXCEL_PATH))

    rows = extract_rows(wb)
    print(f"提取有效行: {len(rows)}")

    # 统计
    y_count = {2025: 0, 2026: 0}
    for r in rows:
        y_count[r["year"]] = y_count.get(r["year"], 0) + 1
    for y, n in y_count.items():
        print(f"  {y}年: {n} 条")

    n = insert_to_db(rows)
    print(f"\n✓ 成功写入 {n} 条案件到 {DB_PATH}")


if __name__ == "__main__":
    main()
