from __future__ import annotations

import io
import json
import math
import zipfile
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd
import plotly.graph_objects as go

from . import config
from .text import safe_filename


def _raw_frame(df: pd.DataFrame) -> pd.DataFrame:
    raw_rows: list[dict[str, Any]] = []
    columns: list[str] = []
    seen: set[str] = set()
    for _, row in df.iterrows():
        try:
            raw = json.loads(row.get("raw_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            raw = {}
        for key in raw:
            if key not in seen:
                seen.add(key)
                columns.append(key)
        raw_rows.append(raw)
    result = pd.DataFrame(raw_rows, columns=columns)
    result = result.fillna("").astype(str)
    return result


def raw_export_frame(df: pd.DataFrame) -> pd.DataFrame:
    raw = _raw_frame(df)
    if raw.empty and len(df) == 0:
        return raw
    provenance = pd.DataFrame(
        {
            "STARLIGHT_observation_id": df["id"].astype(str).values,
            "STARLIGHT_source_file": df["source_file"].fillna("").astype(str).values,
            "STARLIGHT_source_row": df["source_row"].astype(str).values,
            "STARLIGHT_dataset_id": df["dataset_id"].astype(str).values,
            "STARLIGHT_imported_at": df["imported_at"].fillna("").astype(str).values,
            "STARLIGHT_logbook_session_id": df.get(
                "logbook_session_id", pd.Series("", index=df.index)
            )
            .fillna("")
            .astype(str)
            .values,
        },
        index=raw.index,
    )
    return pd.concat([raw, provenance], axis=1)


def analysis_export_frame(df: pd.DataFrame) -> pd.DataFrame:
    raw = raw_export_frame(df)
    derived_columns: dict[str, Any] = {
        "STARLIGHT_target_name": df.get("target_name", pd.Series("", index=df.index)).values,
        "STARLIGHT_target_key": df.get("target_key", pd.Series("", index=df.index)).values,
        "STARLIGHT_night_date": df.get("night_date", pd.Series("", index=df.index)).values,
        "STARLIGHT_night_label": df.get("night_label", pd.Series("", index=df.index)).values,
        "STARLIGHT_time_basis": df.get("time_basis", pd.Series("", index=df.index)).values,
    }
    for source, destination in (
        ("elapsed_hours", "STARLIGHT_elapsed_hours"),
        ("phase", "STARLIGHT_phase"),
        ("flag_reasons", "STARLIGHT_flags"),
        ("logbook_entry_id", "STARLIGHT_logbook_entry_id"),
    ):
        if source in df:
            derived_columns[destination] = df[source].values
    derived = pd.DataFrame(derived_columns, index=raw.index)
    return pd.concat([raw, derived], axis=1)


def dataframe_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, na_rep="").encode("utf-8-sig")


def dataframe_json_bytes(df: pd.DataFrame) -> bytes:
    return df.to_json(orient="records", indent=2, force_ascii=False).encode("utf-8")


def figure_html_bytes(figure: go.Figure, *, include_plotlyjs: str = "inline") -> bytes:
    return figure.to_html(
        full_html=True,
        include_plotlyjs=include_plotlyjs,
        config={"displaylogo": False, "responsive": True},
    ).encode("utf-8")


def figure_png_bytes(figure: go.Figure) -> bytes | None:
    try:
        return figure.to_image(format="png", scale=2)
    except Exception:
        return None


def metadata_payload(
    *,
    target: str | None = None,
    period_days: float | None = None,
    epoch_jd: float | None = None,
    thresholds: Mapping[str, Any] | None = None,
    datasets: list[dict[str, Any]] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "application": config.APP_NAME,
        "version": config.APP_VERSION,
        "generated_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "target": target,
        "period_days": period_days,
        "epoch_jd": epoch_jd,
        "thresholds": dict(thresholds or {}),
        "datasets": datasets or [],
        "preservation_policy": (
            "Raw Seestar values are preserved unchanged. No night-to-night offsets, "
            "median normalization, timezone corrections, or automatic detrending are applied. "
            "Phase and elapsed-time columns are derived for display only."
        ),
    }
    if extra:
        payload.update(extra)
    return payload


def bundle_filename(prefix: str = "starlight_export") -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{safe_filename(prefix, 'starlight_export')}_{stamp}.zip"


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, "item"):
        return _json_safe(value.item())
    return value


def zip_bundle(files: Mapping[str, bytes], metadata: Mapping[str, Any]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
        archive.writestr(
            "metadata.json",
            json.dumps(_json_safe(metadata), indent=2, ensure_ascii=False).encode("utf-8"),
        )
        archive.writestr(
            "README.txt",
            (
                b"StarLight export bundle\n"
                b"=======================\n\n"
                b"This bundle preserves the raw Seestar observations and adds derived analysis "
                b"columns only where explicitly named STARLIGHT_*.\n\n"
                b"No night-to-night shifts, median offsets, timezone corrections, or automatic "
                b"detrending have been applied.\n"
            ),
        )
    return buffer.getvalue()


def csv_filename(prefix: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{safe_filename(prefix, 'starlight')}_{stamp}.csv"
