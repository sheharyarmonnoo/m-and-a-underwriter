"""LBO engine. Pure math, no LLM.

Builds Sources & Uses, the 5-year projection with debt waterfall, and exit returns.
Every line ties to schema.py; if it isn't in the schema, it doesn't come out of this module.
"""

from __future__ import annotations

from copy import deepcopy

from .schema import (
    DealAssumptions,
    Inputs,
    ModelOutput,
    Returns,
    SourcesUses,
    TargetFinancials,
    Tranche,
    YearProjection,
)


def build_sources_uses(inp: Inputs) -> SourcesUses:
    t, d = inp.target, inp.deal
    ev = t.ltm_ebitda * d.entry_multiple
    txn_fees = ev * d.transaction_fees

    total_debt = sum(tr.principal for tr in d.cap_stack)
    fin_fees = total_debt * d.financing_fees

    refi = max(0.0, t.existing_net_debt)
    min_cash = d.min_cash

    total_uses = ev + refi + txn_fees + fin_fees + min_cash
    equity = total_uses - total_debt
    if equity < 0:
        raise ValueError(f"Cap stack over-funds the deal by ${-equity:.1f}M. Reduce debt.")

    return SourcesUses(
        purchase_ev=ev,
        refinanced_debt=refi,
        transaction_fees=txn_fees,
        financing_fees=fin_fees,
        minimum_cash=min_cash,
        total_uses=total_uses,
        total_debt=total_debt,
        sponsor_equity=equity,
        total_sources=total_debt + equity,
    )


def _project_revenue(t: TargetFinancials, years: int) -> list[float]:
    out = []
    rev = t.ltm_revenue
    for yr in range(years):
        g = t.revenue_growth[yr] if yr < len(t.revenue_growth) else t.revenue_growth[-1]
        rev = rev * (1 + g)
        out.append(rev)
    return out


def _interest_on_balance(tranches: list[Tranche], debt_by_tranche: dict[str, float]) -> float:
    return sum(debt_by_tranche.get(tr.name, 0) * tr.rate for tr in tranches)


def project_years(inp: Inputs, su: SourcesUses) -> list[YearProjection]:
    t, d = inp.target, inp.deal
    revenues = _project_revenue(t, d.hold_years)

    tranches = deepcopy(d.cap_stack)
    debt_by_tranche: dict[str, float] = {tr.name: tr.principal for tr in tranches}
    cash = su.minimum_cash

    out: list[YearProjection] = []
    for i, rev in enumerate(revenues):
        beg_debt = sum(debt_by_tranche.values())
        beg_cash = cash

        ebitda = rev * t.ebitda_margin_proj
        d_and_a = rev * t.d_and_a_pct_revenue
        ebit = ebitda - d_and_a

        interest = _interest_on_balance(tranches, debt_by_tranche)
        pretax = ebit - interest
        taxes = max(0.0, pretax) * t.tax_rate
        net_income = pretax - taxes

        capex = rev * t.capex_pct_revenue
        prev_rev = revenues[i - 1] if i > 0 else t.ltm_revenue
        delta_nwc = (rev - prev_rev) * t.nwc_pct_revenue

        cfo_pre_debt = net_income + d_and_a - capex - delta_nwc

        # Mandatory amortization first (TLA-style)
        mandatory = 0.0
        for tr in tranches:
            if tr.amort_pct > 0 and debt_by_tranche[tr.name] > 0:
                pay = min(debt_by_tranche[tr.name], tr.principal * tr.amort_pct)
                mandatory += pay
                debt_by_tranche[tr.name] -= pay

        # Cash available for sweep after maintaining minimum cash
        post_amort_cash = cash + cfo_pre_debt - mandatory
        sweep_capacity = max(0.0, post_amort_cash - d.min_cash)

        # Sweep order: revolver, then TLB, then mezz, then PIK
        sweep_order = ["revolver", "tlb", "tla", "mezz", "pik", "seller_note"]
        sweep_total = 0.0
        for kind in sweep_order:
            if sweep_capacity <= 0:
                break
            for tr in tranches:
                if tr.kind != kind or debt_by_tranche[tr.name] <= 0:
                    continue
                pay = min(debt_by_tranche[tr.name], sweep_capacity)
                debt_by_tranche[tr.name] -= pay
                sweep_capacity -= pay
                sweep_total += pay
                if sweep_capacity <= 0:
                    break

        end_debt = sum(debt_by_tranche.values())
        end_cash = beg_cash + cfo_pre_debt - mandatory - sweep_total

        out.append(YearProjection(
            year=i + 1,
            revenue=rev,
            ebitda=ebitda,
            d_and_a=d_and_a,
            ebit=ebit,
            interest=interest,
            pretax=pretax,
            taxes=taxes,
            net_income=net_income,
            capex=capex,
            delta_nwc=delta_nwc,
            cash_flow_pre_debt=cfo_pre_debt,
            mandatory_amort=mandatory,
            cash_sweep=sweep_total,
            debt_paydown=mandatory + sweep_total,
            beg_debt=beg_debt,
            end_debt=end_debt,
            beg_cash=beg_cash,
            end_cash=end_cash,
        ))
        cash = end_cash

    return out


