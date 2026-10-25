from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from . import config
from .text import short_filename

DATE_FORMATS = (
    "%Y.%m.%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y.%m.%d %H:%M",
    "%Y-%m-%d %H:%M",
)


def jd_to_utc_datetime(jd: float | None) -> datetime | None:
    if jd is None:
        return None
    try:
        value = float(jd)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(value):
        return None
    try:
        return datetime.fromtimestamp(
            (value - config.JD_ORIGIN_UNIX) * 86400.0, tz=UTC
        ).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None


def _parse_local_datetime(values: pd.Series) -> pd.Series:
    parsed = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    for fmt in DATE_FORMATS:
        current = pd.to_datetime(values, format=fmt, errors="coerce")
        parsed = parsed.where(parsed.notna(), current)
    return parsed


def prepare_observations(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    data = df.copy()
    numeric_columns = [
        "mag_obs",
        "mag_err",
        "jd_start",
        "jd_end",
        "snr",
        "ra",
        "dec",
        "exp_seconds",
        "valid_ref_stars",
    ]
    for column in numeric_columns:
        if column in data:
            data[column] = pd.to_numeric(data[column], errors="coerce")

    local = _parse_local_datetime(data.get("local_start", pd.Series(index=data.index, dtype=object)))
    utc = data.get("jd_start", pd.Series(index=data.index, dtype=float)).map(jd_to_utc_datetime)
    utc = pd.to_datetime(pd.Series(utc, index=data.index), errors="coerce")
    data["local_datetime"] = local
    data["utc_datetime"] = utc
    data["display_datetime"] = local.where(local.notna(), utc)
    data["time_basis"] = np.where(local.notna(), "Local EXP start", "UTC from JD")

    display_date = data["display_datetime"].dt.strftime("%Y-%m-%d")
    data["night_date"] = display_date.fillna("unknown-date")
    source_file = data.get("source_file", pd.Series("", index=data.index)).astype(str)
    dataset_id = data.get("dataset_id", pd.Series("", index=data.index)).astype(str)
    data["night_key"] = dataset_id + "|" + data["night_date"]
    data["night_label"] = (
        data["night_date"] + " · " + source_file.map(lambda value: short_filename(value, 34))
    )
    data["target_key"] = data.get("target_key", pd.Series("", index=data.index)).fillna("")
    data["target_name"] = data.get("target_name", pd.Series("", index=data.index)).fillna("")
    data["parse_flags"] = data.get("parse_flags", pd.Series("", index=data.index)).fillna("")
    data = data.sort_values(
        ["target_key", "jd_start", "source_file", "source_row"], kind="stable"
    ).reset_index(drop=True)
    return data


def add_elapsed(df: pd.DataFrame, mode: str = "global") -> pd.DataFrame:
    if df.empty:
        return df.copy()
    data = df.copy()
    if mode == "per_night":
        data["night_start_jd"] = data.groupby(["target_key", "night_key"], dropna=False)[
            "jd_start"
        ].transform("min")
    else:
        data["night_start_jd"] = data.groupby("target_key", dropna=False)["jd_start"].transform(
            "min"
        )
    data["elapsed_hours"] = (data["jd_start"] - data["night_start_jd"]) * 24.0
    return data


def phase_fold(df: pd.DataFrame, period_days: float, epoch_jd: float = 0.0) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    try:
        period = float(period_days)
        epoch = float(epoch_jd or 0.0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Period and epoch must be numeric.") from exc
    if not np.isfinite(period) or period <= 0:
        raise ValueError("Period must be greater than zero.")
    data = df.copy()
    data["phase"] = ((data["jd_start"] - epoch) / period) % 1.0
    data["phase_cycle"] = data["phase"]
    return data


def compute_quality_flags(
    df: pd.DataFrame,
    *,
    snr_min: float = config.DEFAULT_SNR_MIN,
    mag_err_max: float = config.DEFAULT_MAG_ERR_MAX,
    spike_sigma: float = config.DEFAULT_SPIKE_SIGMA,
    spike_min_delta: float = config.DEFAULT_SPIKE_MIN_DELTA,
    spike_window: int = config.SPIKE_WINDOW_POINTS,
) -> pd.DataFrame:
    if df.empty:
        data = df.copy()
        data["flag_reasons"] = ""
        data["is_flagged"] = False
        return data

    data = df.copy().reset_index(drop=True)
    reasons: list[list[str]] = []
    for _, row in data.iterrows():
        current: list[str] = []
        for text in str(row.get("parse_flags") or "").split(";"):
            text = text.strip()
            if text:
                current.append(text)
        if pd.isna(row.get("mag_obs")):
            current.append("missing magnitude")
        if pd.isna(row.get("mag_err")):
            current.append("missing magnitude error")
        elif float(row["mag_err"]) <= 0:
            current.append("non-positive magnitude error")
        elif float(row["mag_err"]) > mag_err_max:
            current.append(f"mag error > {mag_err_max:g}")
        if pd.isna(row.get("snr")):
            current.append("missing SNR")
        elif float(row["snr"]) < snr_min:
            current.append(f"SNR < {snr_min:g}")
        if pd.isna(row.get("jd_start")):
            current.append("missing JD")
        reasons.append(list(dict.fromkeys(current)))

    duplicate_mask = pd.Series(False, index=data.index)
    valid_jd = data["jd_start"].notna()
    if valid_jd.any():
        for index in data[valid_jd].groupby(
            ["target_key", "night_key"], dropna=False
        ).groups.values():
            rounded = data.loc[index, "jd_start"].round(6)
            duplicated = rounded.duplicated(keep=False)
            if duplicated.any():
                duplicate_mask.loc[index] = duplicate_mask.loc[index] | duplicated
    for index in data.index[duplicate_mask]:
        reasons[index].append("duplicate timestamp")

    for _, group in data.groupby(["target_key", "night_key"], dropna=False, sort=False):
        if len(group) < 3:
            continue
        ordered = group.sort_values("jd_start")
        magnitudes = ordered["mag_obs"].to_numpy(dtype=float)
        positions = list(ordered.index)
        half = max(1, int(spike_window) // 2)
        for position, index in enumerate(positions):
            if not np.isfinite(magnitudes[position]):
                continue
            start = max(0, position - half)
            stop = min(len(magnitudes), position + half + 1)
            neighbours = np.concatenate(
                [magnitudes[start:position], magnitudes[position + 1 : stop]]
            )
            neighbours = neighbours[np.isfinite(neighbours)]
            if len(neighbours) < 2:
                continue
            median = float(np.median(neighbours))
            mad = float(np.median(np.abs(neighbours - median)))
            threshold = max(spike_sigma * 1.4826 * mad, spike_min_delta)
            if abs(magnitudes[position] - median) > threshold:
                reasons[index].append("possible spike (review; may be real variability)")

    data["flag_reasons"] = ["; ".join(list(dict.fromkeys(items))) for items in reasons]
    data["is_flagged"] = data["flag_reasons"].str.len() > 0
    return data


def flag_counts(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["flag", "count"])
    counts: dict[str, int] = {}
    for value in df.get("flag_reasons", pd.Series("", index=df.index)).fillna(""):
        for item in str(value).split(";"):
            item = item.strip()
            if item:
                counts[item] = counts.get(item, 0) + 1
    return (
        pd.DataFrame(sorted(counts.items(), key=lambda item: (-item[1], item[0])), columns=["flag", "count"])
        if counts
        else pd.DataFrame(columns=["flag", "count"])
    )


def describe_jd_range(jd_min: float | None, jd_max: float | None) -> str:
    if jd_min is None or jd_max is None:
        return "unknown"
    return f"JD {jd_min:.6f} – {jd_max:.6f}"


def format_datetime_range(values: Iterable) -> str:
    parsed = [value for value in values if value is not None and not pd.isna(value)]
    if not parsed:
        return ""
    start = min(parsed)
    end = max(parsed)
    start_text = pd.Timestamp(start).strftime("%Y-%m-%d %H:%M:%S")
    end_text = pd.Timestamp(end).strftime("%H:%M:%S") if pd.Timestamp(start).date() == pd.Timestamp(end).date() else pd.Timestamp(end).strftime("%Y-%m-%d %H:%M:%S")
    return f"{start_text} – {end_text}"
