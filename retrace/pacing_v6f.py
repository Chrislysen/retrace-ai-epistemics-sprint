"""Conservative local admission policy; this is not a verified vendor quota.

No clocks, network calls, waits, retries or filesystem access are performed.
Callers supply monotonic seconds and hold one shared lock across admission,
budget reservation and dispatch. Existing global/per-model3.1s spacing and
the initial61s previous-run cooldown remain the runner's responsibility.
"""
from __future__ import annotations

import json
import math

WINDOW_SECONDS = 61.0
TOKEN_BUDGET = 100_000
MAX_STARTS = 10
SOLO_LIMIT = 125_000
ENCODING = "cl100k_base"


def _weight(value):
    if type(value) is not int or not 1 <= value <= SOLO_LIMIT:
        raise ValueError("Admission weight must be an integer from1 through125000; larger requests must not be reserved or issued")
    return value


def _time(value):
    if type(value) not in (int, float):
        raise ValueError("Time must be finite monotonic seconds")
    try:
        result = float(value)
    except (OverflowError, ValueError):
        raise ValueError("Time must be finite monotonic seconds") from None
    if not math.isfinite(result) or not math.isfinite(result + WINDOW_SECONDS) or result + WINDOW_SECONDS <= result:
        raise ValueError("Time must be finite and precise enough for a61-second window")
    return result


class AdmissionDenied(ValueError):
    """A start was attempted before its deterministic admission time."""
    def __init__(self, delay_seconds):
        self.delay_seconds = delay_seconds
        super().__init__(f"Request is not admissible yet; wait at least{delay_seconds:.9g} seconds and recheck")


class AdmissionWindow:
    """Caller-clock sliding window with a separately bounded solo class.

    Normal requests have weight<=100000. Every half-open window(t-61,t]
    admits at most100000 total normal weight and10 request starts. A single
    request of weight100001..125000 is allowed only61s after every prior start
    and blocks every subsequent start for61s. Empty new state has no hidden
    initial delay; the runner enforces the previous-run cooldown.

    delay() never consumes an admission, but advances a monotonic observation
    watermark so a caller cannot move its clock backwards. record() rejects an
    early admission rather than silently accumulating an over-budget start.
    Both use caller-supplied time; neither waits. This class is not thread-safe.
    """
    def __init__(self):
        self._records = []
        self._last_observed = None

    @property
    def records(self):
        """Immutable copy of all starts recorded in this instance."""
        return tuple(self._records)

    def _observe(self, now):
        now = _time(now)
        if self._last_observed is not None and now < self._last_observed:
            raise ValueError("Monotonic clock moved backwards")
        self._last_observed = now
        return now

    def _active(self, now):
        # An admission exactly61s old has expired. Adding to the recorded time
        # avoids subtractive boundary drift in the window-membership predicate.
        return [(started, weight) for started, weight in self._records if now < started + WINDOW_SECONDS]

    def _delay(self, now, weight):
        active = self._active(now)
        if not active:
            return 0.0
        if weight > TOKEN_BUDGET:
            return max(0.0, active[-1][0] + WINDOW_SECONDS - now)
        total = sum(value for _, value in active)
        if len(active) < MAX_STARTS and total + weight <= TOKEN_BUDGET:
            return 0.0
        # Evaluate every distinct release boundary; the first fitting state is
        # the earliest admissible one. Solo weight naturally blocks all normals.
        for release in sorted({started + WINDOW_SECONDS for started, _ in active}):
            remaining = [(started, value) for started, value in active if release < started + WINDOW_SECONDS]
            if len(remaining) < MAX_STARTS and sum(value for _, value in remaining) + weight <= TOKEN_BUDGET:
                return max(0.0, release - now)
        raise AssertionError("All expired starts must admit a bounded normal request")

    def delay(self, now, weight):
        weight = _weight(weight)
        return self._delay(self._observe(now), weight)

    def record(self, now, weight):
        weight = _weight(weight)
        now = self._observe(now)
        delay = self._delay(now, weight)
        if delay > 0:
            raise AdmissionDenied(delay)
        self._records.append((now, weight))

    def snapshot(self, now):
        """JSON-safe active ages only; no prompt text or timestamp origin.

        Restoring does not subtract assumed downtime. It retains the remaining
        waits conservatively, while the runner independently applies its initial
        previous-run cooldown. A snapshot is not an authenticated provider log.
        """
        now = self._observe(now)
        return {"schema": "retrace.admission-window.v6f", "window_seconds": WINDOW_SECONDS,
                "token_budget": TOKEN_BUDGET, "max_starts": MAX_STARTS, "solo_limit": SOLO_LIMIT,
                "records": [{"age_seconds": now - started, "weight": weight} for started, weight in self._active(now)]}

    @classmethod
    def from_snapshot(cls, snapshot, now):
        now = _time(now)
        fields = {"schema", "window_seconds", "token_budget", "max_starts", "solo_limit", "records"}
        if not isinstance(snapshot, dict) or set(snapshot) != fields:
            raise ValueError("Invalid admission snapshot fields")
        expected = {"schema": "retrace.admission-window.v6f", "window_seconds": WINDOW_SECONDS,
                    "token_budget": TOKEN_BUDGET, "max_starts": MAX_STARTS, "solo_limit": SOLO_LIMIT}
        if any(snapshot.get(key) != value for key, value in expected.items()):
            raise ValueError("Snapshot policy differs from the conservative v6f policy")
        rows = snapshot["records"]
        if not isinstance(rows, list) or len(rows) > MAX_STARTS:
            raise ValueError("Invalid snapshot request count")
        result = cls()
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"age_seconds", "weight"}:
                raise ValueError("Invalid snapshot admission record")
            age = _time(row["age_seconds"])
            if not 0 <= age < WINDOW_SECONDS:
                raise ValueError("Snapshot ages must be inside the active61-second window")
            # record() also verifies ordering and that the declared history obeys
            # this local policy. No old oversized or overlapping solo is hidden.
            result.record(now - age, row["weight"])
        result._observe(now)
        return result


