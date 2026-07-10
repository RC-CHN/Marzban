import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from app.models.singbox import (
    SINGBOX_NODE_MESSAGE_MAX_LENGTH,
    SingBoxNodeSyncAppliedRequest,
    SingBoxNodeSyncRequest,
)


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_PATH = ROOT / "scripts" / "singbox-bootstrap.sh"


def _sync_agent_definitions() -> str:
    source = BOOTSTRAP_PATH.read_text()
    marker = "cat >\"$tmp_path\" <<'SYNC_AGENT'\n"
    agent = source.split(marker, 1)[1].split("\nSYNC_AGENT\n", 1)[0]
    return agent.rsplit('\nmain "$@"', 1)[0]


class SingBoxNodeSyncPayloadTest(unittest.TestCase):
    def test_sync_payloads_truncate_legacy_agent_messages_before_validation(self):
        message = "upgrade-start\n" + ("x" * 4096) + "\nupgrade-finished"
        payloads = (
            SingBoxNodeSyncRequest(token="t" * 32, message=message),
            SingBoxNodeSyncAppliedRequest(
                token="t" * 32,
                config_hash="a" * 64,
                message=message,
            ),
        )

        for payload in payloads:
            with self.subTest(payload=type(payload).__name__):
                self.assertEqual(len(payload.message), SINGBOX_NODE_MESSAGE_MAX_LENGTH)
                self.assertTrue(payload.message.startswith("[truncated]\n"))
                self.assertTrue(payload.message.endswith("upgrade-finished"))


class SingBoxSyncAgentTest(unittest.TestCase):
    def _run_agent_functions(self, body: str, **environment: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(environment)
        env.setdefault("PANEL_URL", "https://panel.example")
        script = _sync_agent_definitions() + "\n" + body
        with tempfile.NamedTemporaryFile() as sync_env:
            env["SYNC_ENV_PATH"] = sync_env.name
            return subprocess.run(
                ["bash"],
                input=script,
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )

    def test_agent_summarizes_long_reports(self):
        message = "begin-" + ("x" * 2000) + "-finished"

        result = self._run_agent_functions('summarize_message "$MESSAGE"', MESSAGE=message)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout), 900)
        self.assertTrue(result.stdout.startswith("begin-"))
        self.assertIn("...[truncated]...", result.stdout)
        self.assertTrue(result.stdout.endswith("-finished"))

    def test_agent_exposes_http_error_and_keeps_report_failure_best_effort(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            capture_path = Path(temp_dir) / "request.json"
            installed_agent_path = Path(temp_dir) / "installed-agent.sh"
            installed_agent_path.write_text('#!/usr/bin/env bash\nSYNC_AGENT_VERSION="0.9.5"\n')
            body = r'''
sing_box_version() { printf '%s\n' "sing-box version test"; }
container_image() { printf '%s\n' "ghcr.io/rc-chn/marzban:v0.9.5"; }
curl() {
  local output_path="" request_path=""
  while [ "$#" -gt 0 ]; do
    case "$1" in
      -o)
        output_path="$2"
        shift 2
        ;;
      --data-binary)
        request_path="${2#@}"
        shift 2
        ;;
      *)
        shift
        ;;
    esac
  done
  cp "$request_path" "$CAPTURE_PATH"
  printf '%s' '{"detail":"message validation failed"}' >"$output_path"
  printf '%s' '422'
}
report_applied_or_warn "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" true "$MESSAGE"
'''
            result = self._run_agent_functions(
                body,
                CAPTURE_PATH=str(capture_path),
                MESSAGE="pull-output-" + ("x" * 3000) + "-upgrade-finished",
                NODE_SYNC_TOKEN="t" * 32,
                PANEL_URL="https://panel.example",
                RUNTIME="docker",
                SYNC_SCRIPT_PATH=str(installed_agent_path),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("HTTP 422", result.stderr)
            self.assertIn("message validation failed", result.stderr)
            self.assertIn("next heartbeat will reconcile", result.stdout)
            request = json.loads(capture_path.read_text())
            self.assertLessEqual(len(request["message"]), 900)
            self.assertEqual(request["sync_agent_version"], "0.9.5")


if __name__ == "__main__":
    unittest.main()
