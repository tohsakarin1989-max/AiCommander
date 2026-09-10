#!/usr/bin/env python3
"""Validate an assembled schema-2 render bundle; NOT geographic/routing approval."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='服务端重组后的地图资产目录')
    args = parser.parse_args()
    try:
        from app.services.map_render_bundle_validation import validate_render_bundle
        report = validate_render_bundle(args.directory)
    except (OSError, ValueError, ImportError):
        print(json.dumps({'status': 'render_validation_failed', 'publish_ready': False,
                          'message': '地图渲染资源、依赖或读取条件不符合要求'}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
