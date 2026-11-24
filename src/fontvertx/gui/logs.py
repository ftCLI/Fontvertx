"""Structured conversion log records kept in memory by the GUI."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from fontvertx.models import FontOutcome

LogLevel = Literal["INFO", "WARNING", "ERROR"]


@dataclass(frozen=True)
class LogEntry:
    timestamp: str
    level: LogLevel
    event: str
    message: str
    context: dict[str, object] = field(default_factory=dict)
    outcome: FontOutcome | None = field(default=None, repr=False, compare=False)

    @classmethod
    def create(
        cls,
        level: LogLevel,
        event: str,
        message: str,
        context: dict[str, object] | None = None,
        *,
        outcome: FontOutcome | None = None,
    ) -> "LogEntry":
        return cls(
            datetime.now().astimezone().isoformat(timespec="milliseconds"),
            level,
            event,
            message,
            context or {},
            outcome,
        )

    def display_text(self) -> str:
        input_name = self.context.get("input")
        input_label = f" [{input_name}]" if isinstance(input_name, str) else ""
        return f"{self.timestamp} {self.level} [{self.event}]{input_label} {self.message}"

    def to_json(self) -> str:
        return json.dumps(
            {
                "timestamp": self.timestamp,
                "level": self.level,
                "event": self.event,
                "message": self.message,
                "context": self.context,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
