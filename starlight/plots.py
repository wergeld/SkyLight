from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.colors import qualitative
from plotly.subplots import make_subplots

from . import config
from .transforms import add_elapsed

PALETTE = qualitative.Plotly

MODE_LABELS = {
    "calendar": "Calendar date (local EXP start)",
    "jd": "Julian Date (raw)",
    "elapsed_global": "Elapsed time since first observation (all nights, gaps preserved)",
    "elapsed_night": "Elapsed time within each night (separate traces, no cross-night alignment)",
}


def _empty(message: str) -> go.Figure:
    figure = go.Figure()
    figure.add_annotation(
        text=message,
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        font=dict(size=15, color="#c7c7c7"),
    )
    figure.update_layout(
        template="plotly_dark",
        height=420,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
    )
    return figure


def _error_array(values: pd.Series) -> list[float] | None:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().sum() == 0:
        return None
    return numeric.fillna(0.0).astype(float).tolist()


def _hover_text(data: pd.DataFrame) -> list[list[str]]:
    columns = []
    for _, row in data.iterrows():
        columns.append(
            [
                str(row.get("local_start") or row.get("display_datetime") or ""),
                f"{float(row['jd_start']):.6f}" if pd.notna(row.get("jd_start")) else "",
                f"{float(row['snr']):.1f}" if pd.notna(row.get("snr")) else "",
                str(row.get("source_file") or ""),
                str(row.get("flag_reasons") or ""),
                f"{float(row['mag_err']):.3f}" if pd.notna(row.get("mag_err")) else "",
                str(row.get("logbook_session_id") or ""),
            ]
        )
    return columns


def light_curve_figure(
    df: pd.DataFrame,
    target_name: str,
    mode: str = "calendar",
    *,
    show_lines: bool = False,
    highlight_flags: bool = True,
) -> go.Figure:
    if df.empty:
        return _empty("No observations are available for this selection.")
    if mode not in MODE_LABELS:
        mode = "calendar"
    data = add_elapsed(df.copy(), "per_night" if mode == "elapsed_night" else "global")
    if mode == "calendar":
        data = data[data["display_datetime"].notna()].copy()
        x_values = data["display_datetime"]
        x_title = "Local date/time from EXP start (UTC fallback)"
    elif mode == "jd":
        data = data[data["jd_start"].notna()].copy()
        x_values = data["jd_start"]
        x_title = "Julian Date (raw, no offsets)"
    else:
        data = data[data["elapsed_hours"].notna() & data["jd_start"].notna()].copy()
        x_values = data["elapsed_hours"]
        x_title = (
            "Hours since first point in each night (separate traces)"
            if mode == "elapsed_night"
            else "Hours since first observation in selection (gaps preserved)"
        )
    if data.empty:
        return _empty("The selected time axis has no valid values.")

    data["_x"] = x_values
    figure = go.Figure()
    night_groups = list(data.groupby("night_label", dropna=False, sort=True))
    for index, (night_label, group) in enumerate(night_groups):
        group = group.sort_values(["jd_start", "source_row"])
        color = PALETTE[index % len(PALETTE)]
        errors = _error_array(group["mag_err"])
        customdata = _hover_text(group)
        figure.add_trace(
            go.Scatter(
                x=group["_x"],
                y=group["mag_obs"],
                mode="lines+markers" if show_lines else "markers",
                name=str(night_label),
                legendgroup=str(night_label),
                marker=dict(size=7, color=color, line=dict(width=0.5, color="#111111")),
                line=dict(width=1, color=color),
                error_y=dict(
                    type="data",
                    array=errors,
                    visible=errors is not None,
                    thickness=1,
                    width=2,
                    color=color,
                )
                if errors
                else None,
                customdata=customdata,
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "JD %{customdata[1]}<br>"
                    "Mag %{y:.4f} ± %{customdata[5]}<br>"
                    "SNR %{customdata[2]}<br>"
                    "%{customdata[3]}<br>"
                    "Logbook: %{customdata[6]}<br>"
                    "Flags: %{customdata[4]}"
                    "<extra>%{fullData.name}</extra>"
                ),
            )
        )

    if highlight_flags and "is_flagged" in data:
        flagged = data[data["is_flagged"].fillna(False)]
        if not flagged.empty:
            figure.add_trace(
                go.Scatter(
                    x=flagged["_x"],
                    y=flagged["mag_obs"],
                    mode="markers",
                    name="Flagged for review",
                    marker=dict(size=13, symbol="x", color="#ff4d4f", line=dict(width=1.5)),
                    customdata=_hover_text(flagged),
                    hovertemplate=(
                        "<b>%{customdata[0]}</b><br>"
                        "JD %{customdata[1]}<br>"
                        "Mag %{y:.4f}<br>"
                        "SNR %{customdata[2]}<br>"
                        "Flags: %{customdata[4]}"
                        "<extra>Flagged for review</extra>"
                    ),
                )
            )

    subtitle = (
        "Raw observations shown unchanged. No night-to-night shifts, median offsets, "
        "or time alignment have been applied."
    )
    if mode == "elapsed_night":
        subtitle += " Each nightly trace starts at zero for display only."
    figure.update_layout(
        title=dict(text=f"Light Curve — {target_name}", x=0.01),
        template="plotly_dark",
        height=560,
        hovermode="closest",
        legend_title_text="Night / source",
        margin=dict(l=60, r=30, t=85, b=75),
    )
    figure.add_annotation(
        text=subtitle,
        x=0.01,
        y=-0.13,
        xref="paper",
        yref="paper",
        showarrow=False,
        align="left",
        font=dict(size=11, color="#b8b8b8"),
    )
    figure.update_xaxes(title_text=x_title, showgrid=True, gridcolor="#333333")
    if mode == "calendar":
        figure.update_xaxes(type="date")
    figure.update_yaxes(
        title_text="Magnitude (brighter up)",
        autorange="reversed",
        showgrid=True,
        gridcolor="#333333",
    )
    return figure


