# FabOps Copilot Agent Evaluation Rubric

This rubric is loaded by both the in-graph `verify` node and the external
Claude-judge eval harness. It is a versioned code artifact — changes go through
git history.

## Scoring (1–5 per dimension)

### Correctness
- 5: diagnosis names the exact primary driver (policy / demand / supply) that the ground-truth case establishes
- 4: diagnosis names a plausible but not-quite-right driver
- 3: diagnosis is ambiguous ("mixed" when ground truth has one clear driver)
- 2: diagnosis names the wrong driver
- 1: diagnosis is incoherent or errors out

### Citation faithfulness
- 5: every numerical claim in the answer is backed by a cited tool result
- 4: most claims are cited; 1-2 minor unsupported statements
- 3: some claims cited, some hand-waved
- 2: few citations; answer mostly assertions
- 1: no citations or cites non-existent sources

### Action appropriateness
- 5: recommended action matches the driver (refresh policy for policy-driven, expedite for supply-driven, reorder for demand-driven)
- 4: action is reasonable but not the textbook choice
- 3: action is generic ("monitor closely")
- 2: action is wrong type for the driver
- 1: no action given or action is incoherent

## Overall pass criterion

An answer passes iff all three scores are >= 4.
