"""Golden-file-style tests for the LBO engine. No LLM required."""

import json
from pathlib import Path

import pytest

from m_and_a_underwriter import (
    DealAssumptions,
    Inputs,
    TargetFinancials,
    Tranche,
    build_sources_uses,
    offline_memo,
    project_years,
    run_model,
)

SAMPLE = Path(__file__).resolve().parents[1] / "examples" / "target_acme.json"


@pytest.fixture()
def acme() -> Inputs:
    raw = json.loads(SAMPLE.read_text(encoding="utf-8"))
    return Inputs(
        target=TargetFinancials.model_validate(raw["target"]),
        deal=DealAssumptions.model_validate(raw["deal"]),
    )


def test_sources_uses_balance(acme: Inputs) -> None:
    su = build_sources_uses(acme)
    assert abs(su.total_sources - su.total_uses) < 0.01, "S&U must balance"
    assert su.total_debt == sum(tr.principal for tr in acme.deal.cap_stack)


def test_projection_length(acme: Inputs) -> None:
    su = build_sources_uses(acme)
    proj = project_years(acme, su)
    assert len(proj) == acme.deal.hold_years


def test_debt_only_decreases(acme: Inputs) -> None:
    su = build_sources_uses(acme)
    proj = project_years(acme, su)
    balances = [p.end_debt for p in proj]
    assert all(b2 <= b1 + 0.01 for b1, b2 in zip(balances, balances[1:], strict=False))


def test_returns_positive_on_base(acme: Inputs) -> None:
    model = run_model(acme)
    assert model.returns.moic > 1.0, "Base case must clear 1.0x MOIC"
    assert model.returns.irr > 0


def test_sensitivity_monotone_in_exit(acme: Inputs) -> None:
    """At a fixed entry, IRR should rise with exit multiple."""
    model = run_model(acme)
    rows = list(model.sensitivity.values())
    mid_row = rows[len(rows) // 2]
    irrs = list(mid_row.values())
    assert irrs == sorted(irrs), f"IRR not monotone in exit: {irrs}"


def test_offline_memo_renders(acme: Inputs) -> None:
    model = run_model(acme)
    memo = offline_memo(acme, model)
    assert "IC Memo" in memo.title
    assert memo.recommendation in {"proceed", "proceed_with_conditions", "pass"}
    assert len(memo.body_markdown) > 200


def test_overfunded_cap_stack_raises() -> None:
    t = TargetFinancials(
        name="Tiny", industry="Test", ltm_revenue=100, ltm_ebitda=20,
        ebitda_margin_proj=0.2, revenue_growth=[0.05]*5,
        capex_pct_revenue=0.02, nwc_pct_revenue=0.1, tax_rate=0.25,
        d_and_a_pct_revenue=0.03, existing_net_debt=0,
    )
    deal = DealAssumptions(
        entry_multiple=5, exit_multiple=5, hold_years=5,
        cap_stack=[Tranche(name="X", kind="tlb", principal=500,
                            rate=0.08, term_years=7, amort_pct=0)],
    )
    with pytest.raises(ValueError):
        build_sources_uses(Inputs(target=t, deal=deal))
