#!/usr/bin/env python3
"""Read-only delivery/recovery inventory check. No download, restore or deletion.

The manifest is an operator-approved inventory, not a signature or evidence of
deployment. Hashes verify transport; optional Docker probes verify only the
declared local runtime, never the business database or live containers.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile


DIGEST = re.compile(r"[0-9a-f]{64}\Z")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+[-.a-zA-Z0-9]*\Z")
CAPABILITIES = {"core", "maps", "documents", "roads", "map_build", "embedding"}
DELIVERY_ROLES = {
    "core": {"release_archive", "image_archive", "operations_guide"},
    "maps": {"map_packages", "map_manifest", "map_fonts", "map_style", "map_icons", "place_index"},
    "documents": set(),  # Dependencies live in the API image and are probed below.
    "roads": {"road_source", "road_manifest"},
    "map_build": set(),
    "embedding": {"embedding_bundle", "embedding_manifest"},
}
BASE_SERVICES = {"postgres", "redis", "backend", "celery", "celery-beat", "frontend"}


class Invalid(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Invalid(message)


def digest_file(path):
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def safe_file(root, value):
    require(isinstance(value, str) and value and "\\" not in value, "文件相对路径无效")
    relative = PurePosixPath(value)
    require(not relative.is_absolute() and ".." not in relative.parts, "拒绝越界文件路径")
    current = root
    for part in relative.parts:
        current /= part
        require(not current.is_symlink(), "交付文件不能使用符号链接")
    require(current.is_file() and current.resolve().is_relative_to(root), "清单文件缺失或不是普通文件")
    return current


def check_tar(path):
    """Validate only archives we explicitly recommend restoring with tar."""
    try:
        with tarfile.open(path, "r:*") as archive:
            count = files = 0
            for member in archive:
                count += 1
                require(count <= 1_000_000, "地图归档条目超过核对预算")
                name = PurePosixPath(member.name)
                require(not name.is_absolute() and ".." not in name.parts,
                        "地图归档含越界路径")
                require(member.isfile() or member.isdir(), "地图归档不能含链接或特殊设备")
                files += int(member.isfile())
            require(files > 0, "地图归档没有文件")
    except (tarfile.TarError, OSError) as error:
        raise Invalid("地图文件归档不可读取") from error


def docker(args):
    try:
        result = subprocess.run(["docker", *args], capture_output=True, text=True,
                                timeout=45, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Invalid("本机镜像检查不可用或超时；不会下载") from error
    require(result.returncode == 0, "本机镜像或运行依赖检查失败；不会下载，未操作业务卷")
    return result.stdout


def probe(image, capability):
    commands = {
        "documents": (
            "import pathlib, subprocess; import docx; import playwright.sync_api; "
            "from playwright.sync_api import sync_playwright; "
            "subprocess.run(['soffice','--version'],check=True,capture_output=True); "
            "subprocess.run(['node','--version'],check=True,capture_output=True); "
            "assert subprocess.check_output(['fc-list',':lang=zh']).strip(); "
            "assert pathlib.Path('/app/document-renderer/node_modules/docx').is_dir(); "
            "assert pathlib.Path('/app/document-renderer/map-render.mjs').is_file(); "
            "p=sync_playwright().start(); "
            "assert pathlib.Path(p.chromium.executable_path).is_file() or "
            "any(pathlib.Path('/opt/aic-browsers').rglob('headless_shell')); p.stop()"
        ),
        "roads": "from valhalla import Actor",
        "embedding": "import sentence_transformers; import safetensors",
    }
    docker(["run", "--rm", "--pull=never", "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--memory", "768m",
            "--cpus", "1", "--pids-limit", "128", "--tmpfs", "/tmp:size=64m,mode=1777",
            "--entrypoint", "python", image, "-c", commands[capability]])


def check_images(data, enabled, check_local, probe_runtime, compose_config):
    images = data.get("images")
    require(isinstance(images, list) and 0 < len(images) <= 32, "缺少明确镜像清单")
    by_service = {}
    for item in images:
        service = item.get("service")
        require(service in BASE_SERVICES | {"agent-worker", "road-worker", "map-worker"}, "未知服务镜像")
        require(service not in by_service, "服务镜像重复")
        reference = item.get("reference", "")
        require(isinstance(reference, str) and reference and not reference.startswith("-")
                and not any(char.isspace() for char in reference), "镜像引用无效")
        require(DIGEST.fullmatch(item.get("image_id", "").removeprefix("sha256:")), "镜像须记录不可变ID")
        require(item.get("platform") == data["platform"], "镜像架构与交付架构不一致")
        require(bool(item.get("version")), "每个镜像必须标明组件版本")
        if service not in {"postgres", "redis"}:
            require(item["version"] == data["application_version"], "应用/Worker镜像版本不一致")
        by_service[service] = item
        if check_local:
            actual = json.loads(docker(["image", "inspect", reference]))[0]
            require(actual["Id"] == item["image_id"], "本机镜像ID与批准清单不一致")
            require(f'{actual["Os"]}/{actual["Architecture"]}' == item["platform"], "本机镜像架构不一致")
    required = BASE_SERVICES | ({"road-worker"} if "roads" in enabled else set())
    required |= {"map-worker"} if "map_build" in enabled else set()
    require(required <= by_service.keys(), "缺少核心或已启用能力的Worker镜像")
    if compose_config is not None:
        for service, settings in compose_config.get("services", {}).items():
            require(service in by_service and settings.get("image") == by_service[service]["reference"],
                    "实际Compose服务镜像与交付清单不一致")
    if probe_runtime:
        for capability in enabled & {"documents", "roads", "embedding"}:
            probe(by_service["backend"]["image_id"], capability)


def verify(data, root, *, version, platform=None, check_local=False,
           probe_runtime=False, compose_config=None, required_capabilities=()):
    require(isinstance(data, dict) and data.get("schema_version") == 1, "清单格式必须为schema_version=1")
    require(data.get("purpose") in {"delivery", "recovery"}, "清单用途无效")
    require(VERSION.fullmatch(data.get("application_version", "")), "应用版本缺失或无效")
    require(data["application_version"] == version, "清单版本与指定恢复/发布版本不一致")
    require(data.get("platform") in {"linux/amd64", "linux/arm64"}, "必须声明目标Linux架构")
    require(platform is None or data["platform"] == platform, "清单与目标架构不一致")
    capabilities = data.get("capabilities")
    require(isinstance(capabilities, list) and len(capabilities) == len(set(capabilities)), "能力清单无效")
    enabled = set(capabilities)
    require("core" in enabled and enabled <= CAPABILITIES, "能力须含core且只能使用受控名称")
    require(set(required_capabilities) <= enabled, "交付清单未包含部署实际选择的能力")
    require("roads" not in enabled or "maps" in enabled, "道路计算交付必须同时登记地图及路网来源资源")
    artifacts = data.get("artifacts")
    require(isinstance(artifacts, list) and 0 < len(artifacts) <= 2000, "文件清单为空或超出预算")
    roles, files, hashes = set(), {}, {}
    for item in artifacts:
        require(isinstance(item, dict), "文件条目无效")
        role = item.get("role")
        require(isinstance(role, str) and role and role not in roles, "文件用途缺失或重复")
        require(role not in {"secrets", "secret_key", "credentials"}, "密钥必须分离保管，不进入此包")
        require(DIGEST.fullmatch(item.get("sha256", "")), "文件必须记录SHA-256")
        require(type(item.get("bytes")) is int and item["bytes"] > 0, "文件必须记录非零字节数")
        require(isinstance(item.get("version"), str) and item["version"], "文件必须记录来源版本")
        path = safe_file(root, item.get("path"))
        require(path.stat().st_size == item["bytes"], f"{role} 文件长度不符")
        # Maps may package fonts/style/index in one approved archive. Read that
        # archive once, while still checking every declared role's hash/size.
        if path not in hashes:
            hashes[path] = digest_file(path)
        require(hashes[path] == item["sha256"], f"{role} 文件校验不符")
        roles.add(role)
        files[role] = path
    if data["purpose"] == "delivery":
        required = set().union(*(DELIVERY_ROLES[key] for key in enabled))
        require(required <= roles, "交付缺少资源用途: " + ", ".join(sorted(required - roles)))
        check_images(data, enabled, check_local, probe_runtime, compose_config)
    else:
        require(not check_local and not probe_runtime and compose_config is None,
                "恢复对象清单不能替代预构建部署交付清单")
        required = {"database_dump", "database_manifest", "configuration_archive", "originals_inventory"}
        if "maps" in enabled or "roads" in enabled:
            required |= {"map_files", "map_inventory"}
        require(required <= roles, "恢复包缺少对象: " + ", ".join(sorted(required - roles)))
        require(data.get("capture", {}).get("writers_paused") is True,
                "必须登记同一停写窗口捕获；非一致备份不能称完整恢复包")
        require(bool(data.get("capture", {}).get("checkpoint_id")), "缺少一致性检查点")
        escrow = data.get("secret_escrow", {})
        require(escrow.get("separate") is True and bool(escrow.get("receipt_id"))
                and bool(escrow.get("last_verified_at")), "缺少分离密钥保管及可取回核验记录")
        require(data.get("configuration_encrypted") is True, "配置备份必须受控加密")
        with files["database_dump"].open("rb") as stream:
            require(stream.read(5) == b"PGDMP", "数据库备份不是PostgreSQL custom格式")
        require(files["database_manifest"].stat().st_size <= 65536, "数据库清单过大")
        fields = dict(line.split("=", 1) for line in files["database_manifest"].read_text().splitlines() if "=" in line)
        require(fields.get("format") == "postgres-custom", "数据库清单格式不符")
        require(fields.get("application_version") == version, "数据库备份与恢复应用版本不一致")
        revision = fields.get("database_revision", "")
        require(re.fullmatch(r"[a-zA-Z0-9_]+", revision) and revision not in {"unknown", "untracked"}, "数据库备份迁移版本未登记")
        require(revision == data.get("database_revision"), "数据库迁移版本与恢复清单不一致")
        require(files["originals_inventory"].stat().st_size <= 4 * 1024 * 1024, "原件登记过大")
        originals = json.loads(files["originals_inventory"].read_text())
        require(originals.get("database_storage") == "evidence_objects.content", "原件登记须明确数据库内容存储")
        require(originals.get("external_status") in {"none_recorded", "included"},
                "外部原件尚未核对或未备份，不能标记整套对象齐备")
        if originals["external_status"] == "included":
            require("original_files" in roles, "登记了外部原件但未包含受控原件备份")
        if "map_files" in files:
            check_tar(files["map_files"])
    return {"status": "inventory_verified", "purpose": data["purpose"],
            "application_version": version, "platform": data["platform"],
            "capabilities": sorted(enabled), "artifacts_verified": len(files),
            "local_images_checked": check_local,
            "runtime_dependencies_probed": probe_runtime and bool(enabled & {"documents", "roads", "embedding"}),
            "restore_exercised": False, "target_deployment_verified": False,
            "boundary": "文件一致性及声明核对，不替代来源签发、实际导出、离线地图或联合恢复验收"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--root", type=Path, required=True, help="交付包根目录；不得包含真实密钥")
    parser.add_argument("--version", required=True)
    parser.add_argument("--purpose", choices=["delivery", "recovery"])
    parser.add_argument("--platform", choices=["linux/amd64", "linux/arm64"])
    parser.add_argument("--check-images", action="store_true")
    parser.add_argument("--probe-runtime", action="store_true")
    parser.add_argument("--require-capability", choices=sorted(CAPABILITIES), action="append", default=[])
    parser.add_argument("--record", action="store_true", help="只读已声明文件/本机镜像，向stdout生成待批准摘要；不证明包完整或可信")
    parser.add_argument("--compose-stdin", action="store_true", help="从stdin核对已选服务的Compose JSON，不输出其环境配置")
    args = parser.parse_args()
    try:
        require(args.manifest.stat().st_size <= 4 * 1024 * 1024, "清单过大")
        require(not args.probe_runtime or args.check_images, "运行探针必须同时检查镜像ID")
        data = json.loads(args.manifest.read_text())
        require(args.purpose is None or data.get("purpose") == args.purpose, "清单用途与本次操作不一致")
        if args.record:
            require(not args.probe_runtime and not args.compose_stdin, "生成摘要不能同时执行运行验收")
            for item in data.get("artifacts", []):
                path = safe_file(args.root.resolve(), item.get("path"))
                item.update(sha256=digest_file(path), bytes=path.stat().st_size)
            for item in data.get("images", []) if args.check_images else []:
                actual = json.loads(docker(["image", "inspect", item["reference"]]))[0]
                item.update(image_id=actual["Id"], platform=f'{actual["Os"]}/{actual["Architecture"]}')
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0
        config = json.load(sys.stdin) if args.compose_stdin else None
        result = verify(data, args.root.resolve(), version=args.version, platform=args.platform,
                        check_local=args.check_images, probe_runtime=args.probe_runtime, compose_config=config,
                        required_capabilities=args.require_capability)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (Invalid, OSError, ValueError, KeyError, TypeError) as error:
        # Never echo input bodies, Docker stderr, credentials or business text.
        message = str(error) if isinstance(error, Invalid) else "无法解析或读取清单；检查结构、文件和权限"
        print("交付/恢复清单核对失败: " + message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
