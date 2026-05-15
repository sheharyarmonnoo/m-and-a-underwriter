"""Streamlit UI for the M&A underwriter.

Run: streamlit run src/m_and_a_underwriter/app.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import streamlit as st

from .agent import author_memo, offline_memo
from .lbo import assumed_defaults, run_model
from .schema import DealAssumptions, Inputs, TargetFinancials
from .workbook import export

st.set_page_config(page_title="M&A Underwriter", page_icon="MA", layout="wide")

INK = "#0a0a0a"
RUST = "#ff4d2e"

st.markdown(f"""
<style>
.main-title {{ font-family: -apple-system, sans-serif; font-weight: 900; font-size: 36px; letter-spacing: -1px; color: {INK}; }}
.kpi-card {{ background:#fff; border:2px solid {INK}; padding:14px; }}
.kpi-card h4 {{ font-family: 'Courier New', monospace; font-size: 11px; letter-spacing: 2px; color:#6b6b6b; margin:0 0 6px; text-transform: uppercase; }}
.kpi-card .v {{ font-size: 26px; font-weight: 900; letter-spacing: -1px; color: {INK}; }}
.kpi-card .v.rust {{ color: {RUST}; }}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title">M&A Underwriter</div>', unsafe_allow_html=True)
st.markdown("**Target JSON → LBO model + IC memo.** Agentic AI for corporate-finance underwriting.")

with st.sidebar:
    st.subheader("Inputs")
    src = st.radio("Source", ["Upload JSON", "Sample (Acme)"], horizontal=False)
    use_llm = st.toggle("Use LLM for memo", value=False, help="Requires OPENAI_API_KEY in env")
    run_btn = st.button("Run underwrite", type="primary", use_container_width=True)

raw: dict | None = None
if src == "Upload JSON":
    f = st.sidebar.file_uploader("Drop a target.json", type=["json"])
    if f is not None:
        raw = json.loads(f.read().decode("utf-8"))
else:
    sample = Path(__file__).resolve().parents[2] / "examples" / "target_acme.json"
    if sample.exists():
        raw = json.loads(sample.read_text(encoding="utf-8"))

if run_btn and raw:
    target = TargetFinancials.model_validate(raw["target"])
    deal = (DealAssumptions.model_validate(raw["deal"])
            if "deal" in raw else assumed_defaults(target))
    inp = Inputs(target=target, deal=deal)
    model = run_model(inp)
    memo = author_memo(inp, model) if use_llm else offline_memo(inp, model)

    c1, c2, c3, c4 = st.columns(4)
    for col, label, val, rust in [
        (c1, "MOIC", f"{model.returns.moic:.2f}x", True),
        (c2, "IRR", f"{model.returns.irr*100:.1f}%", True),
        (c3, "Sponsor Equity", f"${model.sources_uses.sponsor_equity:.1f}M", False),
        (c4, "Total Debt", f"${model.sources_uses.total_debt:.1f}M", False),
    ]:
        with col:
            klass = "v rust" if rust else "v"
            st.markdown(f'<div class="kpi-card"><h4>{label}</h4><div class="{klass}">{val}</div></div>',
                        unsafe_allow_html=True)

    tab_proj, tab_sens, tab_su, tab_memo = st.tabs(["Projection", "Sensitivity", "Sources & Uses", "IC Memo"])

    with tab_proj:
        import pandas as pd
        df = pd.DataFrame([p.model_dump() for p in model.projections]).set_index("year")
        st.dataframe(df.round(2), use_container_width=True)

    with tab_sens:
        import pandas as pd
        df = pd.DataFrame({k: {kk: f"{vv*100:.1f}%" for kk, vv in v.items()}
                           for k, v in model.sensitivity.items()}).T
        df.index.name = "Entry \\ Exit"
        st.dataframe(df, use_container_width=True)

    with tab_su:
        su = model.sources_uses
        st.write({
            "Purchase EV": round(su.purchase_ev, 1),
            "Refi debt": round(su.refinanced_debt, 1),
            "Transaction fees": round(su.transaction_fees, 1),
            "Financing fees": round(su.financing_fees, 1),
            "Minimum cash": round(su.minimum_cash, 1),
            "Total Uses": round(su.total_uses, 1),
            "Total Debt": round(su.total_debt, 1),
            "Sponsor Equity": round(su.sponsor_equity, 1),
        })

    with tab_memo:
        st.markdown(memo.body_markdown)

    tmp = Path(tempfile.mkdtemp()) / f"{target.name.lower().replace(' ', '_')}_lbo.xlsx"
    export(inp, model, tmp)
    with open(tmp, "rb") as fh:
        st.download_button("Download workbook (.xlsx)", fh.read(),
                           file_name=tmp.name,
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
elif run_btn and not raw:
    st.error("No input loaded.")
else:
    st.info("Choose a source on the left, then click **Run underwrite**.")
