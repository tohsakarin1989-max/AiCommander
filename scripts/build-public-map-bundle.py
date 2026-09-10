#!/usr/bin/env python3
"""在联网区从批准的 XYZ 服务生成 AiCommander 公共离线地图包。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend"))

from app.services.public_map_bundle_builder import (  # noqa: E402
    PublicMapBundleBuilder,
    PublicTileFetchPolicy,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从显式批准的 HTTPS XYZ 瓦片源生成公共数据离线包；不得输入案件或生产坐标。",
    )
    parser.add_argument("--output", type=Path, required=True, help="新 ZIP 输出路径，已存在时拒绝覆盖")
    parser.add_argument(
        "--bounds",
        type=float,
        nargs=4,
        metavar=("WEST", "SOUTH", "EAST", "NORTH"),
        required=True,
        help="仅包含公共地图范围的 WGS84 边界",
    )
    parser.add_argument("--min-zoom", type=int, required=True)
    parser.add_argument("--max-zoom", type=int, required=True)
    parser.add_argument("--bundle-id", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--license-record", required=True, help="批准的许可或授权记录编号")
    parser.add_argument("--attribution", required=True, help="地图页面必须展示的来源署名")
    parser.add_argument(
        "--tile-url",
        required=True,
        help="HTTPS XYZ 模板，必须包含 {z}、{x}、{y}",
    )
    parser.add_argument(
        "--allow-host",
        action="append",
        required=True,
        help="批准访问的瓦片主机，可重复指定",
    )
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--request-delay-seconds", type=float, default=0.0)
    parser.add_argument("--max-tile-count", type=int, default=50_000)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        policy = PublicTileFetchPolicy(
            url_template=args.tile_url,
            allowed_hosts=set(args.allow_host),
            timeout_seconds=args.timeout_seconds,
            request_delay_seconds=args.request_delay_seconds,
        )
        report = PublicMapBundleBuilder.build(
            output_path=args.output,
            bounds=args.bounds,
            min_zoom=args.min_zoom,
            max_zoom=args.max_zoom,
            bundle_id=args.bundle_id,
            provider=args.provider,
            source_version=args.source_version,
            license_record=args.license_record,
            attribution=args.attribution,
            fetch_tile=policy.fetch,
            max_tile_count=args.max_tile_count,
        )
    except Exception as exc:
        parser.exit(2, f"公共地图制包失败: {exc}\n")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
