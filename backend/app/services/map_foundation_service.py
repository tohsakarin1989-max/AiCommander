"""生产地图来源治理、模板化导入、隔离与版本追溯。"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import uuid
import zipfile
from datetime import date, datetime, timezone
from typing import Any, Iterable

import openpyxl
from sqlalchemy.orm import Session

from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import (
    JurisdictionAssetVersion,
    MapFeatureClaim,
    MapImportTemplate,
    MapIngestRun,
    MapSource,
    OperationalArea,
)
from app.services.facility_identity_service import FacilityIdentityService


ALLOWED_TABLE_EXTENSIONS = (".csv", ".xlsx", ".xlsm", ".xltx", ".xltm")
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_EXCEL_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_EXCEL_MEMBERS = 500
MAX_TABLE_ROWS = 100_000
MAX_TABLE_COLUMNS = 200
MAX_CELL_TEXT_LENGTH = 10_000
SUPPORTED_COORDINATE_SYSTEMS = {
    "wgs84",
    "cgcs2000_geographic",
    "gcj02",
    "bd09",
    "cgcs2000_gauss_kruger",
    "local_control_points",
}
SOURCE_TRUST_RANKS = {
    "ledger": 100,
    "manual": 90,
    "internal_gis": 80,
    "public_map": 10,
}


class MapFoundationService:
    """地图底座治理服务；任何异常记录都不会进入标准地图层。"""

    @staticmethod
    def ensure_default_area(db: Session) -> OperationalArea:
        area = db.query(OperationalArea).filter(OperationalArea.is_default.is_(True)).first()
        if area:
            return area
        area = db.query(OperationalArea).filter(OperationalArea.code == "default-factory").first()
        if area:
            area.is_default = True
        else:
            area = OperationalArea(
                code="default-factory",
                name="默认厂区",
                is_default=True,
                status="active",
            )
            db.add(area)
        db.flush()
        return area

    @staticmethod
    def create_area(db: Session, data: dict[str, Any]) -> OperationalArea:
        code = str(data["code"]).strip().lower()
        if db.query(OperationalArea).filter(OperationalArea.code == code).first():
            raise ValueError("operational_area_code_exists")
        boundary = data.get("boundary")
        MapFoundationService._validate_area_boundary(boundary)
        make_default = bool(data.get("is_default")) or not db.query(OperationalArea.id).first()
        if make_default:
            db.query(OperationalArea).update(
                {OperationalArea.is_default: False},
                synchronize_session=False,
            )
        area = OperationalArea(
            code=code,
            name=str(data["name"]).strip(),
            boundary=boundary,
            is_default=make_default,
            status=data.get("status") or "active",
        )
        db.add(area)
        db.commit()
        db.refresh(area)
        return area

    @staticmethod
    def update_area(db: Session, area_id: int, data: dict[str, Any]) -> OperationalArea:
        area = db.query(OperationalArea).filter(OperationalArea.id == area_id).first()
        if not area:
            raise ValueError("operational_area_not_found")
        if "boundary" in data:
            MapFoundationService._validate_area_boundary(data["boundary"])
            area.boundary = data["boundary"]
        if "name" in data:
            area.name = str(data["name"]).strip()
        if "status" in data:
            if area.is_default and data["status"] != "active":
                raise ValueError("default_area_must_remain_active")
            area.status = data["status"]
        if data.get("is_default") is True:
            db.query(OperationalArea).filter(OperationalArea.id != area.id).update(
                {OperationalArea.is_default: False},
                synchronize_session=False,
            )
            area.is_default = True
            area.status = "active"
        elif data.get("is_default") is False and area.is_default:
            raise ValueError("default_area_cannot_be_unset")
        db.commit()
        db.refresh(area)
        return area

    @staticmethod
    def _validate_area_boundary(boundary: Any) -> None:
        if boundary is None:
            return
        if isinstance(boundary, list) and len(boundary) == 4:
            west, south, east, north = boundary
            if -180 <= west < east <= 180 and -90 <= south < north <= 90:
                return
            raise ValueError("invalid_operational_area_boundary")
        geometry = boundary.get("geometry") if isinstance(boundary, dict) and boundary.get("type") == "Feature" else boundary
        if isinstance(geometry, dict) and geometry.get("type") in {"Polygon", "MultiPolygon"}:
            if geometry.get("coordinates"):
                return
        raise ValueError("invalid_operational_area_boundary")

    @staticmethod
    def create_source(db: Session, data: dict[str, Any]) -> MapSource:
        source_key = str(data["source_key"]).strip()
        if db.query(MapSource).filter(MapSource.source_key == source_key).first():
            raise ValueError("source_key_exists")
        area_id = data.get("operational_area_id")
        if area_id is None:
            area = MapFoundationService.ensure_default_area(db)
        else:
            area = db.query(OperationalArea).filter(OperationalArea.id == area_id).first()
            if not area or area.status != "active":
                raise ValueError("operational_area_not_found")
        source_type = data["source_type"]
        requested_rank = data.get("trust_rank")
        fixed_rank = SOURCE_TRUST_RANKS[source_type]
        source = MapSource(
            source_key=source_key,
            name=str(data["name"]).strip(),
            source_type=source_type,
            trust_rank=min(int(requested_rank), fixed_rank) if requested_rank is not None else fixed_rank,
            operational_area_id=area.id,
            status="active",
            description=data.get("description"),
            configuration=data.get("configuration"),
        )
        db.add(source)
        db.commit()
        db.refresh(source)
        return source

    @staticmethod
    def create_template(db: Session, data: dict[str, Any]) -> MapImportTemplate:
        from app.services.map_import_contract import validate_contract
        validate_contract(data)
        source = db.query(MapSource).filter(MapSource.id == data["source_id"]).first()
        if not source or source.status != "active":
            raise ValueError("source_not_found")
        coordinate_system = str(data["coordinate_system"]).lower()
        if coordinate_system not in SUPPORTED_COORDINATE_SYSTEMS:
            raise ValueError("unsupported_coordinate_system")
        expected_unit = "meter" if coordinate_system in {"cgcs2000_gauss_kruger", "local_control_points"} else "degree"
        if data.get("coordinate_unit", "degree") != expected_unit:
            raise ValueError("coordinate_unit_mismatch|坐标单位必须与已明确的坐标系一致；投影/本地坐标使用 meter，经纬度使用 degree")
        MapFoundationService._validate_transformation(coordinate_system, data.get("transformation"))
        latest = (
            db.query(MapImportTemplate)
            .populate_existing()
            .filter(
                MapImportTemplate.source_id == source.id,
                MapImportTemplate.name == str(data["name"]).strip(),
            )
            .order_by(MapImportTemplate.version.desc())
            .first()
        )
        template = MapImportTemplate(
            source_id=source.id,
            name=str(data["name"]).strip(),
            sheet_name=data.get("sheet_name"),
            header_row=data.get("header_row", 1),
            field_mapping=data["field_mapping"],
            coordinate_system=coordinate_system,
            axis_order=data.get("axis_order", "lon_lat"),
            coordinate_unit=data.get("coordinate_unit", "degree"),
            transformation=data.get("transformation"),
            expected_structure=data.get("expected_structure"),
            field_units=data.get("field_units"),
            version=(latest.version + 1) if latest else 1,
            is_active=True,
        )
        db.add(template)
        db.commit()
        db.refresh(template)
        return template

    @staticmethod
    def preview(
        db: Session,
        *,
        source_id: int,
        filename: str,
        content: bytes,
        template_id: int | None,
        ledger_declaration: dict | str | None = None,
    ) -> dict[str, Any]:
        from app.services.map_ingest_plan import make_plan, public_plan
        source = MapFoundationService._get_source(db, source_id)
        template = None
        if template_id is not None:
            template = MapFoundationService._get_template(db, source.id, template_id)
        metadata = {}
        rows = MapFoundationService.parse_table(filename, content, template=template, metadata=metadata)
        with db.no_autoflush:
            plan = make_plan(db, source, template, rows, metadata, file_hash=hashlib.sha256(content).hexdigest())
            from app.services.map_ledger_completeness import declare_plan
            plan = declare_plan(db, source, template, plan, ledger_declaration)
        if template is None:
            plan["sample"] = [raw for _, raw in rows[:10]]
        return public_plan(plan)

    @staticmethod
    def ingest(
        db: Session,
        *,
        source_id: int,
        template_id: int,
        filename: str,
        content: bytes,
        source_revision: str | None,
        created_by: int | None,
        plan_token: str | None = None,
        ledger_declaration: dict | str | None = None,
    ) -> tuple[MapIngestRun, bool]:
        from app.services.map_ingest_execution import ingest_file
        return ingest_file(db, source_id=source_id, template_id=template_id, filename=filename,
                           content=content, source_revision=source_revision, created_by=created_by,
                           plan_token=plan_token, ledger_declaration=ledger_declaration)

    @staticmethod
    def parse_table(
        filename: str,
        content: bytes,
        *,
        template: MapImportTemplate | None,
        metadata: dict | None = None,
    ) -> list[tuple[int, dict[str, Any]]]:
        lowered = (filename or "").lower()
        if not any(lowered.endswith(ext) for ext in ALLOWED_TABLE_EXTENSIONS):
            raise ValueError("unsupported_file_type|仅支持 CSV 或 Excel (.xlsx) 文件")
        if not content:
            raise ValueError("empty_file|文件内容为空")
        if len(content) > MAX_UPLOAD_BYTES:
            raise ValueError("file_too_large|文件过大，限制为 10MB")
        if lowered.endswith(".csv"):
            text = content.decode("utf-8-sig")
            values = csv.reader(io.StringIO(text))
            header_row = template.header_row if template else 1
            for _ in range(header_row - 1):
                next(values, None)
            headers = [str(value).strip() for value in next(values, [])]
            if not headers or not any(headers):
                raise ValueError("missing_header|文件缺少表头")
            if len(headers) > MAX_TABLE_COLUMNS:
                raise ValueError("table_too_wide|表格列数超过限制")
            MapFoundationService._check_headers(headers)
            if metadata is not None:
                metadata.update(headers=headers, sheet_name=None, header_row=header_row)
            parsed = []
            for index, cells in enumerate(values, start=header_row + 1):
                if index > MAX_TABLE_ROWS + header_row:
                    raise ValueError("table_too_long|表格行数超过限制")
                if len(cells) > len(headers):
                    raise ValueError("row_too_wide|数据列多于表头，不能静默丢弃")
                if any(len(value) > MAX_CELL_TEXT_LENGTH for value in cells):
                    raise ValueError("cell_too_long|单元格文本超过限制")
                row = {key: cells[pos] if pos < len(cells) else None for pos, key in enumerate(headers) if key}
                if any(value not in (None, "") for value in row.values()):
                    parsed.append((index, MapFoundationService._json_safe_dict(row)))
            return parsed

        MapFoundationService.validate_excel_archive(content)
        workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        try:
            sheet_name = template.sheet_name if template else None
            if sheet_name:
                if sheet_name not in workbook.sheetnames:
                    raise ValueError("sheet_not_found|模板指定的工作表不存在")
                sheet = workbook[sheet_name]
            else:
                sheet = workbook.active
            header_row = template.header_row if template else 1
            values = sheet.iter_rows(values_only=True)
            headers: list[str] | None = None
            parsed: list[tuple[int, dict[str, Any]]] = []
            for row_number, row in enumerate(values, start=1):
                if row_number > MAX_TABLE_ROWS + header_row:
                    raise ValueError("table_too_long|表格行数超过限制")
                if len(row) > MAX_TABLE_COLUMNS:
                    raise ValueError("table_too_wide|表格列数超过限制")
                if row_number < header_row:
                    continue
                if row_number == header_row:
                    headers = [str(value).strip() if value is not None else "" for value in row]
                    if not any(headers):
                        raise ValueError("missing_header|文件缺少表头")
                    MapFoundationService._check_headers(headers)
                    if metadata is not None:
                        metadata.update(headers=headers, sheet_name=sheet.title, header_row=header_row)
                    continue
                if not headers or not any(value not in (None, "") for value in row):
                    continue
                record = {
                    key: MapFoundationService._json_safe(value)
                    for key, value in zip(headers, row)
                    if key
                }
                if any(
                    isinstance(value, str) and len(value) > MAX_CELL_TEXT_LENGTH
                    for value in record.values()
                ):
                    raise ValueError("cell_too_long|单元格文本超过限制")
                parsed.append((row_number, record))
            return parsed
        finally:
            workbook.close()

    @staticmethod
    def _check_headers(headers):
        names = [name for name in headers if name]
        if len(names) != len(set(names)):
            raise ValueError("duplicate_header|重复列名必须先处理，不能静默覆盖")
        if any(len(name) > 200 for name in names):
            raise ValueError("header_too_long|列名超过200字符")

    @staticmethod
    def validate_excel_archive(content: bytes) -> None:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                members = archive.infolist()
                if len(members) > MAX_EXCEL_MEMBERS:
                    raise ValueError("excel_archive_too_many_members|Excel 文件内部条目过多")
                total_size = sum(item.file_size for item in members)
                if total_size > MAX_EXCEL_UNCOMPRESSED_BYTES:
                    raise ValueError("excel_archive_too_large|Excel 解压后体积超过限制")
                if any(
                    item.file_size / max(item.compress_size, 1) > 100
                    for item in members
                    if item.file_size > 1024 * 1024
                ):
                    raise ValueError("excel_archive_ratio_invalid|Excel 压缩比异常")
        except zipfile.BadZipFile as exc:
            raise ValueError("invalid_excel_archive|Excel 文件结构无效") from exc

    @staticmethod
    def list_conflicts(db: Session, source_id: int | None = None) -> list[MapFeatureClaim]:
        query = db.query(MapFeatureClaim).filter(
            MapFeatureClaim.status.in_(("conflict", "quarantined"))
        )
        if source_id is not None:
            query = query.filter(MapFeatureClaim.source_id == source_id)
        return query.order_by(MapFeatureClaim.id.desc()).all()

    @staticmethod
    def resolve_conflict(
        db: Session,
        claim_id: int,
        *,
        decision: str,
        note: str | None,
    ) -> MapFeatureClaim:
        claim = db.query(MapFeatureClaim).filter(MapFeatureClaim.id == claim_id).first()
        if not claim or claim.status not in {"conflict", "quarantined"}:
            raise ValueError("conflict_not_found")
        if decision == "reject":
            claim.status = "rejected"
            claim.error_message = (note or claim.error_message or "已人工驳回")[:1000]
        elif decision == "retry":
            # 坐标或模板参数不能在此接口中悄悄修改，重新导入才会形成新的可追溯批次。
            claim.status = "awaiting_reingest"
            claim.error_message = (note or "修正模板或源文件后重新导入")[:1000]
        else:
            raise ValueError("unsupported_resolution")
        db.commit()
        db.refresh(claim)
        return claim

    @staticmethod
    def _merge_asset(
        db: Session,
        *,
        source: MapSource,
        claim: MapFeatureClaim,
        normalized: dict[str, Any],
        resolved_payload: dict[str, Any] | None = None,
    ) -> tuple[JurisdictionAsset, bool, bool]:
        canonical_key = normalized["canonical_key"]
        identity, decision, asset = FacilityIdentityService.resolve_import(
            db, source=source, normalized=normalized,
        )
        if asset is None:
            asset = (
            db.query(JurisdictionAsset)
            .filter(JurisdictionAsset.canonical_key == canonical_key)
            .first()
            )
        if identity is None and asset is not None and (
            asset.external_id != normalized.get("external_id")
            or (asset.attributes or {}).get("source_id") != source.id
        ):
            raise ValueError("asset_identity_conflict|稳定标识与已存来源身份不一致，需人工核验")
        if asset is None:
            # Upgrade compatibility for the old case-folded ID / rounded-point
            # key: adopt only exact identity in the *same registered source*.
            # This does not revive the former same-name proximity merge.
            query = db.query(JurisdictionAsset).filter(
                JurisdictionAsset.operational_area_id == source.operational_area_id,
                JurisdictionAsset.external_id == normalized.get("external_id"),
            )
            if not normalized.get("external_id"):
                query = query.filter(
                    JurisdictionAsset.name == normalized["name"],
                    JurisdictionAsset.asset_type == normalized["asset_type"],
                    JurisdictionAsset.latitude == normalized["latitude"],
                    JurisdictionAsset.longitude == normalized["longitude"],
                )
            matches = [
                item for item in query.all()
                if (item.attributes or {}).get("source_id") == source.id
            ]
            if len(matches) > 1:
                raise ValueError("ambiguous_asset_identity|来源内稳定标识重复，需人工核验")
            asset = matches[0] if matches else None
        if asset is not None and not normalized.get("external_id") and asset.verified:
            raise ValueError("asset_identity_requires_review|无稳定编号的导入不能覆盖已核验要素")
        # Names, proximity and source trust are not proof of shared identity.
        # Only the source/area-scoped identifier (or exact unidentified record
        # fingerprint) may resolve an existing asset. Cross-source linking needs
        # an explicit, separately reviewed identity mapping.
        created = asset is None
        if asset is None:
            asset = JurisdictionAsset(canonical_key=canonical_key, name=normalized["name"],
                asset_type=normalized["asset_type"], operational_area_id=source.operational_area_id)
            db.add(asset)
            db.flush()
        identity = identity or FacilityIdentityService.ensure_identity(
            db, source=source, asset=asset, normalized=normalized,
        )
        claim.source_identity_id = identity.id
        claim.identity_decision_id = decision.id if decision else None
        if not created and resolved_payload is None:
            stored_rank = int((asset.attributes or {}).get("source_trust_rank", 0))
            stored_source_id = (asset.attributes or {}).get("source_id")
            if source.trust_rank < stored_rank:
                return asset, False, True
            if source.trust_rank == stored_rank and stored_source_id not in {None, source.id}:
                material_change = any(
                    getattr(asset, key, None) != normalized.get(key)
                    for key in (
                        "asset_type",
                        "latitude",
                        "longitude",
                        "address",
                        "verified",
                        "verification_state",
                    )
                )
                incoming_conditions = normalized.get("attributes") or {}
                stored_conditions = asset.attributes or {}
                material_change = material_change or any(
                    stored_conditions.get(key) != value for key, value in incoming_conditions.items()
                    if key != "original_coordinate_system"
                )
                if material_change:
                    return asset, False, True

        if resolved_payload is not None:
            normalized = resolved_payload
        claim_refs = list(asset.source_claim_refs or [])
        claim_refs.append(claim.id)
        attributes = dict(normalized.get("attributes") or {})
        attributes.update(
            {
                "source_id": source.id,
                "source_key": source.source_key,
                "source_trust_rank": source.trust_rank,
                "source_revision": claim.source_revision,
                "source_identity_id": identity.id,
                "identity_decision_id": decision.id if decision else None,
            }
        )
        valid_from = normalized.get("valid_from")
        valid_to = normalized.get("valid_to")
        now = datetime.now(timezone.utc)
        current_observation = (
            (valid_from is None or datetime.fromisoformat(valid_from) <= now)
            and (valid_to is None or now < datetime.fromisoformat(valid_to))
        )
        # Do not replace today's projection with an explicitly old/future row.
        # The full incoming values still become their own historical version.
        if created or current_observation:
            for key, value in normalized.items():
                if key not in {"attributes", "valid_from", "valid_to"}:
                    if not created and key in {"canonical_key", "external_id"}:
                        continue  # source aliases never replace the stable business identity
                    setattr(asset, key, value)
            asset.attributes = attributes
            asset.valid_from = datetime.fromisoformat(valid_from) if valid_from else None
            asset.valid_to = datetime.fromisoformat(valid_to) if valid_to else None
            if not current_observation:
                asset.verified = False
                asset.verification_state = "temporal_not_current"
        elif valid_from and valid_to and (asset.attributes or {}).get("source_identity_id") == identity.id:
            stored_start = asset.valid_from
            if stored_start is not None and stored_start.tzinfo is None:
                stored_start = stored_start.replace(tzinfo=timezone.utc)
            # A late end-date correction of the same period also invalidates
            # the flat current projection, not only the bitemporal read.
            if stored_start == datetime.fromisoformat(valid_from) and datetime.fromisoformat(valid_to) <= now:
                asset.valid_to = datetime.fromisoformat(valid_to)
                asset.verified = False
                asset.verification_state = "temporal_not_current"
        asset.source_claim_refs = claim_refs
        db.flush()
        return asset, created, False

    @staticmethod
    def _record_asset_version(
        db: Session,
        *,
        asset: JurisdictionAsset,
        claim: MapFeatureClaim | None = None,
        change_type: str,
        validity: dict | None = None,
    ) -> JurisdictionAssetVersion:
        return FacilityIdentityService.record_asset_version(
            db, asset=asset, claim=claim, change_type=change_type, validity=validity,
        )

    @staticmethod
    def record_observed_baseline(db: Session, asset: JurisdictionAsset) -> None:
        """Record what is observable now, never invent an old creation history."""
        latest = (
            db.query(JurisdictionAssetVersion)
            .filter(JurisdictionAssetVersion.asset_id == asset.id)
            .order_by(JurisdictionAssetVersion.version.desc())
            .first()
        )
        if latest is None:
            MapFoundationService._record_asset_version(
                db, asset=asset, change_type="baseline_observed",
            )

    @staticmethod
    def _normalize_row(
        source: MapSource,
        template: MapImportTemplate,
        raw: dict[str, Any],
        *,
        area_boundary: Any = None,
        geometry_state: str = "set",
    ) -> dict[str, Any]:
        mapping = template.field_mapping or {}
        name = MapFoundationService._clean_string(
            MapFoundationService._mapped_value(raw, mapping, "name")
        )
        asset_type = MapFoundationService._clean_string(
            MapFoundationService._mapped_value(raw, mapping, "asset_type")
        )
        external_id = MapFoundationService._clean_string(
            MapFoundationService._mapped_value(raw, mapping, "external_id")
        )
        if not name:
            raise ValueError("missing_name|缺少要素名称")
        if not asset_type:
            raise ValueError("missing_asset_type|缺少要素类型")

        longitude_raw = MapFoundationService._mapped_value(raw, mapping, "longitude")
        latitude_raw = MapFoundationService._mapped_value(raw, mapping, "latitude")
        if template.axis_order == "lat_lon":
            longitude_raw, latitude_raw = latitude_raw, longitude_raw
        longitude = latitude = None
        if geometry_state == "set":
            try:
                first = float(longitude_raw)
                second = float(latitude_raw)
            except (TypeError, ValueError):
                raise ValueError("invalid_coordinate|经纬度缺失或不是有效数字") from None
            longitude, latitude = MapFoundationService._to_wgs84(
                first, second, coordinate_system=template.coordinate_system, transformation=template.transformation)
            if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
                raise ValueError("coordinate_out_of_range|转换后的经纬度超出有效范围")
        elif not external_id:
            raise ValueError("asset_identity_required|未提供坐标时必须有来源稳定编号")
        if geometry_state == "set" and area_boundary and not MapFoundationService._point_in_area_boundary(
            longitude,
            latitude,
            area_boundary,
        ):
            raise ValueError("outside_operational_area|转换后的坐标位于厂区边界外")

        identity = (
            {
                "source_key": source.source_key,
                "external_id": external_id,
            }
            if external_id
            else {
                "source_key": source.source_key,
                "name": MapFoundationService._canonical_text(name),
                "asset_type": asset_type.lower(),
                "latitude": round(latitude, 8),
                "longitude": round(longitude, 8),
            }
        )
        canonical_suffix = MapFoundationService._hash_json(identity)[:24]
        address = MapFoundationService._clean_string(
            MapFoundationService._mapped_value(raw, mapping, "address")
        )
        is_public_reference = source.source_type == "public_map"
        production_attributes: dict[str, Any] = {
            "original_coordinate_system": template.coordinate_system,
        }
        for key in (
            "oil_type",
            "owner_unit",
            "production_unit",
            "production_status",
            "facility_category",
            "water_cut_unit",
            "water_cut_basis",
            "production_output_unit",
            "production_period",
            "production_basis",
        ):
            value = MapFoundationService._clean_string(
                MapFoundationService._mapped_value(raw, mapping, key)
            )
            if value is not None:
                production_attributes[key] = value
        for key in ("water_cut_min", "water_cut_max"):
            value = MapFoundationService._mapped_value(raw, mapping, key)
            if value not in (None, ""):
                try:
                    parsed = float(value)
                except (TypeError, ValueError):
                    raise ValueError("invalid_water_cut_range|含水率区间必须是百分比数值") from None
                if isinstance(value, bool) or not math.isfinite(parsed) or not 0 <= parsed <= 100:
                    raise ValueError("invalid_water_cut_range|含水率区间必须在0至100之间")
                production_attributes[key] = parsed
        if all(key in production_attributes for key in ("water_cut_min", "water_cut_max")):
            if production_attributes["water_cut_min"] > production_attributes["water_cut_max"]:
                raise ValueError("invalid_water_cut_range|含水率下限不能大于上限")
        if production_attributes.get("water_cut_unit") not in {None, "%", "percent", "百分比"}:
            raise ValueError("invalid_water_cut_unit|含水率单位必须明确为百分比，不自动换算")
        for key in ("production_valid_from", "production_valid_to"):
            value = MapFoundationService._mapped_value(raw, mapping, key)
            if value not in (None, ""):
                try:
                    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                except ValueError:
                    raise ValueError("invalid_production_time|生产条件有效时间必须是ISO日期时间") from None
                # Explicit timezone avoids silently shifting spreadsheet dates.
                if parsed.tzinfo is None:
                    raise ValueError("invalid_production_time|生产条件有效时间需标明时区")
                production_attributes[key] = parsed.astimezone(timezone.utc).isoformat()
        if all(key in production_attributes for key in ("production_valid_from", "production_valid_to")):
            if production_attributes["production_valid_from"] >= production_attributes["production_valid_to"]:
                raise ValueError("invalid_production_time|生产条件有效结束时间必须晚于开始时间")
        validity = {}
        for key in ("valid_from", "valid_to"):
            value = MapFoundationService._mapped_value(raw, mapping, key)
            if value in (None, ""):
                # An oil-property interval alone does not establish the validity
                # of geometry, names or the whole facility observation.
                validity[key] = None
                continue
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                raise ValueError("invalid_production_time|资料有效时间必须是ISO日期时间") from None
            if parsed.tzinfo is None:
                raise ValueError("invalid_production_time|资料有效时间需标明时区")
            validity[key] = parsed.astimezone(timezone.utc).isoformat()
        if validity["valid_to"] and (not validity["valid_from"] or validity["valid_to"] <= validity["valid_from"]):
            raise ValueError("invalid_production_time|资料有效结束时间必须晚于明确开始时间")
        production_output = MapFoundationService._mapped_value(
            raw,
            mapping,
            "production_output",
        )
        if production_output not in (None, ""):
            try:
                production_attributes["production_output"] = float(production_output)
            except (TypeError, ValueError):
                raise ValueError("invalid_production_output|产量字段不是有效数字") from None
            if isinstance(production_output, bool) or not math.isfinite(production_attributes["production_output"]) or production_attributes["production_output"] < 0:
                raise ValueError("invalid_production_output|产量必须是非负有限数字")
        high_production = MapFoundationService._mapped_value(
            raw,
            mapping,
            "is_high_production",
        )
        if high_production not in (None, ""):
            if str(high_production).strip().lower() not in {"1", "true", "yes", "y", "是", "高产", "0", "false", "no", "n", "否", "非高产"}:
                raise ValueError("invalid_high_production|高产标识必须明确为是或否")
            production_attributes["is_high_production"] = str(high_production).strip().lower() in {
                "1", "true", "yes", "y", "是", "高产",
            }
        return {
            "operational_area_id": source.operational_area_id,
            "external_id": external_id,
            "canonical_key": f"area:{source.operational_area_id}:{canonical_suffix}",
            "name": name,
            "asset_type": asset_type.lower(),
            "geometry_type": "point",
            "latitude": round(latitude, 8) if latitude is not None else None,
            "longitude": round(longitude, 8) if longitude is not None else None,
            "geometry": {
                "type": "Point",
                "coordinates": [round(longitude, 8), round(latitude, 8)],
            } if longitude is not None and latitude is not None else None,
            "address": address,
            "source": source.source_type,
            "status": "active",
            "risk_level": 1,
            "confidence_score": 0.7 if is_public_reference else 1.0,
            "verified": bool(external_id) and not is_public_reference,
            "verification_state": (
                "identity_pending" if not external_id
                else "reference_only" if is_public_reference else "source_verified"
            ),
            "coordinate_system": "epsg:4326",
            "attributes": production_attributes,
            **validity,
        }

    @staticmethod
    def _point_in_area_boundary(longitude: float, latitude: float, boundary: Any) -> bool:
        if isinstance(boundary, list) and len(boundary) == 4:
            west, south, east, north = boundary
            return float(west) <= longitude <= float(east) and float(south) <= latitude <= float(north)
        if not isinstance(boundary, dict):
            return False
        geometry = boundary.get("geometry") if boundary.get("type") == "Feature" else boundary
        geometry_type = geometry.get("type")
        coordinates = geometry.get("coordinates")
        if geometry_type == "Polygon":
            polygons = [coordinates]
        elif geometry_type == "MultiPolygon":
            polygons = coordinates
        else:
            return False
        for polygon in polygons or []:
            if polygon and MapFoundationService._point_in_ring(longitude, latitude, polygon[0]):
                if not any(
                    MapFoundationService._point_in_ring(longitude, latitude, hole)
                    for hole in polygon[1:]
                ):
                    return True
        return False

    @staticmethod
    def _point_in_ring(longitude: float, latitude: float, ring: Any) -> bool:
        if not isinstance(ring, list) or len(ring) < 3:
            return False
        inside = False
        previous = ring[-1]
        for current in ring:
            try:
                x1, y1 = float(previous[0]), float(previous[1])
                x2, y2 = float(current[0]), float(current[1])
            except (TypeError, ValueError, IndexError):
                return False
            intersects = (y1 > latitude) != (y2 > latitude) and longitude < (
                (x2 - x1) * (latitude - y1) / ((y2 - y1) or 1e-15) + x1
            )
            if intersects:
                inside = not inside
            previous = current
        return inside

    @staticmethod
    def _to_wgs84(
        first: float,
        second: float,
        *,
        coordinate_system: str,
        transformation: dict[str, Any] | None,
    ) -> tuple[float, float]:
        if coordinate_system in {"wgs84", "cgcs2000_geographic"}:
            return first, second
        if coordinate_system == "gcj02":
            return MapFoundationService._gcj02_to_wgs84(first, second)
        if coordinate_system == "bd09":
            gcj_lon, gcj_lat = MapFoundationService._bd09_to_gcj02(first, second)
            return MapFoundationService._gcj02_to_wgs84(gcj_lon, gcj_lat)
        if coordinate_system in {"cgcs2000_gauss_kruger", "local_control_points"}:
            # 首期不引入会在不同系统上漂移的隐式坐标库；必须由模板提供经核验的仿射参数。
            params = transformation or {}
            required = {"a", "b", "c", "d", "e", "f"}
            if not required.issubset(params):
                raise ValueError("transformation_required|投影或本地坐标缺少经控制点核验的转换参数")
            longitude = float(params["a"]) * first + float(params["b"]) * second + float(params["c"])
            latitude = float(params["d"]) * first + float(params["e"]) * second + float(params["f"])
            return longitude, latitude
        raise ValueError("unsupported_coordinate_system|不支持的坐标系")

    @staticmethod
    def _validate_transformation(
        coordinate_system: str,
        transformation: dict[str, Any] | None,
    ) -> None:
        if coordinate_system not in {"cgcs2000_gauss_kruger", "local_control_points"}:
            return
        params = transformation or {}
        if not {"a", "b", "c", "d", "e", "f"}.issubset(params):
            raise ValueError("transformation_required")
        try:
            for key in ("a", "b", "c", "d", "e", "f"):
                float(params[key])
        except (TypeError, ValueError):
            raise ValueError("invalid_transformation") from None

    @staticmethod
    def _gcj02_to_wgs84(longitude: float, latitude: float) -> tuple[float, float]:
        if not (72.004 <= longitude <= 137.8347 and 0.8293 <= latitude <= 55.8271):
            return longitude, latitude
        delta_lon, delta_lat = MapFoundationService._gcj_delta(longitude, latitude)
        return longitude - delta_lon, latitude - delta_lat

    @staticmethod
    def _gcj_delta(longitude: float, latitude: float) -> tuple[float, float]:
        x = longitude - 105.0
        y = latitude - 35.0
        d_lat = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y
        d_lat += 0.2 * math.sqrt(abs(x))
        d_lat += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2 / 3
        d_lat += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3 * math.pi)) * 2 / 3
        d_lat += (160.0 * math.sin(y / 12 * math.pi) + 320 * math.sin(y * math.pi / 30)) * 2 / 3
        d_lon = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y
        d_lon += 0.1 * math.sqrt(abs(x))
        d_lon += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2 / 3
        d_lon += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3 * math.pi)) * 2 / 3
        d_lon += (150.0 * math.sin(x / 12 * math.pi) + 300.0 * math.sin(x / 30 * math.pi)) * 2 / 3
        rad_lat = latitude / 180.0 * math.pi
        magic = 1 - 0.006693421622965943 * math.sin(rad_lat) ** 2
        sqrt_magic = math.sqrt(magic)
        d_lat = d_lat * 180.0 / ((6378245.0 * (1 - 0.006693421622965943)) / (magic * sqrt_magic) * math.pi)
        d_lon = d_lon * 180.0 / (6378245.0 / sqrt_magic * math.cos(rad_lat) * math.pi)
        return d_lon, d_lat

    @staticmethod
    def _bd09_to_gcj02(longitude: float, latitude: float) -> tuple[float, float]:
        x = longitude - 0.0065
        y = latitude - 0.006
        z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * math.pi * 3000 / 180)
        theta = math.atan2(y, x) - 0.000003 * math.cos(x * math.pi * 3000 / 180)
        return z * math.cos(theta), z * math.sin(theta)

    @staticmethod
    def _get_source(db: Session, source_id: int) -> MapSource:
        source = db.query(MapSource).populate_existing().filter(MapSource.id == source_id).first()
        if not source or source.status != "active":
            raise ValueError("source_not_found")
        return source

    @staticmethod
    def _get_template(db: Session, source_id: int, template_id: int) -> MapImportTemplate:
        template = (
            db.query(MapImportTemplate)
            .populate_existing()
            .filter(
                MapImportTemplate.id == template_id,
                MapImportTemplate.source_id == source_id,
                MapImportTemplate.is_active.is_(True),
            )
            .first()
        )
        if not template:
            raise ValueError("template_not_found")
        return template

    @staticmethod
    def source_to_dict(db: Session, source: MapSource) -> dict[str, Any]:
        area = db.query(OperationalArea).filter(OperationalArea.id == source.operational_area_id).first()
        return {
            "id": source.id,
            "source_key": source.source_key,
            "name": source.name,
            "source_type": source.source_type,
            "trust_rank": source.trust_rank,
            "status": source.status,
            "description": source.description,
            "configuration": source.configuration,
            "operational_area": MapFoundationService.area_to_dict(area) if area else None,
            "created_at": source.created_at,
            "updated_at": source.updated_at,
        }

    @staticmethod
    def area_to_dict(area: OperationalArea) -> dict[str, Any]:
        return {
            "id": area.id,
            "code": area.code,
            "name": area.name,
            "boundary": area.boundary,
            "is_default": area.is_default,
            "status": area.status,
        }

    @staticmethod
    def template_to_dict(template: MapImportTemplate) -> dict[str, Any]:
        return {
            "id": template.id,
            "source_id": template.source_id,
            "name": template.name,
            "sheet_name": template.sheet_name,
            "header_row": template.header_row,
            "field_mapping": template.field_mapping,
            "coordinate_system": template.coordinate_system,
            "axis_order": template.axis_order,
            "coordinate_unit": template.coordinate_unit,
            "transformation": template.transformation,
            "expected_structure": template.expected_structure,
            "field_units": template.field_units,
            "version": template.version,
            "is_active": template.is_active,
            "created_at": MapFoundationService._json_safe(template.created_at),
            "updated_at": MapFoundationService._json_safe(template.updated_at),
        }

    @staticmethod
    def run_to_dict(run: MapIngestRun, *, idempotent_replay: bool = False) -> dict[str, Any]:
        return {
            "id": run.id,
            "source_id": run.source_id,
            "template_id": run.template_id,
            "status": run.status,
            "filename": run.filename,
            "source_revision": run.source_revision,
            "file_hash": run.file_hash,
            "request_sha256": run.request_sha256,
            "total_rows": run.total_rows,
            "valid_rows": run.valid_rows,
            "quarantined_rows": run.quarantined_rows,
            "created_assets": run.created_assets,
            "updated_assets": run.updated_assets,
            "errors": run.errors or [],
            "table_metadata": {key: value for key, value in (run.table_metadata or {}).items() if key != "ledger_comparison"},
            "ledger_declaration": (run.table_metadata or {}).get("ledger_declaration"),
            "declaration_actor_id": run.created_by if (run.table_metadata or {}).get("ledger_declaration") else None,
            "template_snapshot": run.template_snapshot,
            "counts": run.classification_counts or {},
            "parent_run_id": run.parent_run_id,
            "original_evidence_object_id": run.original_evidence_object_id,
            "started_at": MapFoundationService._json_safe(run.started_at),
            "received_at": MapFoundationService._json_safe(run.started_at),
            "completed_at": MapFoundationService._json_safe(run.completed_at),
            "idempotent_replay": idempotent_replay,
        }

    @staticmethod
    def claim_to_dict(claim: MapFeatureClaim) -> dict[str, Any]:
        return {
            "id": claim.id,
            "run_id": claim.run_id,
            "source_id": claim.source_id,
            "row_number": claim.row_number,
            "source_record_id": claim.source_record_id,
            "source_revision": claim.source_revision,
            "status": claim.status,
            "error_code": claim.error_code,
            "error_message": claim.error_message,
            "asset_id": claim.asset_id,
            "raw_payload": claim.raw_payload,
            "normalized_payload": claim.normalized_payload,
            "plan": claim.plan,
            "parent_claim_id": claim.parent_claim_id,
            "correction_note": claim.correction_note,
            "source_identity_id": claim.source_identity_id,
            "identity_decision_id": claim.identity_decision_id,
            "created_at": MapFoundationService._json_safe(claim.created_at),
        }

    @staticmethod
    def asset_to_dict(asset: JurisdictionAsset) -> dict[str, Any]:
        return {
            "id": asset.id,
            "operational_area_id": asset.operational_area_id,
            "external_id": asset.external_id,
            "canonical_key": asset.canonical_key,
            "name": asset.name,
            "asset_type": asset.asset_type,
            "geometry_type": asset.geometry_type,
            "latitude": asset.latitude,
            "longitude": asset.longitude,
            "geometry": asset.geometry,
            "address": asset.address,
            "description": asset.description,
            "source": asset.source,
            "status": asset.status,
            "verified": asset.verified,
            "verification_state": asset.verification_state,
            "coordinate_system": asset.coordinate_system,
            "accuracy_m": asset.accuracy_m,
            "source_claim_refs": asset.source_claim_refs,
            "attributes": asset.attributes,
            "tags": asset.tags,
            "valid_from": MapFoundationService._json_safe(asset.valid_from),
            "valid_to": MapFoundationService._json_safe(asset.valid_to),
        }

    @staticmethod
    def _mapped_value(raw: dict[str, Any], mapping: dict[str, Any], key: str) -> Any:
        source_column = mapping.get(key)
        return raw.get(source_column) if source_column else None

    @staticmethod
    def _clean_string(value: Any) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @staticmethod
    def _canonical_text(value: str) -> str:
        return "".join(value.casefold().split())

    @staticmethod
    def _hash_json(value: Any) -> str:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _json_safe_dict(value: dict[str, Any]) -> dict[str, Any]:
        return {str(key): MapFoundationService._json_safe(item) for key, item in value.items()}

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if isinstance(value, datetime):
            # SQLite stores UTC instants without tzinfo; source input is still
            # required to declare a timezone before it reaches storage.
            return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    @staticmethod
    def _error_parts(exc: ValueError) -> tuple[str, str]:
        raw = str(exc)
        if "|" in raw:
            return tuple(raw.split("|", 1))  # type: ignore[return-value]
        messages = {
            "source_not_found": "地图来源不存在或已停用",
            "template_not_found": "导入模板不存在、已停用或不属于该来源",
        }
        return raw, messages.get(raw, raw)
