from __future__ import annotations


class ScriptType(str):
    """string payload that keeps legacy `.script` access available."""

    def __new__(cls, value: str | None = ""):
        return super().__new__(cls, "" if value is None else str(value))

    @property
    def script(self) -> str:
        return str(self)
