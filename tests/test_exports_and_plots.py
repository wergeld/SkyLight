from __future__ import annotations

import io
import json
import math
import zipfile
from datetime import datetime

import numpy as np
import plotly.graph_objects as go

from starlight import exports, plots, transforms


def test_analysis_export_and_bundle_metadata(prepared):
    folded = transforms.phase_fold(prepared, 105.0 / 1440.0, 2461336.5)
    analysis = exports.analysis_export_frame(folded)
    assert "STARLIGHT_phase" in analysis.columns
    assert analysis["STARLIGHT_phase"].between(0, 1).all()

    metadata = exports.metadata_payload(
        target="DY Pegasi",
        period_days=105.0 / 1440.0,
        epoch_jd=2461336.5,
        thresholds={"snr_min": np.float64(10.0)},
        datasets=[{"rows": np.int64(163), "imported_at": datetime(2026, 10, 22, 1, 2, 3)}],
        extra={"flag_count": np.int64(4), "invalid": math.nan},
    )
    bundle = exports.zip_bundle({"analysis.csv": b"a,b\n1,2\n"}, metadata)
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        names = set(archive.namelist())
        assert names == {"analysis.csv", "metadata.json", "README.txt"}
        restored = json.loads(archive.read("metadata.json"))
    assert restored["target"] == "DY Pegasi"
    assert restored["thresholds"]["snr_min"] == 10.0
    assert restored["datasets"][0]["rows"] == 163
    assert restored["datasets"][0]["imported_at"].startswith("2026-10-22T01:02:03")
    assert restored["invalid"] is None


def test_plot_figures_build(prepared):
    elapsed = transforms.add_elapsed(prepared, "global")
    folded = transforms.phase_fold(elapsed, 105.0 / 1440.0, 2461336.5)
    quality = transforms.compute_quality_flags(folded, snr_min=1000.0)

    light = plots.light_curve_figure(quality, "DY Pegasi", "calendar")
    phase = plots.phase_figure(folded, "DY Pegasi", 105.0 / 1440.0, 2461336.5)
    distributions = plots.quality_distributions(quality)
    timeseries = plots.quality_timeseries(quality)

    for figure in (light, phase, distributions, timeseries):
        assert isinstance(figure, go.Figure)
        assert len(figure.data) > 0
    assert len(light.data) >= 1
    assert any("Flagged for review" == trace.name for trace in light.data)
    assert exports.figure_html_bytes(light).startswith(b"<html")
    png = exports.figure_png_bytes(light)
    assert png is None or png.startswith(b"\x89PNG")
