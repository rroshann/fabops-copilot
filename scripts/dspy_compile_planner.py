"""DSPy BootstrapFewShot compile for the entry/planner prompt.

Uses the gold set as few-shot examples. Outputs a compiled prompt file
that replaces ENTRY_SYSTEM in nodes.py.

LM wrapper: dspy.LM("google/gemini-2.0-flash-exp", api_key=...)
  dspy-ai 3.1.3 routes through LiteLLM; dspy.Google / dspy.GoogleAI do
  not exist in this version.
"""
import json
import os
from pathlib import Path

import dspy

GOLD = Path("evals/gold_set.json")
OUT = Path("fabops/agent/planner_prompt.txt")


class ParseQuery(dspy.Signature):
    """Extract part_id, fab_id, and intent from a user query."""

    query = dspy.InputField()
    part_id = dspy.OutputField()
    fab_id = dspy.OutputField()
    intent = dspy.OutputField()


def main():
    # dspy-ai 3.1.3: dspy.Google/GoogleAI do not exist; use dspy.LM via LiteLLM.
    lm = dspy.LM("google/gemini-2.0-flash-exp", api_key=os.environ["GEMINI_API_KEY"])
    dspy.settings.configure(lm=lm)

    gold = json.loads(GOLD.read_text())
    trainset = [
        dspy.Example(
            query=c["question"],
            part_id=c["part_id"],
            fab_id=c["fab_id"],
            intent="stockout_risk",
        ).with_inputs("query")
        for c in gold[:20]
    ]

    planner = dspy.Predict(ParseQuery)
    from dspy.teleprompt import BootstrapFewShot

    compiled = BootstrapFewShot(max_bootstrapped_demos=4).compile(
        planner, trainset=trainset
    )

    OUT.write_text(
        compiled.dump_state() if hasattr(compiled, "dump_state") else str(compiled)
    )
    print(f"Compiled planner saved to {OUT}")


if __name__ == "__main__":
    main()
