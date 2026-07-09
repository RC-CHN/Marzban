#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_CONFIG = Path("/tmp/singbox-runtime-smoke-active.json")
FIRST_CONFIG = ROOT / "generated" / "node-a" / "config.json"
SECOND_CONFIG = ROOT / "generated" / "node-a" / "config-exit-node-c.json"


def wait_for_start(process: subprocess.Popen[str]) -> None:
    deadline = time.time() + 5
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"sing-box exited early with code {process.returncode}")
        time.sleep(0.2)


def start(config: Path) -> subprocess.Popen[str]:
    ACTIVE_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(config, ACTIVE_CONFIG)
    process = subprocess.Popen(
        ["sing-box", "run", "-c", str(ACTIVE_CONFIG)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    wait_for_start(process)
    return process


def stop(process: subprocess.Popen[str]) -> str:
    process.terminate()
    try:
        output, _ = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        output, _ = process.communicate(timeout=10)
    return output


def main() -> int:
    process = start(FIRST_CONFIG)
    first_logs = stop(process)
    if "sing-box started" not in first_logs:
        print(first_logs)
        raise RuntimeError("first start did not emit expected startup log")

    process = start(SECOND_CONFIG)
    second_logs = stop(process)
    if "sing-box started" not in second_logs:
        print(second_logs)
        raise RuntimeError("restart config did not emit expected startup log")

    print("runtime smoke passed: start/logs/restart/stop")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"runtime smoke failed: {exc}", file=sys.stderr)
        raise