def estimate_request(instructions, messages, max_output_tokens, *, token_counter=None):
    """Return local-admission metadata for all instructions and text messages.

    Default counting uses tiktoken's cl100k_base over canonical JSON containing
    instructions and every message, including roles and historical assistant
    text. The buffer is ceil(1.25*reference_input_tokens); requested max output
    is added in full. This is not a provider token count or known rate quota.
    A missing tokenizer raises rather than substituting a word estimate.

    token_counter is a deterministic test hook; injected counters are explicitly
    labeled as such in metadata, never reported as genuine cl100k_base counts.
    The returned metadata contains no instructions or message content.
    """
    if not isinstance(instructions, str) or not isinstance(messages, list) or not messages:
        raise ValueError("Supply instructions and a nonempty complete message list")
    if any(not isinstance(message, dict) or not isinstance(message.get("role"), str) or not message["role"]
           or not isinstance(message.get("content"), str) for message in messages):
        raise ValueError("Estimator supports explicit role/content text messages only")
    if type(max_output_tokens) is not int or not 1 <= max_output_tokens <= SOLO_LIMIT:
        raise ValueError("Requested maximum output must be a positive integer no larger than125000")
    encoded = json.dumps({"instructions": instructions, "input": messages}, sort_keys=True,
                         separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    if token_counter is None:
        try:
            import tiktoken
        except ImportError:
            raise RuntimeError("tiktoken with cl100k_base is required; no fallback estimate is permitted") from None
        # Source/history text may literally contain tokenizer control spellings;
        # count them as ordinary text rather than rejecting or interpreting them.
        count = len(tiktoken.get_encoding(ENCODING).encode(encoded, disallowed_special=()))
        encoding = ENCODING
        tokenizer_version = tiktoken.__version__
    else:
        if not callable(token_counter): raise ValueError("Injected token counter must be callable")
        count = token_counter(encoded)
        encoding = "injected_test_counter"
        tokenizer_version = None
    if type(count) is not int or count < 0:
        raise ValueError("Token counter must return a nonnegative integer")
    weighted = (5 * count + 3) // 4
    weight = weighted + max_output_tokens
    _weight(weight)  # Local rejection before any runner budget reservation.
    return {"schema": "retrace.admission-estimate.v6f", "weight": weight,
            "reference_input_tokens": count, "weighted_input_tokens": weighted,
            "requested_max_output_tokens": max_output_tokens, "encoding": encoding,
            "tokenizer_version": tokenizer_version, "input_safety_multiplier": "1.25",
            "quota_verified": False, "solo_required": weight > TOKEN_BUDGET,
            "scope": "Conservative local reference-token estimate, not a verified vendor quota or provider input-token count. Includes all supplied instructions and role/content history plus requested maximum output."}
