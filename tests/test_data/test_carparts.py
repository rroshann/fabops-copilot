"""Test the carparts loader returns a clean long-format DataFrame."""
from fabops.data.carparts import load_carparts, classify_adi_cv2


def test_load_carparts_returns_long_format():
    df = load_carparts()
    assert list(df.columns) == ["part_id", "month", "demand"]
    assert 2670 <= df["part_id"].nunique() <= 2680
    assert df.groupby("part_id")["month"].count().min() == 51
    assert df["demand"].min() >= 0
    assert df["demand"].dtype.kind in ("i", "f")


def test_classify_adi_cv2_quadrant():
    df = load_carparts()
    classified = classify_adi_cv2(df)
    assert set(classified["class"].unique()).issubset(
        {"smooth", "intermittent", "erratic", "lumpy"}
    )
    # Most car parts are intermittent or lumpy per the literature
    intermittent_or_lumpy = classified["class"].isin(["intermittent", "lumpy"]).sum()
    assert intermittent_or_lumpy > classified.shape[0] * 0.5
