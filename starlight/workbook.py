from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

import pandas as pd

from . import config, database, resources
from .text import (
    clean_text,
    normalize_target_key,
    parse_bool,
    parse_float,
    parse_int,
    parse_seconds,
    stringify,
)

TARGET_SHEET = "Target Catalog"
PLAN_SHEET = "Annual Plan"
LOG_SHEET = "Observation Log"
REFERENCES_SHEET = "References"
README_SHEET = "Read Me"

OBSERVATION_LOG_COLUMNS = [
    "Session ID",
    "Target",
    "Date (local)",
    "Start time (local)",
    "End time (local)",
    "Time standard in CSV (JD/BJD/UTC/other)",
    "Filter",
    "Exposure (s)",
    "Frames / points",
    "Seestar mode/settings",
    "Sky transparency",
    "Seeing / focus",
    "Moon / conditions",
    "CSV filename",
    "Notes / issues",
    "Processed?",
]


def _read_excel(source: Any, sheet: str) -> pd.DataFrame:
    if hasattr(source, "seek"):
        source.seek(0)
    try:
        frame = pd.read_excel(source, sheet_name=sheet, dtype=object)
    except ValueError:
        return pd.DataFrame()
    frame.columns = [clean_text(column) for column in frame.columns]
    return frame


def _period_from_text(text: str, target_key: str) -> float | None:
    configured = config.CATALOG_PERIOD_DAYS.get(target_key)
    if configured is not None:
        return float(configured)
    value = clean_text(text).casefold()
    if not value:
        return None
    minutes = re.search(r"([\d.]+)\s*(?:min|minutes)", value)
    if minutes:
        try:
            return float(minutes.group(1)) / 1440.0
        except ValueError:
            pass
    days = re.search(r"([\d.]+)\s*(?:d\b|day|days)", value)
    if days:
        try:
            return float(days.group(1))
        except ValueError:
            pass
    return None


def _import_target_catalog(frame: pd.DataFrame) -> int:
    if frame.empty or "Target" not in frame.columns:
        return 0
    count = 0
    for _, row in frame.iterrows():
        target_name = clean_text(row.get("Target"))
        if not target_name:
            continue
        target_key = normalize_target_key(target_name)
        period_text = clean_text(row.get("Period / timescale"))
        period_days = _period_from_text(period_text, target_key)
        database.upsert_catalog_target(
            {
                "target_key": target_key,
                "target_name": target_name,
                "common_designation": clean_text(row.get("Common designation")),
                "variable_type": clean_text(row.get("Variable type")),
                "constellation": clean_text(row.get("Constellation")),
                "brightness_range": clean_text(row.get("Approx. brightness range")),
                "period_days": period_days,
                "period_timescale": period_text,
                "season": clean_text(row.get("Season from Tampa (approx.)")),
                "session_length": clean_text(row.get("Session length")),
                "cadence": clean_text(row.get("Cadence / schedule")),
                "project_goal": clean_text(row.get("Project goal")),
                "notes": clean_text(row.get("Notes / caveats")),
            }
        )
        count += 1
    database.seed_aliases()
    database.apply_catalog_period_defaults()
    return count


