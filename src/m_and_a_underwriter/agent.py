"""Homegrown agentic loop. No framework, no magic.

Two agents live here:
  - extract: PDF / dict -> validated TargetFinancials
  - memo:    ModelOutput -> ICMemo

Both validate via pydantic before returning. If the LLM hallucinates a field
that doesn't conform, we raise.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from pydantic import ValidationError

from .schema import DealAssumptions, ICMemo, Inputs, ModelOutput, TargetFinancials

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


@dataclass
class LLMResponse:
    text: str
    raw: dict


def _call_llm(prompt: str, *, system: str, json_mode: bool = False) -> LLMResponse:
    provider = (os.getenv("LLM_PROVIDER") or "openai").lower()
    model = os.getenv("LLM_MODEL") or ("gpt-4o-mini" if provider == "openai" else "claude-3-5-sonnet-latest")

    if provider == "openai":
        from openai import OpenAI
        client = OpenAI()
        kwargs: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        r = client.chat.completions.create(**kwargs)
        return LLMResponse(text=r.choices[0].message.content or "", raw=r.model_dump())

    if provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic()
        r = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system + ("\n\nReturn ONLY JSON." if json_mode else ""),
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in r.content if hasattr(b, "text"))
        return LLMResponse(text=text, raw=r.model_dump())

    raise RuntimeError(f"Unknown LLM_PROVIDER: {provider!r}")


EXTRACT_SYSTEM = """You are a sell-side analyst building a target dossier.

Given a CIM excerpt or descriptive text about a company, extract the target's
financial profile. Return ONLY valid JSON conforming to the requested schema.
Use sensible industry-typical assumptions for any field not explicitly stated.
Never invent revenue or EBITDA — if not stated, return 0 so the caller knows."""


def extract_target(text: str) -> TargetFinancials:
    """LLM-driven extraction with pydantic validation as the safety net."""
    schema_hint = TargetFinancials.model_json_schema()
    prompt = (
        f"Extract a TargetFinancials object from the text below. "
        f"Use this JSON Schema:\n\n{json.dumps(schema_hint, indent=2)}\n\n"
        f"TEXT:\n\n{text}\n\n"
        f"Return only the JSON object."
    )
    resp = _call_llm(prompt, system=EXTRACT_SYSTEM, json_mode=True)
    try:
        return TargetFinancials.model_validate_json(resp.text)
    except ValidationError as e:
        raise ValueError(f"Extractor returned invalid TargetFinancials: {e}") from e


MEMO_SYSTEM = """You are an investment-committee voice writing for a PE sponsor.

Style: terse, direct, no marketing language. Cite the numbers, not adjectives.
Lead the memo with the thesis, then findings, then risks, then recommendation."""


def author_memo(inp: Inputs, model: ModelOutput) -> ICMemo:
    su, ret = model.sources_uses, model.returns
    snap = {
        "target": inp.target.name,
        "industry": inp.target.industry,
        "entry_multiple": inp.deal.entry_multiple,
        "exit_multiple": inp.deal.exit_multiple,
        "ltm_revenue": inp.target.ltm_revenue,
        "ltm_ebitda": inp.target.ltm_ebitda,
        "purchase_ev": round(su.purchase_ev, 1),
        "sponsor_equity": round(su.sponsor_equity, 1),
        "total_debt": round(su.total_debt, 1),
        "leverage_x": round(su.total_debt / inp.target.ltm_ebitda, 2),
        "exit_equity": round(ret.exit_equity, 1),
        "moic": round(ret.moic, 2),
        "irr_pct": round(ret.irr * 100, 1),
    }
    prompt = (
        "Write a 2-page IC memo as Markdown. Sections: Thesis, Diligence Findings, "
        "Risks & Mitigants, Returns Summary, Recommendation. "
        "Use the deal snapshot below.\n\n"
        f"```json\n{json.dumps(snap, indent=2)}\n```\n\n"
        "Then return a JSON envelope:\n"
        '{"title": str, "thesis": str (1-2 sentences), '
        '"diligence_findings": [str, ...], "risks": [str, ...], '
        '"recommendation": "proceed"|"proceed_with_conditions"|"pass", '
        '"body_markdown": str (the full memo)}'
    )
    resp = _call_llm(prompt, system=MEMO_SYSTEM, json_mode=True)
    try:
        return ICMemo.model_validate_json(resp.text)
    except ValidationError as e:
        raise ValueError(f"Memo agent returned invalid ICMemo: {e}") from e


def offline_memo(inp: Inputs, model: ModelOutput) -> ICMemo:
    """Deterministic memo for offline / no-API-key runs and tests."""
    su, ret = model.sources_uses, model.returns
    lev = su.total_debt / inp.target.ltm_ebitda
    rec = "proceed" if ret.irr >= 0.20 else "proceed_with_conditions" if ret.irr >= 0.15 else "pass"
    body = f"""# {inp.target.name} \u2014 IC Memo (offline)

## Thesis
{inp.target.name} is a {inp.target.industry} platform priced at {inp.deal.entry_multiple:.1f}x LTM
EBITDA of ${inp.target.ltm_ebitda:.1f}M. Base-case sponsor returns clear {ret.irr*100:.1f}% IRR
on a {inp.deal.hold_years}-year hold.

## Diligence Findings
- LTM revenue ${inp.target.ltm_revenue:.1f}M, forward EBITDA margin {inp.target.ebitda_margin_proj*100:.1f}%
- Entry leverage {lev:.2f}x; sponsor equity ${su.sponsor_equity:.1f}M
- Cap stack sized at ${su.total_debt:.1f}M across the provided tranches

## Risks & Mitigants
- Multiple compression: stress-tested in the 5x5 sensitivity grid
- Debt paydown sensitivity to working capital swings: monitor NWC variance

## Returns Summary
- MOIC {ret.moic:.2f}x \u00b7 IRR {ret.irr*100:.1f}%
- Exit equity ${ret.exit_equity:.1f}M at {inp.deal.exit_multiple:.1f}x exit on Y{inp.deal.hold_years} EBITDA ${ret.exit_ebitda:.1f}M

## Recommendation
{rec.replace('_', ' ').title()}.
"""
    return ICMemo(
        title=f"{inp.target.name} \u2014 IC Memo",
        thesis=f"{inp.target.name}: {inp.deal.entry_multiple:.1f}x entry, {ret.irr*100:.1f}% base IRR.",
        diligence_findings=[
            f"LTM revenue ${inp.target.ltm_revenue:.1f}M, EBITDA ${inp.target.ltm_ebitda:.1f}M",
            f"Entry leverage {lev:.2f}x, sponsor equity ${su.sponsor_equity:.1f}M",
        ],
        risks=[
            "Multiple compression at exit",
            "NWC swings stressing the cash sweep",
        ],
        recommendation=rec,  # type: ignore[arg-type]
        body_markdown=body,
    )


def assemble_inputs(target: TargetFinancials, deal: DealAssumptions) -> Inputs:
    return Inputs(target=target, deal=deal)
