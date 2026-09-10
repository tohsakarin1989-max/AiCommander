#!/usr/bin/env python3
"""Read-only public package-set integrity probe; exit 0 is NOT publish approval."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from app.services.map_package_set import read_manifest, verify_directory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='受控公共地图分片目录')
    args = parser.parse_args()
    try:
        manifest = read_manifest(args.directory)
        report = verify_directory(args.directory, manifest)
    except (OSError, ValueError) as exc:
        # Avoid emitting operator paths or low-level exception text.
        print(json.dumps({'status': 'invalid_package', 'publish_ready': False,
                          'error_type': type(exc).__name__}))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['status'] == 'integrity_verified' else 1


if __name__ == '__main__':
    raise SystemExit(main())
