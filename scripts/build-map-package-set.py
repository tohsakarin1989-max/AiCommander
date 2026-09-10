#!/usr/bin/env python3
"""Build a public transport package from a trusted local, hash-bound recipe.

Only for the isolated public build zone; not exposed as a web endpoint.
Recipe asset paths must be absolute canonical paths to regular local files.
"""
import argparse
import json
import os
from pathlib import Path
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.services.map_package_builder import build_package
from app.services.map_package_set import MAX_MANIFEST_BYTES, _object


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recipe', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    try:
        fd = os.open(args.recipe, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_MANIFEST_BYTES:
                raise ValueError('invalid_recipe_file')
            content = source.read(MAX_MANIFEST_BYTES + 1)
        if len(content) > MAX_MANIFEST_BYTES:
            raise ValueError('recipe_size_limit')
        recipe = json.loads(content, object_pairs_hook=_object)
        if not isinstance(recipe, dict):
            raise ValueError('invalid_recipe_object')
        report = build_package(recipe, args.destination)
    except (OSError, ValueError, TypeError, RecursionError):
        print(json.dumps({'status': 'build_failed', 'publish_ready': False,
                          'message': '制包清单、输入文件或输出目录不符合要求'}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
