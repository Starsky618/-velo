"""路线发布脚本的失败传播门。"""

from pathlib import Path
import subprocess


def test_remote_route_publish_uses_bash_pipefail_and_propagates_import_failure():
    script = Path("scripts/publish_routes.sh").read_text(encoding="utf-8")
    assert "'bash -seuo pipefail' <<'REMOTE_PUBLISH'" in script

    probe = subprocess.run(
        ["bash", "-seuo", "pipefail"],
        input="(exit 23) 2>&1 | tail -2\n",
        text=True,
        capture_output=True,
        check=False,
    )
    assert probe.returncode == 23
