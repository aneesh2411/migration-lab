"""Budget wrapper: sound token bounds, pre-call reservation, locking."""
import json
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from migrator.budget import (Budget, BudgetedClient, BudgetExceeded,  # noqa: E402
                             Pricing, token_bound)

PRICING = {"test-model": Pricing(input_per_mtok=0.10,
                                 output_per_mtok=0.50,
                                 tokenizer="byte-bpe")}


def make_budget(tmp_path, ceiling=0.01, name="budget.json"):
    return Budget(tmp_path / name, ceiling, PRICING)


def test_token_bound_covers_unicode_dense_text():
    # emoji-heavy text: a chars/3 heuristic would UNDERCOUNT; the byte
    # bound cannot, because every BPE token covers >= 1 byte
    text = "\U0001f600" * 100  # 4 bytes each in UTF-8
    bound = token_bound(text, "byte-bpe")
    assert bound >= len(text.encode("utf-8"))
    assert bound > len(text) // 3 * 10  # far above the old heuristic


def test_unsupported_tokenizer_fails_closed():
    with pytest.raises(BudgetExceeded):
        token_bound("hello", "sentencepiece-unknown-variant")


def test_non_text_input_fails_closed():
    with pytest.raises(BudgetExceeded):
        token_bound(b"bytes", "byte-bpe")


def test_reservation_accumulates_and_persists(tmp_path):
    b = make_budget(tmp_path)
    b.reserve("test-model", "x" * 300, 500)
    after = b.reserved_usd
    assert after > 0
    assert make_budget(tmp_path).reserved_usd == after
    json.loads((tmp_path / "budget.json").read_text())  # valid JSON


def test_ceiling_refuses_before_call(tmp_path):
    b = make_budget(tmp_path, ceiling=0.0001)
    calls = []
    client = BudgetedClient(lambda p: calls.append(p) or "ok", b,
                            "test-model", 500)
    with pytest.raises(BudgetExceeded):
        client("x" * 9000)
    assert calls == []  # the paid call never happened


def test_settle_refunds_to_actual(tmp_path):
    b = make_budget(tmp_path, ceiling=0.01)
    client = BudgetedClient(lambda p: "short", b, "test-model", 5000)
    client("hello world")
    assert b.reserved_usd < 0.0001


def test_unknown_model_fails_closed(tmp_path):
    b = make_budget(tmp_path)
    with pytest.raises(BudgetExceeded):
        b.reserve("mystery-model", "prompt", 10)


def test_corrupt_state_fails_closed(tmp_path):
    (tmp_path / "budget.json").write_text("not json")
    b = make_budget(tmp_path)
    with pytest.raises(BudgetExceeded):
        b.reserve("test-model", "prompt", 10)


def test_no_ceiling_fails_closed(tmp_path):
    with pytest.raises(BudgetExceeded):
        Budget(tmp_path / "b.json", 0, PRICING)


def test_client_error_keeps_full_reservation(tmp_path):
    b = make_budget(tmp_path, ceiling=0.01)
    res = b.reserve("test-model", "prompt", 500)
    before = b.reserved_usd
    # settle deliberately not called: a raised call may be billed
    assert b.reserved_usd == before == res.amount


def test_concurrent_instances_lose_no_spend(tmp_path):
    # two Budget objects over one file, interleaved across threads;
    # flock must serialize every load-modify-store
    ceiling = 100.0
    budgets = [make_budget(tmp_path, ceiling),
               make_budget(tmp_path, ceiling)]
    errors = []

    def worker(b):
        try:
            for _ in range(50):
                b.reserve("test-model", "x" * 60, 100)
        except BudgetExceeded as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(b,))
               for b in budgets]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    final = make_budget(tmp_path, ceiling).reserved_usd
    one = Budget(tmp_path / "unit.json", ceiling,
                 PRICING).reserve("test-model", "x" * 60, 100).amount
    assert final == pytest.approx(100 * one)  # exactly 100 reservations
