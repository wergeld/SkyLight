from __future__ import annotations

from pathlib import Path

import pytest

from starlight import bootstrap, config, database, ingestion

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_CSV = ROOT / "Magnitude_23h 08m 51s +17° 12′ 59″.csv"
WORKBOOK = ROOT / "Tampa_Variable_Star_Observing_Logbook.xlsx"


@pytest.fixture
def temp_data(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "DB_PATH", data_dir / "starlight.db")
    monkeypatch.setattr(config, "UPLOADS_DIR", data_dir / "uploads")
    monkeypatch.setattr(bootstrap, "_INITIALIZED_PATH", None)
    database.init_db()
    yield data_dir


@pytest.fixture
def sample_bytes() -> bytes:
    return SAMPLE_CSV.read_bytes()


@pytest.fixture
def sample_dataset(temp_data, sample_bytes):
    return ingestion.ingest_bytes(sample_bytes, SAMPLE_CSV.name)


@pytest.fixture
def observations(sample_dataset):
    return database.get_observations(dataset_ids=[sample_dataset.dataset_id])


@pytest.fixture
def prepared(observations):
    from starlight import transforms

    return transforms.prepare_observations(observations)