def _import_annual_plan(frame: pd.DataFrame) -> int:
    if frame.empty or "When" not in frame.columns:
        return 0
    rows: list[tuple[str, ...]] = []
    for _, row in frame.iterrows():
        values = (
            stringify(row.get("When")),
            stringify(row.get("Primary target(s)")),
            stringify(row.get("What to do")),
            stringify(row.get("Time per target")),
            stringify(row.get("Repeat cadence")),
            stringify(row.get("Deliverable / milestone")),
            stringify(row.get("Priority")),
        )
        if not any(values):
            continue
        rows.append(values)
    with database.connect() as conn:
        conn.execute("DELETE FROM annual_plan")
        conn.executemany(
            """
            INSERT INTO annual_plan(
                when_text, primary_targets, what_to_do, time_per_target,
                repeat_cadence, deliverable, priority
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    return len(rows)


def _import_references(frame: pd.DataFrame) -> int:
    if frame.empty or "URL" not in frame.columns:
        return 0
    count = 0
    for _, row in frame.iterrows():
        url = clean_text(row.get("URL"))
        label = clean_text(row.get("Resource")) or url
        if not url:
            continue
        database.upsert_resource(
            {
                "target_key": None,
                "label": label,
                "url": url,
                "category": "Reference",
                "notes": clean_text(row.get("Use")),
                "source": "Tampa workbook",
            }
        )
        count += 1
    return count


def _logbook_exists(
    target_key: str,
    date_local: str,
    start_local: str,
    end_local: str,
    session_id: str,
) -> bool:
    if session_id:
        with database.connect() as conn:
            if conn.execute(
                "SELECT 1 FROM logbook_entries WHERE session_id = ?", (session_id,)
            ).fetchone():
                return True
    with database.connect() as conn:
        return (
            conn.execute(
                """
                SELECT 1 FROM logbook_entries
                WHERE target_key = ? AND IFNULL(date_local, '') = ? AND
                      IFNULL(start_local, '') = ? AND IFNULL(end_local, '') = ?
                LIMIT 1
                """,
                (target_key, date_local, start_local, end_local),
            ).fetchone()
            is not None
        )


def _import_observation_log(frame: pd.DataFrame) -> int:
    if frame.empty or "Target" not in frame.columns:
        return 0
    count = 0
    for _, row in frame.iterrows():
        values = [stringify(row.get(column)) for column in OBSERVATION_LOG_COLUMNS]
        if not any(values):
            continue
        target_name = clean_text(row.get("Target"))
        if not target_name:
            continue
        target_key = database.resolve_alias_key(normalize_target_key(target_name))
        date_local = stringify(row.get("Date (local)"))
        start_local = stringify(row.get("Start time (local)"))
        end_local = stringify(row.get("End time (local)"))
        session_id = clean_text(row.get("Session ID"))
        if _logbook_exists(target_key, date_local, start_local, end_local, session_id):
            continue
        database.create_logbook_entry(
            {
                "session_id": session_id,
                "target_name": target_name,
                "target_key": target_key,
                "date_local": date_local,
                "start_local": start_local,
                "end_local": end_local,
                "time_standard": clean_text(row.get("Time standard in CSV (JD/BJD/UTC/other)")),
                "filter": clean_text(row.get("Filter")),
                "exposure_s": parse_float(row.get("Exposure (s)"))
                or parse_seconds(row.get("Exposure (s)")),
                "frames": parse_int(row.get("Frames / points")),
                "settings": clean_text(row.get("Seestar mode/settings")),
                "transparency": clean_text(row.get("Sky transparency")),
                "seeing": clean_text(row.get("Seeing / focus")),
                "moon": clean_text(row.get("Moon / conditions")),
                "csv_filename": clean_text(row.get("CSV filename")),
                "notes": clean_text(row.get("Notes / issues")),
                "processed": bool(parse_bool(row.get("Processed?"))),
            }
        )
        count += 1
    return count


def import_workbook(source: Any = None) -> dict[str, int]:
    source = source or config.WORKBOOK_PATH
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    if isinstance(source, Path) and not source.exists():
        raise FileNotFoundError(f"Workbook not found: {source}")
    counts = {
        "targets": _import_target_catalog(_read_excel(source, TARGET_SHEET)),
        "annual_plan_rows": _import_annual_plan(_read_excel(source, PLAN_SHEET)),
        "logbook_entries": _import_observation_log(_read_excel(source, LOG_SHEET)),
        "references": _import_references(_read_excel(source, REFERENCES_SHEET)),
    }
    resources.ensure_default_resources()
    database.set_setting("workbook_seeded", "1")
    return counts


def seed_if_needed(*, force: bool = False) -> dict[str, int] | None:
    marker = database.get_setting("workbook_seeded")
    if marker and not force:
        return None
    if not config.WORKBOOK_PATH.exists():
        database.set_setting("workbook_seeded", "1")
        return None
    return import_workbook(config.WORKBOOK_PATH)


def _observation_log_export() -> pd.DataFrame:
    entries = database.list_logbook_entries()
    if entries.empty:
        return pd.DataFrame(columns=OBSERVATION_LOG_COLUMNS)
    rows: list[dict[str, Any]] = []
    for _, row in entries.iterrows():
        rows.append(
            {
                "Session ID": row.get("session_id", ""),
                "Target": row.get("target_name", ""),
                "Date (local)": row.get("date_local", ""),
                "Start time (local)": row.get("start_local", ""),
                "End time (local)": row.get("end_local", ""),
                "Time standard in CSV (JD/BJD/UTC/other)": row.get("time_standard", ""),
                "Filter": row.get("filter", ""),
                "Exposure (s)": row.get("exposure_s", ""),
                "Frames / points": row.get("frames", ""),
                "Seestar mode/settings": row.get("settings", ""),
                "Sky transparency": row.get("transparency", ""),
                "Seeing / focus": row.get("seeing", ""),
                "Moon / conditions": row.get("moon", ""),
                "CSV filename": row.get("csv_filename", ""),
                "Notes / issues": row.get("notes", ""),
                "Processed?": "Yes" if row.get("processed") else "No",
            }
        )
    return pd.DataFrame(rows, columns=OBSERVATION_LOG_COLUMNS)


def _target_catalog_export() -> pd.DataFrame:
    catalog = database.get_catalog()
    if catalog.empty:
        return pd.DataFrame()
    mapping = [
        ("target_name", "Target"),
        ("common_designation", "Common designation"),
        ("variable_type", "Variable type"),
        ("constellation", "Constellation"),
        ("brightness_range", "Approx. brightness range"),
        ("period_timescale", "Period / timescale"),
        ("season", "Season from Tampa (approx.)"),
        ("session_length", "Session length"),
        ("cadence", "Cadence / schedule"),
        ("project_goal", "Project goal"),
        ("notes", "Notes / caveats"),
    ]
    output = pd.DataFrame()
    for source, destination in mapping:
        output[destination] = catalog.get(source, "")
    return output


def _annual_plan_export() -> pd.DataFrame:
    plan = database.get_annual_plan()
    if plan.empty:
        return pd.DataFrame(
            columns=[
                "When",
                "Primary target(s)",
                "What to do",
                "Time per target",
                "Repeat cadence",
                "Deliverable / milestone",
                "Priority",
            ]
        )
    mapping = [
        ("when_text", "When"),
        ("primary_targets", "Primary target(s)"),
        ("what_to_do", "What to do"),
        ("time_per_target", "Time per target"),
        ("repeat_cadence", "Repeat cadence"),
        ("deliverable", "Deliverable / milestone"),
        ("priority", "Priority"),
    ]
    return pd.DataFrame({destination: plan.get(source, "") for source, destination in mapping})


def _references_export() -> pd.DataFrame:
    rows = []
    for item in database.get_resources():
        if item.get("target_key"):
            continue
        rows.append(
            {
                "Resource": item.get("label", ""),
                "Use": item.get("notes", ""),
                "URL": item.get("url", ""),
            }
        )
    return pd.DataFrame(rows, columns=["Resource", "Use", "URL"])


def export_workbook_bytes() -> bytes:
    buffer = io.BytesIO()
    read_me = pd.DataFrame(
        {
            "StarLight observing logbook export": [
                "Raw Seestar observations remain in the StarLight database and exports.",
                "This workbook contains the logbook, target catalog, annual plan, and references.",
                "No night-to-night alignment or automatic photometry correction is applied by StarLight.",
                f"Exported at {database.utc_now()}.",
            ]
        }
    )
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        read_me.to_excel(writer, sheet_name=README_SHEET, index=False)
        _target_catalog_export().to_excel(writer, sheet_name=TARGET_SHEET, index=False)
        _annual_plan_export().to_excel(writer, sheet_name=PLAN_SHEET, index=False)
        _observation_log_export().to_excel(writer, sheet_name=LOG_SHEET, index=False)
        _references_export().to_excel(writer, sheet_name=REFERENCES_SHEET, index=False)
        for worksheet in writer.sheets.values():
            worksheet.freeze_panes = "A2"
            for column_cells in worksheet.columns:
                width = min(
                    55,
                    max(12, max(len(stringify(cell.value)) for cell in column_cells) + 2),
                )
                worksheet.column_dimensions[column_cells[0].column_letter].width = width
    return buffer.getvalue()


def logbook_export_frame() -> pd.DataFrame:
    return _observation_log_export()
