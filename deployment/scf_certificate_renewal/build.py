#!/usr/bin/env python3
"""Reproducible renewal-function ZIP from one reviewed Git commit, no credentials."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile

SOURCE = "deployment/scf_certificate_renewal/handler.py"


def git(repo, *arguments):
    return subprocess.run(["git", "-C", str(repo), *arguments], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def build(repo, revision, output):
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision):
        raise ValueError("revision must be a full lowercase commit hash")
    if git(repo, "rev-parse", "--verify", revision + "^{commit}").decode().strip() != revision:
        raise ValueError("revision does not identify the requested commit")
    listing = git(repo, "ls-tree", revision, "--", SOURCE).decode()
    if not listing.startswith("100644 blob ") and not listing.startswith("100755 blob "):
        raise ValueError("committed handler must be a regular file")
    handler = git(repo, "show", revision + ":" + SOURCE)
    manifest = {
        "source_revision": revision,
        "entry_point": "handler.main_handler",
        "runtime": "Python 3.10+",
        "files": [{"path": "handler.py", "bytes": len(handler), "sha256": hashlib.sha256(handler).hexdigest()}],
    }
    manifest_bytes = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    output = Path(output)
    sidecar = output.with_suffix(output.suffix + ".manifest.json")
    if output.exists() or sidecar.exists():
        raise ValueError("output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_STORED) as archive:
        for name, content in sorted({"handler.py": handler, "deployment-manifest.json": manifest_bytes}.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    report = {**manifest, "zip_sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "zip_bytes": output.stat().st_size}
    sidecar.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = build(args.repo, args.revision, args.output)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Build failed: {error}\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
