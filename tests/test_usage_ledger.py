"""Tests for usage_ledger: per-model totals and dollar estimates from recorded calls."""
import pytest

import usage_ledger as ledger


def test_totals_and_costs_per_model(tmp_path):
    # The Muse Wonder trial call's usage block (see CLAUDE.md, "How to call Muse Wonder").
    wonder_response = {"usage": {"prompt_tokens": 237, "completion_tokens": 806,
                                 "completion_tokens_details": {"reasoning_tokens": 727}}}
    ledger.record_response(tmp_path, ledger.WONDER, "trial", wonder_response, seconds=8.9)
    for _ in range(3):
        ledger.record(tmp_path, ledger.SAM, "segment", images=1, seconds=2)
    ledger.record_response(tmp_path, ledger.SPARK_OPEN, "candidate 1", {"usage": {"prompt_tokens": 900, "completion_tokens": 1500}})
    ledger.record_response(tmp_path, ledger.SPARK_OPEN, "candidate 2", {"error": "connection reset"})  # failed: 0 tokens

    summary = ledger.summarize(tmp_path)
    wonder, sam, spark = (summary["models"][m] for m in (ledger.WONDER, ledger.SAM, ledger.SPARK_OPEN))
    assert wonder["reasoning_tokens"] == 727 and wonder["cost_usd"] == pytest.approx(237 * 4e-6 + 806 * 20e-6, abs=1e-4)
    assert sam["images"] == 3 and sam["cost_usd"] == pytest.approx(0.0075) and sam["seconds"] == 6
    assert spark["calls"] == 2 and spark["output_tokens"] == 1500
    assert spark["cost_usd"] == pytest.approx(900 * 1.25e-6 + 1500 * 4.25e-6, abs=1e-4)
    assert summary["unverified_price_models"] == [ledger.SPARK_OPEN] and not wonder["price_unverified"]
    assert summary["known_cost_usd"] == pytest.approx(wonder["cost_usd"] + sam["cost_usd"] + spark["cost_usd"], abs=1e-4)


def test_a_run_without_calls_has_an_empty_ledger(tmp_path):
    assert ledger.summarize(tmp_path)["models"] == {}
