from __future__ import annotations

import io

import pandas as pd

from starlight import database, workbook


def test_bundled_workbook_import_and_export(temp_data):
    counts = workbook.import_workbook()

    assert counts["targets"] >= 1
    assert counts["annual_plan_rows"] >= 1
    assert counts["logbook_entries"] == 0
    assert counts["references"] >= 1
    assert not database.get_catalog().empty
    assert not database.get_annual_plan().empty

    catalog = database.get_catalog()
    dy_peg = catalog.loc[catalog["target_name"] == "DY Pegasi"].iloc[0]
    assert abs(float(dy_peg["period_days"]) - 105.0 / 1440.0) < 1e-9
    assert database.resolve_alias_key("DY Peg") == "dy pegasi"

    exported = workbook.export_workbook_bytes()
    assert exported.startswith(b"PK")
    excel = pd.ExcelFile(io.BytesIO(exported), engine="openpyxl")
    assert set(excel.sheet_names) == {
        "Read Me",
        "Target Catalog",
        "Annual Plan",
        "Observation Log",
        "References",
    }


def test_observation_log_rows_are_imported_once(temp_data):
    log = pd.DataFrame(
        [
            {
                "Session ID": "S-manual-1",
                "Target": "DY Pegasi",
                "Date (local)": "2026-10-22",
                "Start time (local)": "21:29:46",
                "End time (local)": "22:52:26",
                "Time standard in CSV (JD/BJD/UTC/other)": "Local",
                "Filter": "Unfiltered",
                "Exposure (s)": 30,
                "Frames / points": 163,
                "Seestar mode/settings": "Seestar",
                "Sky transparency": "Clear",
                "Seeing / focus": "Good",
                "Moon / conditions": "No moon",
                "CSV filename": "sample.csv",
                "Notes / issues": "Imported from workbook",
                "Processed?": "No",
            }
        ]
    )
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        log.to_excel(writer, sheet_name="Observation Log", index=False)

    counts = workbook.import_workbook(buffer.getvalue())
    assert counts["logbook_entries"] == 1
    entry = database.list_logbook_entries().iloc[0]
    assert entry["session_id"] == "S-manual-1"
    assert entry["target_key"] == "dy pegasi"
    assert entry["frames"] == 163

    again = workbook.import_workbook(buffer.getvalue())
    assert again["logbook_entries"] == 0
    assert len(database.list_logbook_entries()) == 1


def test_workbook_import_is_idempotent_before_export(temp_data):
    first = workbook.import_workbook()
    entry_count = len(database.list_logbook_entries())
    catalog_name = database.get_catalog_target("dy pegasi")["target_name"]

    second = workbook.import_workbook()

    assert second["logbook_entries"] == 0
    assert len(database.list_logbook_entries()) == entry_count
    assert database.get_catalog_target("dy pegasi")["target_name"] == catalog_name
    assert first["targets"] == second["targets"]


def test_seed_marker_prevents_reimport(temp_data):
    counts = workbook.seed_if_needed()
    assert counts is not None
    assert workbook.seed_if_needed() is None
    assert database.get_setting("workbook_seeded") == "1"
