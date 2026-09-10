#!/usr/bin/env python3
"""Validate one public MVT asset; exit zero is not map publication approval."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.services.vector_map_validation import validate_vector_mbtiles


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mbtiles', type=Path)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--bounds', required=True, nargs=4, type=float)
    parser.add_argument('--min-zoom', type=int, default=6)
    parser.add_argument('--max-zoom', type=int, default=16)
    parser.add_argument('--audit-public-labels', action='store_true',
                        help='Audit fixed public place, POI and road label fields; not shaping or full style evaluation')
    arguments = parser.parse_args()
    try:
        report = validate_vector_mbtiles(arguments.mbtiles, arguments.sha256,
            bounds=arguments.bounds, min_zoom=arguments.min_zoom, max_zoom=arguments.max_zoom,
            label_fields={layer: ('name:zh', 'name:latin', 'name')
                          for layer in ('place', 'poi', 'transportation_name')}
                         if arguments.audit_public_labels else None)
    except (OSError, ValueError, ImportError):
        print(json.dumps({'status': 'validation_failed', 'publish_ready': False,
                          'message': '地图内容、依赖或读取条件不符合要求'}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
