"""CLI: `python -m m_and_a_underwriter examples/target_acme.json [--llm]`"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent import author_memo, offline_memo
from .lbo import assumed_defaults, run_model
from .schema import DealAssumptions, Inputs, TargetFinancials
from .workbook import export


def main() -> int:
    ap = argparse.ArgumentParser(prog="m-and-a-underwriter")
    ap.add_argument("inputs", type=Path, help="JSON file: TargetFinancials and optional DealAssumptions")
    ap.add_argument("--llm", action="store_true", help="Author the memo via LLM (needs API key)")
    ap.add_argument("--out", type=Path, default=Path("out"), help="Output directory")
    args = ap.parse_args()

    raw = json.loads(args.inputs.read_text(encoding="utf-8"))
    target = TargetFinancials.model_validate(raw["target"])
    deal = (DealAssumptions.model_validate(raw["deal"])
            if "deal" in raw else assumed_defaults(target))
    inp = Inputs(target=target, deal=deal)

    model = run_model(inp)
    args.out.mkdir(parents=True, exist_ok=True)
    workbook_path = export(inp, model, args.out / f"{target.name.lower().replace(' ', '_')}_lbo.xlsx")

    memo = author_memo(inp, model) if args.llm else offline_memo(inp, model)
    memo_path = args.out / f"{target.name.lower().replace(' ', '_')}_ic_memo.md"
    memo_path.write_text(memo.body_markdown, encoding="utf-8")

    print(f"Workbook : {workbook_path}")
    print(f"IC memo  : {memo_path}")
    print(f"MOIC     : {model.returns.moic:.2f}x")
    print(f"IRR      : {model.returns.irr*100:.1f}%")
    print(f"Rec      : {memo.recommendation}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
