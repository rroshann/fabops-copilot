"""Generate 50 adversarial variants from the gold set using Gemini Pro.

Not hand-reviewed (architect pre-authorized cut). Used for confusion matrix only.
"""
import json
import os
from pathlib import Path

import google.generativeai as genai

GOLD = Path("evals/gold_set.json")
OUT = Path("evals/adversarial_set.json")


def main():
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model = genai.GenerativeModel("gemini-2.0-pro-exp")
    gold = json.loads(GOLD.read_text())
    adversarial = []
    for i, case in enumerate(gold[:50]):
        prompt = f"""Generate a harder, more ambiguous variant of this supply-chain question
while keeping the same ground-truth driver ({case['ground_truth_driver']}).

Original: {case['question']}

Output ONLY the new question text, no quotes or prose."""
        resp = model.generate_content(prompt)
        new_q = resp.text.strip().strip('"')
        adversarial.append({
            "id": f"adv-{i:03d}",
            "question": new_q,
            "part_id": case["part_id"],
            "fab_id": case["fab_id"],
            "ground_truth_driver": case["ground_truth_driver"],
            "ground_truth_action": case["ground_truth_action"],
            "derived_from": case["id"],
        })
        print(f"  [{i+1}/50] {new_q[:80]}")
    OUT.write_text(json.dumps(adversarial, indent=2))
    print(f"Wrote {len(adversarial)} adversarial cases to {OUT}")


if __name__ == "__main__":
    main()
