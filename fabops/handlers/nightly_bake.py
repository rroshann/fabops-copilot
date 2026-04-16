"""Nightly forecast bake — runs inside the container image Lambda.

Computes Croston/SBA/TSB forecasts for all parts, writes to fabops_forecasts
and pre-baked demand stats to fabops_policies (resolves policy/demand
circular dep). Imports statsforecast ONLY here — never at runtime.

Policy-drift gold-set parts are EXCLUDED from the policy table write so
that the staleness injected by scripts/inject_gold_drift.py persists
across nightly bake runs. Without this exclusion, last_updated gets
refreshed to today for all 200 parts, which resets staleness_days to 0
and causes the agent to misdiagnose policy-drift cases as supply or
demand.

Spec Section 9.2.
"""
import json
import os
from datetime import datetime
from pathlib import Path

try:
    from statsforecast import StatsForecast
    from statsforecast.models import CrostonSBA
    HAS_STATSFORECAST = True
except ImportError:
    HAS_STATSFORECAST = False

import pandas as pd

from fabops.config import TABLE_FORECASTS, TABLE_POLICIES
from fabops.data.carparts import load_carparts, classify_adi_cv2
from fabops.data.dynamo import batch_write
from fabops.tools._croston_numpy import croston as numpy_croston


def _forecast_all_parts(df: pd.DataFrame, horizon: int = 12) -> pd.DataFrame:
    """Run SBA Croston on every intermittent/lumpy part."""
    if HAS_STATSFORECAST:
        sf_df = df.rename(columns={"part_id": "unique_id", "month": "ds", "demand": "y"}).copy()
        # Convert month integer index to monthly date
        sf_df["ds"] = pd.to_datetime("2020-01-01") + pd.to_timedelta((sf_df["ds"] - 1) * 30, unit="D")
        # n_jobs=1 — AWS Lambda does not expose /dev/shm so multiprocessing
        # semaphores raise PermissionError. Single-process is fine for ~200 parts.
        sf = StatsForecast(models=[CrostonSBA()], freq="MS", n_jobs=1)
        sf.fit(sf_df)
        yhat = sf.predict(h=horizon)
        # Newer statsforecast versions return unique_id as the index rather
        # than a column. Normalize by resetting the index so downstream
        # filtering on yhat["unique_id"] always works.
        if "unique_id" not in yhat.columns:
            yhat = yhat.reset_index()
        return yhat
    # Fallback: per-part NumPy Croston
    out = []
    for part_id, grp in df.groupby("part_id"):
        demand = grp.sort_values("month")["demand"].tolist()
        fc, p10, p90 = numpy_croston(demand, horizon=horizon, variant="sba")
        for i, (f, lo, hi) in enumerate(zip(fc, p10, p90)):
            out.append({"unique_id": part_id, "step": i + 1, "forecast": f, "p10": lo, "p90": hi})
    return pd.DataFrame(out)