def phase_figure(
    df: pd.DataFrame,
    target_name: str,
    period_days: float,
    epoch_jd: float = 0.0,
    *,
    show_lines: bool = False,
) -> go.Figure:
    if df.empty or "phase" not in df:
        return _empty("No phase-folded observations are available.")
    data = df[df["phase"].notna()].copy()
    if data.empty:
        return _empty("No valid phases are available.")
    figure = go.Figure()
    night_groups = list(data.groupby("night_label", dropna=False, sort=True))
    for index, (night_label, group) in enumerate(night_groups):
        color = PALETTE[index % len(PALETTE)]
        for cycle, showlegend in ((0, True), (1, False)):
            cycle_data = group.assign(_phase=group["phase"] + cycle).sort_values("_phase")
            errors = _error_array(cycle_data["mag_err"])
            figure.add_trace(
                go.Scatter(
                    x=cycle_data["_phase"],
                    y=cycle_data["mag_obs"],
                    mode="lines+markers" if show_lines else "markers",
                    name=str(night_label),
                    legendgroup=str(night_label),
                    showlegend=showlegend,
                    marker=dict(size=7, color=color, line=dict(width=0.5, color="#111111")),
                    line=dict(width=1, color=color),
                    error_y=dict(
                        type="data",
                        array=errors,
                        visible=errors is not None,
                        thickness=1,
                        width=2,
                        color=color,
                    )
                    if errors
                    else None,
                    customdata=_hover_text(cycle_data),
                    hovertemplate=(
                        "<b>%{customdata[0]}</b><br>"
                        "Phase %{x:.5f}<br>"
                        "JD %{customdata[1]}<br>"
                        "Mag %{y:.4f} ± %{customdata[5]}<br>"
                        "SNR %{customdata[2]}<br>"
                        "Flags: %{customdata[4]}"
                        "<extra>%{fullData.name}</extra>"
                    ),
                )
            )
    period_minutes = float(period_days) * 1440.0
    figure.add_vline(x=1.0, line_width=1, line_dash="dot", line_color="#777777")
    figure.update_layout(
        title=dict(text=f"Phase Fold — {target_name}", x=0.01),
        template="plotly_dark",
        height=560,
        hovermode="closest",
        legend_title_text="Night / source",
        margin=dict(l=60, r=30, t=85, b=85),
    )
    figure.add_annotation(
        text=(
            f"Period = {period_days:.8f} d ({period_minutes:.2f} min) · "
            f"Epoch = JD {epoch_jd:.6f} · phase = ((JD − epoch) / period) mod 1<br>"
            "Phases are derived from absolute JD. No night-to-night alignment was applied."
        ),
        x=0.01,
        y=-0.14,
        xref="paper",
        yref="paper",
        showarrow=False,
        align="left",
        font=dict(size=11, color="#b8b8b8"),
    )
    figure.update_xaxes(
        title_text="Phase (two cycles shown)",
        range=[0, 2],
        tickvals=[0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0],
        gridcolor="#333333",
    )
    figure.update_yaxes(
        title_text="Magnitude (brighter up)",
        autorange="reversed",
        gridcolor="#333333",
    )
    return figure


