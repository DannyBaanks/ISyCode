"""Readable, lossless references for long terminal pastes."""
import re

class PastedText:
    def __init__(self):
        self.items: dict[str, str] = {}

    def capture(self, text: str) -> str:
        if len(text) < 800:
            return text
        preview = " ".join(text.split())[:20].replace('"', "'").replace("[", "(").replace("]", ")")
        base = '["' + preview + '…"]'
        label = base
        sequence = 2
        while label in self.items and self.items[label] != text:
            label = base[:-1] + f" #{sequence}]"
            sequence += 1
        self.items[label] = text
        return label

    def expand(self, draft: str) -> str:
        # One pass: pasted content must never expand another stored reference.
        if not self.items:
            return draft
        pattern = "|".join(re.escape(label) for label in sorted(self.items, key=len, reverse=True))
        return re.sub(pattern, lambda match: self.items[match.group()], draft)
