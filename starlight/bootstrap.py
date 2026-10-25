from __future__ import annotations

from . import config, database, resources, workbook

_INITIALIZED_PATH: str | None = None


def initialize(*, force_seed: bool = False) -> None:
    global _INITIALIZED_PATH
    config.ensure_dirs()
    database.init_db()
    if not force_seed and _INITIALIZED_PATH == str(config.DB_PATH):
        return
    try:
        workbook.seed_if_needed(force=force_seed)
        database.set_setting("workbook_seed_error", "")
    except Exception as exc:  # keep the app usable even if the seed workbook is malformed
        database.set_setting("workbook_seed_error", str(exc))
    database.seed_aliases()
    resources.ensure_default_resources()
    if database.get_setting("snr_min") is None:
        database.set_setting("snr_min", str(config.DEFAULT_SNR_MIN))
    if database.get_setting("mag_err_max") is None:
        database.set_setting("mag_err_max", str(config.DEFAULT_MAG_ERR_MAX))
    if database.get_setting("spike_sigma") is None:
        database.set_setting("spike_sigma", str(config.DEFAULT_SPIKE_SIGMA))
    if database.get_setting("spike_min_delta") is None:
        database.set_setting("spike_min_delta", str(config.DEFAULT_SPIKE_MIN_DELTA))
    _INITIALIZED_PATH = str(config.DB_PATH)
