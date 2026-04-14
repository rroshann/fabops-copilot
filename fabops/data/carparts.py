"""Hyndman carparts loader + Syntetos-Boylan-Croston ADI/CV² classification."""
import os
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

# Inside the Lambda container image, /var/task is the working root and
# carparts.csv is copied to /var/task/data/. Locally, fall back to
# <repo_root>/data/carparts.csv (two levels up from this file).
_TASK_ROOT = Path(
    os.environ.get("LAMBDA_TASK_ROOT", str(Path(__file__).resolve().parents[2]))
)
DATA_PATH = _TASK_ROOT / "data" / "carparts.csv"


def load_carparts() -> pd.DataFrame:
    """Return a long-format DataFrame: part_id, month (1..51), demand (int).

    Handles both wide format (first column month, remaining columns per-part)
    and long format (already has part_id/month/demand columns).
    """
    raw = pd.read_csv(DATA_PATH)
    if "part_id" in raw.columns:
        return raw[["part_id", "month", "demand"]].reset_index(drop=True)
    # Wide format: pivot long
    id_col = raw.columns[0]
    long = raw.melt(id_vars=[id_col], var_name="part_id", value_name="demand")
    long = long.rename(columns={id_col: "month"})
    long["demand"] = long["demand"].fillna(0).astype(int)
    long["month"] = long["month"].astype(int)
    return long[["part_id", "month", "demand"]].reset_index(drop=True)


def classify_adi_cv2(df: pd.DataFrame) -> pd.DataFrame:
    """Classify each part into the Syntetos-Boylan-Croston quadrant.

    ADI = Average Demand Interval (average gap between non-zero demands)
    CV² = squared coefficient of variation of non-zero demand sizes

    Cutoffs (Syntetos & Boylan 2005):
      ADI <= 1.32  &  CV² <= 0.49  -> smooth
      ADI >  1.32  &  CV² <= 0.49  -> intermittent
      ADI <= 1.32  &  CV² >  0.49  -> erratic
      ADI >  1.32  &  CV² >  0.49  -> lumpy
    """
    out = []
    for part_id, grp in df.groupby("part_id"):
        demands = grp["demand"].to_numpy()
        nonzero = demands[demands > 0]
        if len(nonzero) == 0:
            continue
        adi = len(demands) / len(nonzero)
        cv2 = (nonzero.std() / nonzero.mean()) ** 2 if nonzero.mean() > 0 else 0.0
        cls = _classify(adi, cv2)
        out.append({"part_id": part_id, "adi": adi, "cv2": cv2, "class": cls})
    return pd.DataFrame(out)


def _classify(
    adi: float, cv2: float
) -> Literal["smooth", "intermittent", "erratic", "lumpy"]:
    if adi <= 1.32 and cv2 <= 0.49:
        return "smooth"
    if adi > 1.32 and cv2 <= 0.49:
        return "intermittent"
    if adi <= 1.32 and cv2 > 0.49:
        return "erratic"
    return "lumpy"
