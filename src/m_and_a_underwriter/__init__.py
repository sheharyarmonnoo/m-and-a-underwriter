"""M&A Underwriter — CIM PDF → LBO model + IC memo."""

from .agent import author_memo, extract_target, offline_memo
from .lbo import (
    accretion_dilution,
    assumed_defaults,
    build_sources_uses,
    compute_returns,
    project_years,
    run_model,
    sensitivity,
)
from .schema import (
    DealAssumptions,
    ICMemo,
    Inputs,
    ModelOutput,
    Returns,
    SourcesUses,
    TargetFinancials,
    Tranche,
    YearProjection,
)
from .workbook import export

__version__ = "0.1.0"

__all__ = [
    "TargetFinancials", "Tranche", "DealAssumptions", "Inputs",
    "SourcesUses", "YearProjection", "Returns", "ModelOutput", "ICMemo",
    "run_model", "build_sources_uses", "project_years", "compute_returns",
    "sensitivity", "accretion_dilution", "assumed_defaults",
    "extract_target", "author_memo", "offline_memo",
    "export",
]
