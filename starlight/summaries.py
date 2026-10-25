from __future__ import annotations

import numpy as np
import pandas as pd

from .transforms import format_datetime_range


def _weighted_mean(values: pd.Series, errors: pd.Series) -> float | None:
    valid = values.notna() & errors.notna() & (errors > 0)
    if not valid.any():
        return None
    weights = 1.0 / (errors[valid].astype(float) ** 2)
    return float(np.average(values[valid].astype(float), weights=weights))


def summarize(df: pd.DataFrame, *, by_night: bool = False) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    data = df.copy()
    if "night_key" not in data:
        data["night_key"] = data.get("dataset_id", "").astype(str) + "|" + data.get(
            "local_start", ""
        ).astype(str)
    if "night_label" not in data:
        data["night_label"] = data["night_key"]
    if "local_datetime" not in data:
        data["local_datetime"] = pd.NaT
    if "is_flagged" not in data:
        data["is_flagged"] = False

    group_columns = ["target_key", "target_name"]
    if by_night:
        group_columns.extend(["night_key", "night_label"])

    rows: list[dict] = []
    for keys, group in data.groupby(group_columns, dropna=False, sort=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        target_key, target_name = keys[0], keys[1]
        mags = group["mag_obs"].dropna().astype(float)
        errors = group["mag_err"].dropna().astype(float)
        snrs = group["snr"].dropna().astype(float)
        exposure = group.get("exp_seconds", pd.Series(dtype=float)).dropna()
        refs = group.get("valid_ref_stars", pd.Series(dtype=float)).dropna()
        jd = group["jd_start"].dropna().astype(float)
        local_times = group["local_datetime"].dropna()
        sources = sorted(
            {str(value) for value in group.get("source_file", pd.Series(dtype=str)).dropna() if str(value)}
        )
        night_count = group["night_key"].nunique(dropna=True)
        duration = float((jd.max() - jd.min()) * 24.0) if len(jd) > 1 else 0.0
        row = {
            "Target": target_name,
            "Target key": target_key,
            "Observations": int(len(group)),
            "Nights": int(night_count) if not by_night else 1,
            "Local start": (
                pd.Timestamp(local_times.min()).strftime("%Y-%m-%d %H:%M:%S")
                if not local_times.empty
                else ""
            ),
            "Local end": (
                pd.Timestamp(local_times.max()).strftime("%Y-%m-%d %H:%M:%S")
                if not local_times.empty
                else ""
            ),
            "Date range": format_datetime_range(local_times.tolist()),
            "JD min": float(jd.min()) if not jd.empty else None,
            "JD max": float(jd.max()) if not jd.empty else None,
            "Duration (h)": duration,
            "Min mag": float(mags.min()) if not mags.empty else None,
            "Max mag": float(mags.max()) if not mags.empty else None,
            "Range (mag)": float(mags.max() - mags.min()) if not mags.empty else None,
            "Median mag": float(mags.median()) if not mags.empty else None,
            "Mean mag": float(mags.mean()) if not mags.empty else None,
            "Std dev (mag)": float(mags.std(ddof=1)) if len(mags) > 1 else None,
            "Weighted mean mag": _weighted_mean(group["mag_obs"], group["mag_err"]),
            "Median error": float(errors.median()) if not errors.empty else None,
            "Mean error": float(errors.mean()) if not errors.empty else None,
            "Mean SNR": float(snrs.mean()) if not snrs.empty else None,
            "Min SNR": float(snrs.min()) if not snrs.empty else None,
            "Exposure (s)": float(exposure.median()) if not exposure.empty else None,
            "Ref stars": float(refs.median()) if not refs.empty else None,
            "Flagged": int(group["is_flagged"].fillna(False).sum()),
            "Sources": "; ".join(sources),
        }
        if by_night:
            row["Night"] = keys[3] if len(keys) > 3 else ""
            row["Night key"] = keys[2] if len(keys) > 2 else ""
        rows.append(row)
    result = pd.DataFrame(rows)
    if by_night and not result.empty:
        result = result[
            [
                "Target",
                "Night",
                "Observations",
                "Local start",
                "Local end",
                "Duration (h)",
                "Min mag",
                "Max mag",
                "Range (mag)",
                "Median mag",
                "Weighted mean mag",
                "Median error",
                "Mean SNR",
                "Min SNR",
                "Flagged",
                "Sources",
            ]
        ]
    return result


def summary_totals(df: pd.DataFrame) -> dict[str, float | int | str]:
    if df.empty:
        return {
            "observations": 0,
            "targets": 0,
            "nights": 0,
            "flagged": 0,
            "sources": 0,
        }
    return {
        "observations": int(len(df)),
        "targets": int(df["target_key"].nunique()),
        "nights": int(df["night_key"].nunique()) if "night_key" in df else 0,
        "flagged": int(df["is_flagged"].fillna(False).sum()) if "is_flagged" in df else 0,
        "sources": int(df["dataset_id"].nunique()) if "dataset_id" in df else 0,
    }
