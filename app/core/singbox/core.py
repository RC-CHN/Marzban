from __future__ import annotations

import atexit
import subprocess
import threading
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.core.runtime import CoreRuntime
from app.core.singbox.config import stable_json


class SingBoxCore(CoreRuntime):
    """Process manager for a local sing-box core."""

    def __init__(
        self,
        executable_path: str = "/usr/local/bin/sing-box",
        config_path: str = "/tmp/sing-box-config.json",
        work_dir: str | None = None,
    ) -> None:
        self.executable_path = executable_path
        self.config_path = Path(config_path)
        self.work_dir = Path(work_dir) if work_dir else None
        self.process: subprocess.Popen[str] | None = None
        self._logs = deque(maxlen=300)
        self._temp_log_buffers: dict[int, deque[str]] = {}
        atexit.register(self.stop)

    def get_version(self) -> str | None:
        output = subprocess.check_output(
            [self.executable_path, "version"],
            stderr=subprocess.STDOUT,
            text=True,
        )
        first_line = output.splitlines()[0] if output else ""
        return first_line.removeprefix("sing-box version ").strip() or None

    @property
    def started(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, config: dict[str, Any]) -> None:
        if self.started:
            raise RuntimeError("sing-box is already started")

        self._write_config(config)
        cmd = [self.executable_path, "run", "-c", str(self.config_path)]
        self.process = subprocess.Popen(
            cmd,
            cwd=str(self.work_dir) if self.work_dir else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self._capture_logs()

    def stop(self) -> None:
        if not self.started:
            return
        assert self.process is not None
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=10)
        finally:
            self.process = None

    def restart(self, config: dict[str, Any]) -> None:
        self.stop()
        self.start(config)

    @contextmanager
    def get_logs(self) -> Iterator[deque[str]]:
        buf = deque(self._logs, maxlen=300)
        buf_id = id(buf)
        try:
            self._temp_log_buffers[buf_id] = buf
            yield buf
        finally:
            self._temp_log_buffers.pop(buf_id, None)

    def _write_config(self, config: dict[str, Any]) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(stable_json(config))

    def _capture_logs(self) -> None:
        def capture() -> None:
            while self.process and self.process.stdout:
                line = self.process.stdout.readline()
                if not line:
                    if self.process.poll() is not None:
                        break
                    continue
                line = line.rstrip()
                self._logs.append(line)
                for buf in list(self._temp_log_buffers.values()):
                    buf.append(line)

        threading.Thread(target=capture, daemon=True).start()
