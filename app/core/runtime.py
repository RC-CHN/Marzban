from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


class CoreRuntime(ABC):
    """Minimal runtime contract for a managed proxy core."""

    @abstractmethod
    def get_version(self) -> str | None:
        raise NotImplementedError

    @property
    @abstractmethod
    def started(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def start(self, config: dict[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def restart(self, config: dict[str, Any]) -> None:
        raise NotImplementedError

    @contextmanager
    def get_logs(self) -> Iterator[list[str]]:
        yield []