def quality_distributions(
    df: pd.DataFrame,
    *,
    snr_min: float = config.DEFAULT_SNR_MIN,
    mag_err_max: float = config.DEFAULT_MAG_ERR_MAX,
) -> go.Figure:
    if df.empty:
        return _empty("No observations are available.")
    figure = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=("Reported magnitude error", "Signal-to-noise ratio (SNR)"),
    )
    errors = pd.to_numeric(df["mag_err"], errors="coerce").dropna()
    snrs = pd.to_numeric(df["snr"], errors="coerce").dropna()
    figure.add_trace(
        go.Histogram(x=errors, nbinsx=30, marker_color="#5dade2", name="Mag error"),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Histogram(x=snrs, nbinsx=30, marker_color="#58d68d", name="SNR"),
        row=1,
        col=2,
    )
    if not errors.empty:
        figure.add_vline(x=mag_err_max, line_dash="dash", line_color="#ff4d4f", row=1, col=1)
    if not snrs.empty:
        figure.add_vline(x=snr_min, line_dash="dash", line_color="#ff4d4f", row=1, col=2)
    figure.update_layout(
        template="plotly_dark",
        height=360,
        showlegend=False,
        margin=dict(l=40, r=20, t=60, b=40),
        title=dict(text="Quality distributions (dashed lines = review thresholds)", x=0.01),
    )
    figure.update_xaxes(title_text="Mag(err)", row=1, col=1)
    figure.update_xaxes(title_text="SNR", row=1, col=2)
    figure.update_yaxes(title_text="Count", row=1, col=1)
    return figure


def quality_timeseries(
    df: pd.DataFrame,
    *,
    snr_min: float = config.DEFAULT_SNR_MIN,
    mag_err_max: float = config.DEFAULT_MAG_ERR_MAX,
) -> go.Figure:
    if df.empty:
        return _empty("No observations are available.")
    figure = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        subplot_titles=("SNR versus time", "Reported magnitude error versus time"),
        vertical_spacing=0.12,
    )
    for flagged, color, name in (
        (df[~df["is_flagged"].fillna(False)], "#5dade2", "OK"),
        (df[df["is_flagged"].fillna(False)], "#ff4d4f", "Flagged for review"),
    ):
        if flagged.empty:
            continue
        figure.add_trace(
            go.Scatter(
                x=flagged["jd_start"],
                y=flagged["snr"],
                mode="markers",
                name=name,
                marker=dict(color=color, size=7),
                customdata=flagged["flag_reasons"].fillna("").tolist(),
                hovertemplate="JD %{x:.6f}<br>SNR %{y:.2f}<br>%{customdata}<extra></extra>",
            ),
            row=1,
            col=1,
        )
        figure.add_trace(
            go.Scatter(
                x=flagged["jd_start"],
                y=flagged["mag_err"],
                mode="markers",
                name=name,
                showlegend=False,
                marker=dict(color=color, size=7),
                customdata=flagged["flag_reasons"].fillna("").tolist(),
                hovertemplate="JD %{x:.6f}<br>Mag(err) %{y:.3f}<br>%{customdata}<extra></extra>",
            ),
            row=2,
            col=1,
        )
    figure.add_hline(y=snr_min, line_dash="dash", line_color="#f5b041", row=1, col=1)
    figure.add_hline(y=mag_err_max, line_dash="dash", line_color="#f5b041", row=2, col=1)
    figure.update_layout(
        template="plotly_dark",
        height=560,
        hovermode="closest",
        margin=dict(l=55, r=20, t=60, b=40),
        title=dict(text="Quality metrics in time (raw timestamps, no offsets)", x=0.01),
    )
    figure.update_yaxes(title_text="SNR", row=1, col=1)
    figure.update_yaxes(title_text="Mag(err)", row=2, col=1)
    figure.update_xaxes(title_text="Julian Date (raw)", row=2, col=1)
    return figure
