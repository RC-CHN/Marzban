from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any

from app.core.singbox.config import config_hash, stable_json
from app.db.models import SingBoxNode
from config import SINGBOX_EXECUTABLE_PATH


def write_config_if_changed(config_path: str | Path, config: dict[str, Any]) -> tuple[bool, str]:
    """Write config only when content changed.

    Returns `(changed, hash)`.
    """

    path = Path(config_path)
    new_hash = config_hash(config)
    new_content = stable_json(config) + "\n"
    if path.exists() and path.read_text() == new_content:
        return False, new_hash
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_content)
    return True, new_hash


def check_config(config_path: str | Path, executable_path: str = SINGBOX_EXECUTABLE_PATH) -> str:
    result = subprocess.run(
        [executable_path, "check", "-c", str(config_path)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout.strip() or "sing-box check failed")
    return result.stdout.strip()


def deploy_node_config(
    node: SingBoxNode,
    config: dict[str, Any],
    *,
    apply: bool = False,
    executable_path: str = SINGBOX_EXECUTABLE_PATH,
) -> tuple[bool, str]:
    """Check and optionally apply a generated node config.

    Returns `(applied, output)`. Manual deployments intentionally do not write
    files; they only return the generated config hash to the caller.
    """

    if node.deploy_method == "manual":
        return False, "manual deployment: config generated but not applied"
    if node.deploy_method == "local":
        return _deploy_local(node, config, apply=apply, executable_path=executable_path)
    if node.deploy_method == "ssh":
        return _deploy_ssh(node, config, apply=apply)
    raise ValueError(f"Unsupported deploy method: {node.deploy_method}")


def _deploy_local(
    node: SingBoxNode,
    config: dict[str, Any],
    *,
    apply: bool,
    executable_path: str,
) -> tuple[bool, str]:
    config_path = Path(node.config_path)
    next_path = config_path.with_name(config_path.name + ".next")
    previous_path = config_path.with_name(config_path.name + ".prev")
    _, hash_value = write_config_if_changed(next_path, config)
    check_output = check_config(next_path, executable_path=executable_path)
    if not apply:
        return False, f"checked {next_path} hash={hash_value}\n{check_output}".strip()

    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        previous_path.write_text(config_path.read_text())
    config_path.write_text(next_path.read_text())
    restart_output = _run_shell(node.restart_command or "systemctl restart sing-box")
    return True, f"applied {config_path} hash={hash_value}\n{check_output}\n{restart_output}".strip()


def _deploy_ssh(node: SingBoxNode, config: dict[str, Any], *, apply: bool) -> tuple[bool, str]:
    if not node.ssh_host or not node.ssh_user:
        raise ValueError("ssh_host and ssh_user are required for SSH deployment")
    port = node.ssh_port or 22
    config_path = node.config_path
    next_path = f"{config_path}.next"
    previous_path = f"{config_path}.prev"
    target = f"{node.ssh_user}@{node.ssh_host}"
    payload = stable_json(config) + "\n"

    mkdir_cmd = f"mkdir -p {shlex.quote(str(Path(config_path).parent))}"
    _run(["ssh", "-p", str(port), target, mkdir_cmd], stdin=None)
    _run(["ssh", "-p", str(port), target, f"cat > {shlex.quote(next_path)}"], stdin=payload)
    check_output = _run(
        ["ssh", "-p", str(port), target, f"sing-box check -c {shlex.quote(next_path)}"],
        stdin=None,
    )
    if not apply:
        return False, check_output.strip()

    apply_cmd = (
        f"if [ -f {shlex.quote(config_path)} ]; then "
        f"cp {shlex.quote(config_path)} {shlex.quote(previous_path)}; fi; "
        f"mv {shlex.quote(next_path)} {shlex.quote(config_path)}; "
        f"{node.restart_command or 'systemctl restart sing-box'}"
    )
    restart_output = _run(["ssh", "-p", str(port), target, apply_cmd], stdin=None)
    return True, f"{check_output}\n{restart_output}".strip()


def _run(cmd: list[str], stdin: str | None) -> str:
    result = subprocess.run(
        cmd,
        input=stdin,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout.strip() or f"Command failed: {cmd[0]}")
    return result.stdout.strip()


def _run_shell(cmd: str) -> str:
    result = subprocess.run(
        cmd,
        shell=True,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout.strip() or "restart command failed")
    return result.stdout.strip()
