"""Pre-call budget enforcement for paid model calls.

Design rules (fail closed everywhere):
- Cost is RESERVED before a call: worst case = (input token bound
  + max_output_tokens + per-request overhead) x pricing, with a safety
  multiplier. A call that would push reserved spend over the ceiling
  is refused BEFORE it happens - so retries, concurrency and output
  length cannot silently overrun: each one needs its own reservation.
- Input tokens are bounded, not guessed: for byte-level BPE
  tokenizers every token encodes at least one input byte, so the
  UTF-8 byte length of the prompt is a sound upper bound on its token
  count (Unicode/code dense text cannot exceed it). Models whose
  tokenizer is not known to satisfy that property are refused, as is
  non-text input. max_output_tokens alone is never treated as a cost
  bound; it is only one reservation term.
- The cumulative total lives in a state file guarded by an OS-level
  advisory lock (fcntl.flock) around every load-modify-store, so
  concurrent processes cannot lose each other's spend; the write
  itself is atomic (temp file + os.replace). Corrupt or unreadable
  state fails closed by treating the ceiling as fully spent.
- If the underlying client raises, the full reservation is KEPT: a
  failed-looking call may still have been billed.
"""
from __future__ import annotations

import fcntl
import json
import os
import threading
from dataclasses import dataclass


class BudgetExceeded(Exception):
    """The call was refused before it happened. Nothing was spent."""


@dataclass(frozen=True)
class Pricing:
    input_per_mtok: float
    output_per_mtok: float
    tokenizer: str  # must be a tokenizer class with a sound bound


_SAFETY = 1.25
_REQUEST_OVERHEAD = 32  # framing/message tokens, conservative


def token_bound(text: str, tokenizer: str) -> int:
    """Sound upper bound on input tokens, or refuse (fail closed)."""
    if not isinstance(text, str):
        raise BudgetExceeded("cannot bound tokens for non-text input")
    if tokenizer != "byte-bpe":
        raise BudgetExceeded(
            f"no sound token bound for tokenizer {tokenizer!r}")
    # byte-level BPE: each token covers >= 1 byte of the input
    return len(text.encode("utf-8")) + _REQUEST_OVERHEAD


@dataclass
class _Reservation:
    model: str
    amount: float


class Budget:
    """A persisted, cumulative, pre-call spending ceiling.

    Safe for concurrent processes on one machine: every mutation
    reloads state and stores it under an exclusive flock.
    """

    def __init__(self, path, ceiling_usd: float,
                 pricing: dict[str, Pricing]):
        if ceiling_usd is None or ceiling_usd <= 0:
            raise BudgetExceeded("no positive ceiling configured")
        self.path = str(path)
        self.lock_path = self.path + ".lock"
        self.ceiling = float(ceiling_usd)
        self.pricing = dict(pricing)
        self._thread_lock = threading.Lock()

    def _load(self) -> float:
        try:
            with open(self.path) as f:
                return float(json.load(f)["reserved_usd"])
        except FileNotFoundError:
            return 0.0
        except (json.JSONDecodeError, KeyError, ValueError):
            return self.ceiling  # fail closed

    def _store(self, reserved: float) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"reserved_usd": reserved}, f)
        os.replace(tmp, self.path)

    def _mutate(self, fn):
        # thread lock first (same process), then OS lock (any process);
        # state is re-read and written while holding the OS lock
        with self._thread_lock:
            with open(self.lock_path, "a+b") as lockf:
                fcntl.flock(lockf, fcntl.LOCK_EX)
                try:
                    reserved = self._load()
                    reserved, result = fn(reserved)
                    self._store(reserved)
                    return result
                finally:
                    fcntl.flock(lockf, fcntl.LOCK_UN)

    def reserve(self, model: str, prompt: str,
                max_output_tokens: int) -> _Reservation:
        price = self.pricing.get(model)
        if price is None:
            raise BudgetExceeded(f"no pricing for model {model!r}")
        if max_output_tokens <= 0:
            raise BudgetExceeded("max_output_tokens unknown")
        tokens = token_bound(prompt, price.tokenizer) + max_output_tokens
        worst = (tokens * max(price.input_per_mtok,
                              price.output_per_mtok)
                 / 1_000_000) * _SAFETY

        def take(reserved):
            if reserved + worst > self.ceiling:
                raise BudgetExceeded(
                    f"ceiling ${self.ceiling:.4f} would be exceeded: "
                    f"${reserved:.4f} reserved, call needs "
                    f"up to ${worst:.4f}")
            return reserved + worst, _Reservation(model, worst)

        return self._mutate(take)

    def settle(self, res: _Reservation, actual_input_tokens: int,
               actual_output_tokens: int) -> None:
        """Reconcile after a successful call; on error do not call -
        the reservation stays at its worst-case amount."""
        price = self.pricing[res.model]
        actual = ((actual_input_tokens * price.input_per_mtok
                   + actual_output_tokens * price.output_per_mtok)
                  / 1_000_000) * _SAFETY

        def refund(reserved):
            return reserved + actual - res.amount, None

        self._mutate(refund)

    @property
    def reserved_usd(self) -> float:
        with self._thread_lock:
            with open(self.lock_path, "a+b") as lockf:
                fcntl.flock(lockf, fcntl.LOCK_EX)
                try:
                    return self._load()
                finally:
                    fcntl.flock(lockf, fcntl.LOCK_UN)


class BudgetedClient:
    """Wrap a prompt->text model client with pre-call reservations."""

    def __init__(self, client, budget: Budget, model: str,
                 max_output_tokens: int):
        self.client = client
        self.budget = budget
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        res = self.budget.reserve(self.model, prompt,
                                  self.max_output_tokens)
        self.calls += 1
        out = self.client(prompt)  # raises -> reservation kept
        price = self.budget.pricing[self.model]
        self.budget.settle(res, token_bound(prompt, price.tokenizer),
                           token_bound(out, price.tokenizer))
        return out