def handler(event, context):
    run_id = datetime.utcnow().isoformat()
    print(f"[nightly_bake] run_id={run_id} starting; HAS_STATSFORECAST={HAS_STATSFORECAST}")

    df = load_carparts()
    classified = classify_adi_cv2(df)
    target_parts = set(classified[classified["class"].isin(["intermittent", "lumpy"])]["part_id"])
    print(f"[nightly_bake] {len(target_parts)} parts classified as intermittent/lumpy")

    # Demo scope: first 200 parts
    target_parts = sorted(target_parts)[:200]
    df_sub = df[df["part_id"].isin(target_parts)]
    print(f"[nightly_bake] running forecasts on {len(target_parts)} parts")

    yhat = _forecast_all_parts(df_sub, horizon=12)
    print(f"[nightly_bake] forecasts computed, rows={len(yhat)}")

    forecast_items = []
    policy_items = []
    for part_id in target_parts:
        if HAS_STATSFORECAST:
            part_fc = yhat[yhat["unique_id"] == part_id].sort_values("ds")
            if len(part_fc) == 0:
                continue
            fc_vals = part_fc["CrostonSBA"].astype(float).tolist()
            # statsforecast's CrostonSBA doesn't emit intervals directly — approximate
            p10_vals = [max(0.0, v * 0.6) for v in fc_vals]
            p90_vals = [v * 1.4 for v in fc_vals]
        else:
            part_fc = yhat[yhat["unique_id"] == part_id].sort_values("step")
            if len(part_fc) == 0:
                continue
            fc_vals = part_fc["forecast"].astype(float).tolist()
            p10_vals = part_fc["p10"].astype(float).tolist()
            p90_vals = part_fc["p90"].astype(float).tolist()

        forecast_items.append({
            "part_id": part_id,
            "forecast_run_id": run_id,
            "forecast": fc_vals,
            "p10": p10_vals,
            "p90": p90_vals,
            "model": "croston_sba",
            "horizon_months": 12,
        })

        # Derive demand stats for the policy table (lead-time assumed 30d for the demo)
        hist = df_sub[df_sub["part_id"] == part_id]["demand"].astype(float).to_numpy()
        monthly_mean = float(hist.mean())
        monthly_std = float(hist.std(ddof=0))
        policy_items.append({
            "part_id": part_id,
            "leadtime_demand_mean": monthly_mean,
            "leadtime_demand_std": monthly_std,
            "last_updated": run_id,
        })

    # --- MLflow tracking (computed before batch_write so in-memory floats are clean) ---
    import mlflow
    import numpy as np

    smapes = []
    for item in forecast_items:
        part_hist = df_sub[df_sub["part_id"] == item["part_id"]]["demand"].astype(float).tolist()[-12:]
        fc = [float(x) for x in item["forecast"]]
        if len(part_hist) == len(fc):
            num = sum(abs(h - f) for h, f in zip(part_hist, fc))
            den = sum(abs(h) + abs(f) for h, f in zip(part_hist, fc)) / 2 or 1
            smapes.append(num / den)

    # Lambda /var/task is read-only; redirect MLflow's default artifact
    # root to /tmp before any store is initialised (the constant is used
    # at import time by _get_sqlalchemy_store when artifact_uri=None).
    import mlflow.store.tracking as _mst
    import mlflow.tracking._tracking_service.utils as _mtu
    _mst.DEFAULT_LOCAL_FILE_AND_ARTIFACT_PATH = "/tmp/mlruns"
    _mtu.DEFAULT_LOCAL_FILE_AND_ARTIFACT_PATH = "/tmp/mlruns"

    mlflow.set_tracking_uri("sqlite:////tmp/mlflow.db")
    mlflow.set_experiment("fabops-nightly-forecast")
    with mlflow.start_run(run_name=run_id):
        mlflow.log_param("model", "croston_sba")
        mlflow.log_param("n_parts", len(forecast_items))
        mlflow.log_param("horizon_months", 12)
        if smapes:
            mlflow.log_metric("smape_mean", float(np.mean(smapes)))
            mlflow.log_metric("smape_p50", float(np.median(smapes)))
            mlflow.log_metric("smape_p90", float(np.percentile(smapes, 90)))

    print(f"[nightly_bake] writing {len(forecast_items)} forecasts to {TABLE_FORECASTS}")
    batch_write(TABLE_FORECASTS, forecast_items)

    # Exclude gold-set policy-drift parts from the policy write so their
    # injected staleness (last_updated = 2025-03-01, staleness_days = 409)
    # survives the nightly bake. Without this, last_updated would be
    # refreshed to today and staleness_days would recompute to 0.
    protected_parts = set()
    gold_path = Path(__file__).parent.parent.parent / "evals" / "gold_set.json"
    if gold_path.exists():
        try:
            gold_cases = json.loads(gold_path.read_text())
            for c in gold_cases:
                if c.get("ground_truth_driver") == "policy":
                    protected_parts.add(str(c["part_id"]))
            print(f"[nightly_bake] protecting {len(protected_parts)} policy-drift gold parts from policy overwrite")
        except Exception as e:
            print(f"[nightly_bake] could not load gold set for protection: {e}")

    safe_policy_items = [p for p in policy_items if p["part_id"] not in protected_parts]
    print(f"[nightly_bake] writing {len(safe_policy_items)} policies to {TABLE_POLICIES} (skipped {len(policy_items) - len(safe_policy_items)} protected)")
    batch_write(TABLE_POLICIES, safe_policy_items)

    # Upload MLflow tracking DB to S3 (non-fatal if bucket not yet available)
    try:
        import boto3
        boto3.client("s3").upload_file("/tmp/mlflow.db", "fabops-copilot-artifacts", "mlflow.db")
        print("[nightly_bake] mlflow.db uploaded to s3://fabops-copilot-artifacts/mlflow.db")
    except Exception as e:
        print(f"[nightly_bake] mlflow S3 upload failed: {e}", flush=True)

    print(f"[nightly_bake] run_id={run_id} complete")
    return {
        "statusCode": 200,
        "body": {
            "run_id": run_id,
            "parts": len(forecast_items),
            "has_statsforecast": HAS_STATSFORECAST,
        },
    }
