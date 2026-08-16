#!/usr/bin/env python3
"""Create the deterministic, versioned Phase 0 MCAN artifact package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[2]
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
MAX_ELF_BYTES = 4 * 1024 * 1024
SOURCE_SUFFIX = "tools/phase0/mcan0_external_probe/src/main.c"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fail(message: str) -> None:
    raise SystemExit(message)


def safe_relative_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        fail(f"invalid {label}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        fail(f"invalid {label}")
    if str(path) != value:
        fail(f"invalid {label}")
    return value


def repository_output(value: object, label: str) -> Path:
    relative = safe_relative_path(value, label)
    path = ROOT / relative
    try:
        parent = path.parent.resolve(strict=True)
        parent.relative_to(ROOT.resolve())
    except ValueError as error:
        fail(f"invalid {label}")
        raise AssertionError from error
    if parent != path.parent.absolute():
        fail(f"invalid {label}")
    if path.is_symlink():
        fail(f"{label} must not be a symlink")
    if path.exists() and not path.is_file():
        fail(f"{label} must be a regular file or absent")
    return path


def cache_values(build: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (build / "CMakeCache.txt").read_text().splitlines():
        if "=" not in line or ":" not in line.split("=", 1)[0]:
            continue
        name = line.split(":", 1)[0]
        values[name] = line.split("=", 1)[1]
    return values


def tool_version(path: str) -> str:
    return subprocess.check_output([path, "--version"], text=True).splitlines()[0]


def command_version(command: str) -> str:
    return subprocess.check_output([command, "--version"], text=True).splitlines()[0]


def git_output(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(["git", "-C", str(cwd), *args], text=True).strip()


def archived_blob(commit: str, relative: str) -> bytes:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), "show", f"{commit}:{relative}"]
    )


def lock_value(lock: bytes, name: str) -> str:
    prefix = f"{name}="
    for line in lock.decode().splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix)
    fail(f"archived SDK lock is missing {name}")
    raise AssertionError


def verify_source_tree(source_tree: Path, data: dict[str, object]) -> None:
    commit = data.get("source_commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        fail("artifact attestation requires a full source_commit")
    manifest_name = safe_relative_path(data.get("source_manifest"), "source manifest")
    manifest_bytes = archived_blob(commit, manifest_name)
    if sha256_bytes(manifest_bytes) != data.get("source_manifest_sha256"):
        fail("archived source manifest SHA-256 mismatch")
    for line_number, line in enumerate(manifest_bytes.decode().splitlines(), 1):
        try:
            expected, member_name = line.split("  ", 1)
        except ValueError as error:
            fail(f"archived manifest line {line_number}: invalid syntax")
            raise AssertionError from error
        safe_relative_path(member_name, f"source manifest member {line_number}")
        member = source_tree / member_name
        if not member.is_file() or member.is_symlink():
            fail(f"source tree member is missing or unsafe: {member_name}")
        if sha256_bytes(member.read_bytes()) != expected:
            fail(f"source tree member mismatch: {member_name}")


def actual_build_definitions(build: Path, expected: object) -> dict[str, int]:
    if not isinstance(expected, dict) or not expected:
        fail("artifact attestation build_definitions must be a non-empty object")
    compile_db = json.loads((build / "compile_commands.json").read_text())
    source_entry = next(
        (entry for entry in compile_db if entry["file"].endswith(SOURCE_SUFFIX)),
        None,
    )
    if source_entry is None:
        fail("probe source compile command is missing")
    command = source_entry.get("command")
    arguments = shlex.split(command) if isinstance(command, str) else source_entry["arguments"]
    definitions = {
        token[2:].split("=", 1)[0]: token[2:].split("=", 1)[1]
        for token in arguments
        if token.startswith("-D") and "=" in token
    }
    actual: dict[str, int] = {}
    for name, declared in expected.items():
        value = definitions.get(name)
        if value is None or str(declared) != value:
            fail(f"build definition mismatch: {name}")
        actual[name] = int(value, 0)
    return actual


def sdk_build_version(build: Path) -> str:
    header = build / "build_tmp/generated/include/hpm_sdk_version.h"
    match = re.search(
        r"^#define BUILD_VERSION\s+(\S+)$",
        header.read_text(),
        re.MULTILINE,
    )
    if match is None:
        fail("SDK BUILD_VERSION is missing")
    return match.group(1)


def canonical_compile_commands_sha256(
    compile_db: Path,
    source_tree: Path,
    build: Path,
    sdk_base: Path,
) -> str:
    text = compile_db.read_text()
    replacements = (
        (str(source_tree), "${SOURCE_TREE}"),
        (str(build.resolve()), "${BUILD}"),
        (str(sdk_base), "${HPM_SDK_BASE}"),
    )
    for absolute, replacement in sorted(
        replacements, key=lambda item: len(item[0]), reverse=True
    ):
        text = text.replace(absolute, replacement)
    return sha256_bytes(text.encode())


def write_member(archive: zipfile.ZipFile, name: str, payload: bytes) -> None:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_STORED
    info.flag_bits = 0
    info.internal_attr = 0
    info.external_attr = 0o100644 << 16
    info.extra = b""
    info.comment = b""
    archive.writestr(info, payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("attestation", type=Path)
    parser.add_argument("--source-tree", required=True, type=Path)
    args = parser.parse_args()

    attestation_path = args.attestation.resolve()
    data = json.loads(attestation_path.read_text())
    package = repository_output(data.get("artifact_package"), "artifact package")
    artifact_name = safe_relative_path(data.get("artifact"), "artifact member")
    source_tree = args.source_tree.resolve(strict=True)
    verify_source_tree(source_tree, data)

    build = ROOT / "build/review-mcan-tx"
    elf = build / "output/demo.elf"
    elf_bytes = elf.read_bytes()
    if not elf_bytes or len(elf_bytes) > MAX_ELF_BYTES:
        fail("ELF size is outside the package limit")

    cache = cache_values(build)
    expected_home = source_tree / "tools/phase0/mcan0_external_probe"
    if Path(cache.get("CMAKE_HOME_DIRECTORY", "")).resolve() != expected_home:
        fail("build source directory does not match --source-tree")
    if cache.get("HPM_BUILD_TYPE") != "flash_xip":
        fail("build type mismatch")
    if cache.get("BOARD") != "hpm5321_custom":
        fail("board mismatch")

    actual_definitions = actual_build_definitions(build, data.get("build_definitions"))
    actual_sdk_version = sdk_build_version(build)
    if actual_sdk_version != data.get("sdk_build_version"):
        fail("SDK BUILD_VERSION mismatch")

    sdk_base_value = os.environ.get("HPM_SDK_BASE")
    if not sdk_base_value:
        fail("HPM_SDK_BASE is required to package the artifact")
    sdk_base = Path(sdk_base_value).resolve(strict=True)
    sdk_commit = git_output("rev-parse", "HEAD", cwd=sdk_base)
    locked_sdk_commit = lock_value(
        archived_blob(data["source_commit"], "dependencies/hpm-sdk.lock"),
        "current_build_commit",
    )
    if sdk_commit != locked_sdk_commit or sdk_commit != data.get("sdk_commit"):
        fail("SDK commit mismatch")
    if git_output("status", "--porcelain", "--untracked-files=all", cwd=sdk_base):
        fail("SDK worktree must be clean")

    compiler = cache.get("CMAKE_C_COMPILER", "")
    linker = cache.get("CMAKE_LINKER", "")
    objcopy = cache.get("CMAKE_OBJCOPY", "")
    if not all((compiler, linker, objcopy)):
        fail("build tool path is missing from CMakeCache.txt")
    compile_db = build / "compile_commands.json"

    package_manifest = {
        "schema": 2,
        "artifact": artifact_name,
        "elf_sha256": sha256_bytes(elf_bytes),
        "elf_size": len(elf_bytes),
        "source_commit": data["source_commit"],
        "source_dirty": False,
        "source_manifest_sha256": data["source_manifest_sha256"],
        "sdk_commit": sdk_commit,
        "sdk_dirty": False,
        "sdk_build_version": actual_sdk_version,
        "compiler": tool_version(compiler),
        "linker": tool_version(linker),
        "objcopy": tool_version(objcopy),
        "cmake": command_version("cmake"),
        "ninja": command_version("ninja"),
        "compile_commands_sha256": canonical_compile_commands_sha256(
            compile_db,
            source_tree,
            build,
            sdk_base,
        ),
        "compile_commands_hash_mode": "paths-normalized-v1",
        "build": {
            "board": cache["BOARD"],
            "hpm_build_type": cache["HPM_BUILD_TYPE"],
            "definitions": actual_definitions,
        },
        "result_abi_version": data["result_abi_version"],
    }
    manifest_bytes = (
        json.dumps(package_manifest, indent=2, sort_keys=True) + "\n"
    ).encode()

    package.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=package.parent,
        prefix=f".{package.name}.",
        delete=False,
    ) as stream:
        temporary_package = Path(stream.name)
    try:
        with zipfile.ZipFile(temporary_package, "w") as archive:
            archive.comment = b""
            write_member(archive, "package-manifest.json", manifest_bytes)
            write_member(archive, artifact_name, elf_bytes)
        temporary_package.replace(package)
    finally:
        temporary_package.unlink(missing_ok=True)

    print(
        f"PACKAGE path={package.relative_to(ROOT)} "
        f"sha256={sha256_bytes(package.read_bytes())} "
        f"elf_sha256={package_manifest['elf_sha256']}"
    )


if __name__ == "__main__":
    main()
