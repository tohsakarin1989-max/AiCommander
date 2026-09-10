#!/usr/bin/env python3
"""在受控交换前后深度校验公共离线地图包。"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend"))
# 该命令只做本地文件解析，不启动应用或签发任何令牌；给配置模型提供一个
# 进程内占位值，避免独立验包被在线服务的 SECRET_KEY 门槛阻断。
os.environ.setdefault("SECRET_KEY", "offline-map-bundle-verifier-only")

from app.services.offline_map_service import MAX_BUNDLE_BYTES  # noqa: E402
from app.services.public_map_bundle_verifier import PublicMapBundleVerifier  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="校验公共地图 ZIP 清单、摘要、MBTiles 完整性和全部瓦片可读性。",
    )
    parser.add_argument("bundle", type=Path, help="待校验的公共地图 ZIP")
    parser.add_argument("--evidence", type=Path, help="可选的只含校验摘要的 JSON 证据文件")
    return parser


def _write_new_file(path: Path, content: str) -> None:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise ValueError("evidence_file_exists")
    temporary = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
        delete=False,
    )
    temporary_path = Path(temporary.name)
    try:
        with temporary:
            temporary.write(content)
            temporary.write("\n")
        os.chmod(temporary_path, 0o600)
        os.link(temporary_path, target)
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        path = args.bundle.expanduser().resolve()
        if path.suffix.lower() != ".zip" or not path.is_file():
            raise ValueError("bundle_not_found")
        with path.open("rb") as handle:
            content = handle.read(MAX_BUNDLE_BYTES + 1)
        if len(content) > MAX_BUNDLE_BYTES:
            raise ValueError("bundle_too_large")
        report = PublicMapBundleVerifier.verify_bytes(content)
        serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
        if args.evidence:
            _write_new_file(args.evidence, serialized)
    except Exception as exc:
        parser.exit(2, f"公共地图包验证失败: {exc}\n")
    print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
