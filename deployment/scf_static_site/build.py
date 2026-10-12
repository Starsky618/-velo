#!/usr/bin/env python3
"""Build an immutable, byte-reproducible SCF ZIP from an explicit Git commit."""

import argparse
import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile

HANDLER_SOURCE = "deployment/scf_static_site/handler.py"
ALLOWED_SUFFIXES = {".html", ".css", ".js", ".json", ".txt", ".md", ".xml", ".svg", ".jpg", ".jpeg", ".png", ".woff", ".woff2", ".ico", ".webp"}
TEXT_SUFFIXES = {".html", ".css", ".js", ".json", ".txt", ".md", ".xml", ".svg"}
# Decimal MB is deliberately conservative where provider docs only say MB.
MAX_RESPONSE_BYTES = 6_000_000
MAX_ZIP_BYTES = 50_000_000
MAX_UNPACKED_BYTES = 500_000_000
RESPONSE_HEADER_RESERVE = 4096


def _git(repo, *arguments):
    return subprocess.run(
        ["git", "-C", str(repo), *arguments], check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout


def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, indent=2) + "\n").encode("ascii")


def _response_size(path, content):
    base64_size = 4 * ((len(content) + 2) // 3)
    text_size = 0
    if PurePosixPath(path).suffix.lower() in TEXT_SUFFIXES:
        text_size = len(json.dumps(content.decode("utf-8"), ensure_ascii=True).encode("ascii"))
    # Include JSON escaping, Base64 expansion and a full header allowance.
    return max(base64_size, text_size) + RESPONSE_HEADER_RESERVE


def build(repo, revision, output):
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision):
        raise ValueError("--revision must be a full lowercase Git commit hash")
    resolved = _git(repo, "rev-parse", "--verify", revision + "^{commit}").decode().strip()
    if resolved != revision:
        raise ValueError("revision is not the requested commit")
    entries = _git(repo, "ls-tree", "-rz", revision, "--", "website", HANDLER_SOURCE)
    payloads = {}
    largest_response = {"path": "", "bytes_upper_bound": 0}
    for entry in entries.split(b"\0"):
        if not entry:
            continue
        attributes, raw_path = entry.split(b"\t", 1)
        mode, kind, object_id = attributes.decode("ascii").split()
        path = raw_path.decode("utf-8")
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ValueError(f"refusing symlink/submodule/non-regular entry: {path}")
        if path == HANDLER_SOURCE:
            archive_name = "handler.py"
        else:
            parts = PurePosixPath(path).parts
            if (len(parts) < 2 or parts[0] != "website"
                    or any(part.startswith(".") for part in parts)
                    or any(part.lower() in {"uploads", "backups", "node_modules", "__pycache__"} for part in parts)
                    or PurePosixPath(path).suffix.lower() not in ALLOWED_SUFFIXES
                    or any(ord(c) < 32 or c in "\\%?#" for c in path)):
                raise ValueError(f"refusing non-public website entry: {path}")
            archive_name = path
        content = _git(repo, "cat-file", "blob", object_id)
        payloads[archive_name] = content
        if archive_name.startswith("website/"):
            response_size = _response_size(archive_name, content)
            if response_size >= MAX_RESPONSE_BYTES:
                raise ValueError(f"response exceeds SCF 6 MB limit: {path} ({response_size})")
            if response_size > largest_response["bytes_upper_bound"]:
                largest_response = {"path": path, "bytes_upper_bound": response_size}
    required = {"handler.py", "website/index.html", "website/404.html"}
    if not required <= payloads.keys():
        raise ValueError(f"commit is missing required deployment files: {sorted(required - payloads.keys())}")
    manifest = {
        "schema_version": 1,
        "source_revision": revision,
        "source_commit_timestamp": int(_git(repo, "show", "-s", "--format=%ct", revision)),
        "entry_point": "handler.main_handler",
        "runtime": "Python 3.10+",
        "zip_format": "ZIP_STORED; fixed 1980-01-01 UTC metadata; sorted paths; mode 0644",
        "largest_response": largest_response,
        "files": [{"path": name, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
                  for name, content in sorted(payloads.items())],
    }
    embedded_manifest = _json_bytes(manifest)
    payloads["deployment-manifest.json"] = embedded_manifest
    unpacked_bytes = sum(map(len, payloads.values()))
    if unpacked_bytes >= MAX_UNPACKED_BYTES:
        raise ValueError("unpacked package exceeds SCF 500 MB limit")
    output = Path(output)
    if output.exists() or output.with_suffix(output.suffix + ".manifest.json").exists():
        raise ValueError("output or sidecar already exists; choose a new output path")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
        for name, content in sorted(payloads.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, content)
    zip_bytes = output.stat().st_size
    if zip_bytes >= MAX_ZIP_BYTES:
        output.unlink()
        raise ValueError("ZIP exceeds SCF online-upload 50 MB limit")
    report = {
        **manifest,
        "zip_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "zip_bytes": zip_bytes,
        "unpacked_bytes": unpacked_bytes,
        "embedded_manifest_sha256": hashlib.sha256(embedded_manifest).hexdigest(),
    }
    output.with_suffix(output.suffix + ".manifest.json").write_bytes(_json_bytes(report))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--revision", required=True, help="reviewed full Git commit hash (no HEAD or branch names)")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = build(args.repo, args.revision, args.output)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Build failed: {error}\n")
    print(json.dumps({key: report[key] for key in (
        "source_revision", "zip_sha256", "zip_bytes", "unpacked_bytes", "largest_response",
    )}, indent=2))


if __name__ == "__main__":
    main()
