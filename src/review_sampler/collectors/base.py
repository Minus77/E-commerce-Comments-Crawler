from typing import Protocol


class TaskCancelled(Exception):
    """Raised when a collector observes a user cancellation."""


class VerificationRequired(Exception):
    """Raised when a collector cannot continue without a person."""

    def __init__(self, message: str, kind: str = "verification"):
        super().__init__(message)
        self.kind = kind
        self.message = message


class BrowserUnavailable(Exception):
    """Raised when the local browser channel cannot start."""


class Collector(Protocol):
    def collect(self, task: dict, runtime) -> None: ...