def compute_returns(inp: Inputs, su: SourcesUses, projections: list[YearProjection]) -> Returns:
    exit_year = projections[-1]
    exit_ebitda = exit_year.ebitda
    exit_ev = exit_ebitda * inp.deal.exit_multiple
    exit_equity = exit_ev - exit_year.end_debt + exit_year.end_cash
    moic = exit_equity / su.sponsor_equity if su.sponsor_equity > 0 else 0
    irr = moic ** (1 / inp.deal.hold_years) - 1 if moic > 0 else -1.0
    return Returns(
        exit_ebitda=exit_ebitda,
        exit_ev=exit_ev,
        exit_equity=exit_equity,
        moic=moic,
        irr=irr,
    )


def sensitivity(inp: Inputs, entry_steps: list[float], exit_steps: list[float]) -> dict[str, dict[str, float]]:
    grid: dict[str, dict[str, float]] = {}
    base_entry = inp.deal.entry_multiple
    base_exit = inp.deal.exit_multiple
    for em_delta in entry_steps:
        row: dict[str, float] = {}
        for xm_delta in exit_steps:
            cand = inp.model_copy(deep=True)
            cand.deal.entry_multiple = base_entry + em_delta
            cand.deal.exit_multiple = base_exit + xm_delta
            su = build_sources_uses(cand)
            projs = project_years(cand, su)
            ret = compute_returns(cand, su, projs)
            row[f"{cand.deal.exit_multiple:.1f}x"] = round(ret.irr, 4)
        grid[f"{cand.deal.entry_multiple:.1f}x"] = row
    return grid


def accretion_dilution(inp: Inputs, projections: list[YearProjection]) -> dict[str, float]:
    """Simple stand-alone vs. pro-forma EPS deltas on Y1.

    Stand-alone uses LTM net income proxy; pro-forma is post-deal Y1 net income.
    """
    t = inp.target
    standalone_ni = (t.ltm_ebitda - t.ltm_revenue * t.d_and_a_pct_revenue) * (1 - t.tax_rate)
    proforma_ni = projections[0].net_income
    return {
        "standalone_y1_ni": round(standalone_ni, 2),
        "proforma_y1_ni": round(proforma_ni, 2),
        "delta_pct": round((proforma_ni / standalone_ni - 1) * 100, 2) if standalone_ni else 0.0,
    }


def run_model(inp: Inputs) -> ModelOutput:
    su = build_sources_uses(inp)
    projs = project_years(inp, su)
    rets = compute_returns(inp, su, projs)
    sens = sensitivity(inp, entry_steps=[-1.0, -0.5, 0, 0.5, 1.0], exit_steps=[-1.0, -0.5, 0, 0.5, 1.0])
    ad = accretion_dilution(inp, projs)
    return ModelOutput(
        sources_uses=su,
        projections=projs,
        returns=rets,
        sensitivity=sens,
        accretion_dilution=ad,
    )


def assumed_defaults(target: TargetFinancials, entry_multiple: float = 10.0) -> DealAssumptions:
    """Reasonable default cap stack so the LLM extractor can punt."""
    ev = target.ltm_ebitda * entry_multiple
    debt = ev * 0.55  # ~5.5x leverage on a 10x deal
    tla = debt * 0.25
    tlb = debt * 0.55
    mezz = debt * 0.20
    return DealAssumptions(
        entry_multiple=entry_multiple,
        exit_multiple=entry_multiple,
        hold_years=5,
        cap_stack=[
            Tranche(name="Revolver", kind="revolver", principal=0, rate=0.075, term_years=5, amort_pct=0.0),
            Tranche(name="TLA", kind="tla", principal=tla, rate=0.075, term_years=5, amort_pct=0.10),
            Tranche(name="TLB", kind="tlb", principal=tlb, rate=0.085, term_years=7, amort_pct=0.01),
            Tranche(name="Mezz", kind="mezz", principal=mezz, rate=0.12, term_years=8, amort_pct=0.0),
        ],
    )
