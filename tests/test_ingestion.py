from __future__ import annotations

import json

import pandas as pd

from starlight import config, database, exports, ingestion, transforms


def test_parse_sample_preserves_raw_values(sample_bytes):
    parsed = ingestion.parse_seestar_csv(sample_bytes, "sample.csv")

    assert parsed.row_count == 163
    assert parsed.target_names == ["DY Pegasi"]
    assert parsed.jd_min == 2461336.562347
    assert parsed.jd_max == 2461336.619747

    first = parsed.rows[0]
    raw = json.loads(first["raw_json"])
    assert raw["Name"] == "DY Pegasi"
    assert raw["EXP start"] == "2026.10.22 21:29:46"
    assert raw["EXP start(JD)"] == "2461336.562347"
    assert raw["Mag(obs)"] == "9.583609"
    assert first["mag_obs"] == 9.583609
    assert first["target_key"] == "dy pegasi"
    assert "Is Variable" in raw


def test_ingest_archives_file_and_is_idempotent(temp_data, sample_bytes, sample_dataset):
    dataset = database.get_dataset(sample_dataset.dataset_id)
    archived = config.UPLOADS_DIR / dataset["stored_filename"]
    assert sample_dataset.row_count == 163
    assert sample_dataset.duplicate is False
    assert archived.read_bytes() == sample_bytes

    duplicate = ingestion.ingest_bytes(sample_bytes, "sample.csv")
    assert duplicate.duplicate is True
    assert duplicate.dataset_id == sample_dataset.dataset_id
    assert len(database.list_datasets()) == 1

    forced = ingestion.ingest_bytes(sample_bytes, "sample.csv", force=True)
    assert forced.duplicate is False
    assert len(database.list_datasets()) == 2
    assert len(database.get_observations()) == 326


def test_prepare_and_raw_export_preserve_cells(observations):
    prepared = transforms.prepare_observations(observations).reset_index(drop=True)
    raw = exports.raw_export_frame(prepared)
    analysis = exports.analysis_export_frame(prepared)

    assert len(raw) == 163
    assert "EXP start(JD)" in raw.columns
    assert "STARLIGHT_observation_id" in raw.columns
    assert "STARLIGHT_target_key" in analysis.columns
    assert raw.loc[0, "EXP start(JD)"] == "2461336.562347"
    assert raw.loc[0, "EXP start"] == "2026.10.22 21:29:46"
    assert raw.loc[0, "Mag(obs)"] == "9.583609"
    assert not any(column == "STARLIGHT_phase" for column in raw.columns)


def test_prepare_derives_time_and_phase(observations):
    prepared = transforms.prepare_observations(observations)
    elapsed = transforms.add_elapsed(prepared, "global")
    folded = transforms.phase_fold(elapsed, 105.0 / 1440.0, 2461336.5)

    assert elapsed["elapsed_hours"].min() == 0.0
    assert elapsed["elapsed_hours"].max() > 1.3
    assert folded["phase"].between(0, 1).all()
    assert prepared["local_datetime"].notna().all()
    assert prepared["night_key"].nunique() == 1


def test_quality_flags_do_not_drop_rows():
    frame = pd.DataFrame(
        {
            "id": [10, 11, 12, 13, 14],
            "target_key": ["test target"] * 5,
            "target_name": ["Test Target"] * 5,
            "dataset_id": ["d"] * 5,
            "source_file": ["s.csv"] * 5,
            "source_row": [2, 3, 4, 5, 6],
            "local_start": [
                "2026-01-01 00:00:00",
                "2026-01-01 00:01:00",
                "2026-01-01 00:02:00",
                "2026-01-01 00:03:00",
                "2026-01-01 00:04:00",
            ],
            "jd_start": [2460000.50000, 2460000.50069, 2460000.50139, 2460000.50139, 2460000.50278],
            "mag_obs": [10.0, 10.0, 10.0, 10.0, 3.0],
            "mag_err": [0.05, 0.50, 0.05, 0.05, 0.05],
            "snr": [2.0, 50.0, 50.0, 50.0, 50.0],
            "parse_flags": ["", "", "", "", ""],
        },
        index=[10, 11, 12, 13, 14],
    )
    prepared = transforms.prepare_observations(frame)
    flagged = transforms.compute_quality_flags(
        prepared, snr_min=10, mag_err_max=0.20, spike_sigma=5, spike_min_delta=0.15
    )

    assert len(flagged) == len(frame)
    reasons = flagged["flag_reasons"].tolist()
    assert any("SNR < 10" in value for value in reasons)
    assert any("mag error > 0.2" in value for value in reasons)
    assert any("duplicate timestamp" in value for value in reasons)
    assert any("possible spike" in value for value in reasons)
    assert flagged["is_flagged"].sum() >= 4
    counts = transforms.flag_counts(flagged)
    assert not counts.empty
