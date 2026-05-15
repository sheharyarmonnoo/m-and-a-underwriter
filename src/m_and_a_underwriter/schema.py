"""Pydantic schemas for the M&A underwriter.

Every input and every output passes through here. Validation is the first
quality gate before any LBO math runs.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class TargetFinancials(BaseModel):
    """Source-data view of the target. Everything downstream keys off this."""

    name: str
    ticker: str | None = None
    industry: str

    ltm_revenue: float = Field(..., gt=0, description="LTM revenue, $M")
    ltm_ebitda: float = Field(..., description="LTM EBITDA, $M")
    ebitda_margin_proj: float = Field(..., ge=0, le=1, description="Forward EBITDA margin")

    revenue_growth: list[float] = Field(..., min_length=5, max_length=5,
                                        description="Y1..Y5 revenue growth, decimal (e.g., 0.08)")

    capex_pct_revenue: float = Field(..., ge=0, le=0.3)
    nwc_pct_revenue: float = Field(..., ge=-0.2, le=0.4)
    tax_rate: float = Field(0.25, ge=0, le=0.5)
    d_and_a_pct_revenue: float = Field(0.03, ge=0, le=0.15)

    existing_net_debt: float = Field(0, description="$M, positive = debt, negative = cash")

    @field_validator("ltm_ebitda")
    @classmethod
    def _ebitda_sanity(cls, v: float, info) -> float:
        rev = info.data.get("ltm_revenue")
        if rev and v > rev:
            raise ValueError("EBITDA cannot exceed revenue")
        return v


class Tranche(BaseModel):
    """A single piece of the capital stack."""

    name: str
    kind: Literal["revolver", "tla", "tlb", "mezz", "pik", "seller_note"]
    principal: float = Field(..., ge=0, description="$M")
    rate: float = Field(..., ge=0, le=0.25, description="Coupon, decimal")
    term_years: int = Field(..., ge=1, le=10)
    amort_pct: float = Field(0.0, ge=0, le=1.0, description="Annual amortization, decimal")
    cash_pay: bool = True


class DealAssumptions(BaseModel):
    """Sponsor's view of the deal. Multiples, fees, exit."""

    entry_multiple: float = Field(..., gt=0, description="EV / LTM EBITDA")
    exit_multiple: float = Field(..., gt=0)
    hold_years: int = Field(5, ge=3, le=7)

    transaction_fees: float = Field(0.025, ge=0, le=0.10,
                                    description="As % of EV")
    financing_fees: float = Field(0.02, ge=0, le=0.10,
                                  description="As % of total debt raised")
    min_cash: float = Field(5.0, ge=0)

    cap_stack: list[Tranche] = Field(..., min_length=1)


class Inputs(BaseModel):
    """The full input bundle that drives the model."""

    target: TargetFinancials
    deal: DealAssumptions


class SourcesUses(BaseModel):
    purchase_ev: float
    refinanced_debt: float
    transaction_fees: float
    financing_fees: float
    minimum_cash: float
    total_uses: float

    total_debt: float
    sponsor_equity: float
    total_sources: float


class YearProjection(BaseModel):
    year: int
    revenue: float
    ebitda: float
    d_and_a: float
    ebit: float
    interest: float
    pretax: float
    taxes: float
    net_income: float

    capex: float
    delta_nwc: float
    cash_flow_pre_debt: float

    mandatory_amort: float
    cash_sweep: float
    debt_paydown: float

    beg_debt: float
    end_debt: float

    beg_cash: float
    end_cash: float


class Returns(BaseModel):
    exit_ebitda: float
    exit_ev: float
    exit_equity: float
    moic: float
    irr: float


class ModelOutput(BaseModel):
    sources_uses: SourcesUses
    projections: list[YearProjection]
    returns: Returns
    sensitivity: dict[str, dict[str, float]]
    accretion_dilution: dict[str, float]


class ICMemo(BaseModel):
    title: str
    thesis: str
    diligence_findings: list[str]
    risks: list[str]
    recommendation: Literal["proceed", "proceed_with_conditions", "pass"]
    body_markdown: str
