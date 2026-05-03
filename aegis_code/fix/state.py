from __future__ import annotations


class FixLoopState:
    def __init__(self) -> None:
        self.seen_signatures: set[str] = set()
        self.previous_signature: str | None = None

    def record_before_apply(self, signature: str) -> None:
        value = str(signature or "").strip()
        self.previous_signature = value
        if value:
            self.seen_signatures.add(value)

    def repeated_after_apply(self, signature: str) -> bool:
        value = str(signature or "").strip()
        if not value:
            return False
        if self.previous_signature and value == self.previous_signature:
            return True
        if value in self.seen_signatures:
            return True
        self.seen_signatures.add(value)
        return False

