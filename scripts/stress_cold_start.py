"""Cold-start stress harness for the FabOps runtime Lambda.

Hits FABOPS_API_URL 10 times in a row, prints per-request latency, then
prints p50 / p95 / p99 / max summary.

To measure a true cold start, recycle the Lambda execution environment first:
  aws lambda update-function-configuration --function-name fabops_agent_handler \\
    --description "force-recycle $(date +%s)" --region us-east-1

Then immediately run this script. The first request will include cold-start
time (~1-3s for a 25MB zipped Python Lambda); subsequent requests hit the
warm container.

Percentile math (nearest-rank, small-sample):
  index = min(round(0.95 * (N-1)), N-1)
With N=10 that gives index 9 (i.e. sl[9]) for p99 and index 9 (sl[8]) for p95
-- more precisely p95 → sl[min(round(8.55), 9)] = sl[9] is actually the max,
so we cap to N-2 for p95 to avoid collapsing p95=max. The formula used is:
  p95 = sl[min(int(round(0.95 * (N - 1))), N - 1)]
  p99 = sl[min(int(round(0.99 * (N - 1))), N - 1)]
For N=10 this yields p95=sl[9] (2nd-highest sample = index 8... see below).

Concretely with N=10:
  0.95 * 9 = 8.55  → round → 9  → sl[9]  (which IS sl[-1], the max)
  0.99 * 9 = 8.91  → round → 9  → sl[9]  (same)
Both collapse to max with n=10. That is mathematically correct for
nearest-rank at these quantile levels with so few samples. The "p95" label
is therefore aspirational — with 10 samples the 95th percentile is
indistinguishable from the maximum. This is documented here so the reader
isn't surprised when p95 == max.

Usage:
  export FABOPS_API_URL=https://<id>.execute-api.us-east-1.amazonaws.com/getChatResponse
  python scripts/stress_cold_start.py
"""
import os
import statistics
import sys
import time

import requests

API = os.environ.get("FABOPS_API_URL")
if not API:
    print("ERROR: set FABOPS_API_URL", file=sys.stderr)
    sys.exit(1)

N = 10
latencies: list[float] = []

for i in range(N):
    t0 = time.time()
    try:
        r = requests.post(
            API,
            json={"query": f"part A{i} stockout risk?"},
            timeout=120,
        )
        status = r.status_code
    except requests.RequestException as e:
        status = f"ERR:{type(e).__name__}"
    ms = (time.time() - t0) * 1000
    latencies.append(ms)
    print(f"  {i + 1:2}/{N}: {ms:7.0f}ms  status={status}")

sl = sorted(latencies)

# Nearest-rank percentiles.  With N=10, 0.95*(N-1)=8.55 → rounds to 9 (the
# max sample).  This is correct nearest-rank behaviour for small n — see
# module docstring for explanation.
p50 = statistics.median(sl)
p95 = sl[min(int(round(0.95 * (N - 1))), N - 1)]
p99 = sl[min(int(round(0.99 * (N - 1))), N - 1)]

print(f"\nSummary (n={N}):")
print(f"  p50  {p50:7.0f}ms")
print(f"  p95  {p95:7.0f}ms")
print(f"  p99  {p99:7.0f}ms")
print(f"  max  {sl[-1]:7.0f}ms")
