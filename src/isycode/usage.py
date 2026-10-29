"""Pure, conservative accounting for provider-reported session tokens.

These counters describe consumption, never authority or a billing guarantee.
Missing usage leaves totals as lower bounds; a budget stops subsequent requests.
"""

from dataclasses import dataclass


MAX_COUNTER = 10**12
_STATE_FIELDS = frozenset({"requests", "input_tokens", "output_tokens", "unknown_requests"})


@dataclass(frozen=True)
class CostBucket:
    """Display-only cost classification; absence of pricing stays unknown."""

    status: str
    usd: float | None = None
    source: str = ""

    @classmethod
    def unknown(cls) -> "CostBucket":
        return cls("unknown")

    @classmethod
    def included(cls, source: str) -> "CostBucket":
        if not isinstance(source, str) or not source.strip():
            raise ValueError("included cost source is required")
        return cls("included", source=source.strip())

    @classmethod
    def estimated(cls, usd: float, *, source: str) -> "CostBucket":
        if (type(usd) not in {int, float} or usd < 0
                or not isinstance(source, str) or not source.strip()):
            raise ValueError("estimated cost requires a nonnegative amount and source")
        return cls("estimated", float(usd), source.strip())

    def to_state(self) -> dict:
        if self.status == "unknown":
            return {"status": "unknown"}
        if self.status == "included":
            return {"status": "included", "source": self.source}
        if self.status == "estimated" and self.usd is not None:
            return {"status": "estimated", "usd": self.usd, "source": self.source}
        raise ValueError("invalid cost bucket")


def _valid_counter(value: object) -> bool:
    return type(value) is int and 0 <= value <= MAX_COUNTER


def _validate_budget(budget: int) -> None:
    if not _valid_counter(budget):
        raise ValueError("Token budget must be an integer between 0 and 1000000000000")


@dataclass
class UsageLedger:
    """Bounded reported counters; unknown responses prevent budget enforcement."""

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    unknown_requests: int = 0

    def __post_init__(self) -> None:
        if not all(_valid_counter(getattr(self, name)) for name in _STATE_FIELDS):
            raise ValueError("Usage counters must be bounded nonnegative integers")
        if self.unknown_requests > self.requests:
            raise ValueError("Unknown requests cannot exceed total requests")

    @classmethod
    def from_state(cls, value: object) -> "UsageLedger":
        """Validate untrusted portable state without accepting additional fields."""
        if not isinstance(value, dict) or set(value) != _STATE_FIELDS:
            raise ValueError("Usage state must contain exactly the four usage counters")
        return cls(**value)

    def to_state(self) -> dict:
        return {name: getattr(self, name) for name in (
            "requests", "input_tokens", "output_tokens", "unknown_requests"
        )}

    def record(self, usage: dict | None) -> None:
        """Count one response, retaining only valid reported counters.

        Partial or malformed pairs are unknown even when one counter is valid.
        Saturation also makes totals lower bounds and blocks a configured budget.
        """
        unknown = self.requests == MAX_COUNTER
        self.requests = min(MAX_COUNTER, self.requests + 1)
        if not isinstance(usage, dict):
            usage = {}
        cache_fields = ("cache_read_input_tokens", "cache_creation_input_tokens")
        if any(field in usage for field in ("input_tokens", "output_tokens", *cache_fields)):
            counters = [("input_tokens", usage.get("input_tokens")),
                        ("output_tokens", usage.get("output_tokens"))]
            # Anthropic reports cache reads/writes separately from ordinary
            # input_tokens. Absent optional counters are zero, present invalid
            # counters make consumption unknown rather than silently free.
            counters.extend(("input_tokens", usage[field]) for field in cache_fields if field in usage)
        else:
            # OpenAI cached_tokens is already included in prompt_tokens.
            counters = [("input_tokens", usage.get("prompt_tokens")),
                        ("output_tokens", usage.get("completion_tokens"))]
        for name, value in counters:
            if not _valid_counter(value):
                unknown = True
                continue
            total = getattr(self, name) + value
            if total > MAX_COUNTER:
                unknown = True
            setattr(self, name, min(MAX_COUNTER, total))
        if unknown:
            self.unknown_requests = min(MAX_COUNTER, self.unknown_requests + 1)

    def allowed(self, budget: int = 0) -> bool:
        """Whether another request may begin under the optional session budget."""
        _validate_budget(budget)
        return budget == 0 or (
            self.unknown_requests == 0 and self.input_tokens + self.output_tokens < budget
        )

    def remaining(self, budget: int = 0) -> int | None:
        """Remaining reported-token budget; unknown usage may consume more."""
        _validate_budget(budget)
        if budget == 0:
            return None
        return max(0, budget - self.input_tokens - self.output_tokens)

    def label(self) -> str:
        """Describe reported usage without inventing monetary prices."""
        total = self.input_tokens + self.output_tokens
        tokens = f"{self.input_tokens} input, {self.output_tokens} output"
        requests = f"{self.requests} requests"
        if self.requests == MAX_COUNTER:
            requests = "at least " + requests
        if self.unknown_requests:
            return (f"At least {total} reported tokens ({tokens}); "
                    f"{requests}, {self.unknown_requests} with unknown usage")
        return f"{total} reported tokens ({tokens}); {requests}"
