from __future__ import annotations

import pandas as pd
import streamlit as st

from starlight import config, database, exports, ingestion, plots, summaries, transforms, ui

ui.page_setup("Observations", "🔭")
ui.sidebar_common()

st.title("Seestar observation analysis")
st.caption(
    "Upload one or more Seestar CSVs, inspect each target independently, and link individual "
    "measurements to a persistent observing logbook."
)
ui.preservation_notice()

for level, message in st.session_state.pop("import_messages", []):
    if level == "success":
        st.success(message)
    elif level == "warning":
        st.warning(message)
    else:
        st.error(message)

uploaded = st.sidebar.file_uploader(
    "Upload Seestar CSV files",
    type=["csv"],
    accept_multiple_files=True,
    key="seestar_uploads",
)
force_import = st.sidebar.checkbox(
    "Re-import files already in the archive",
    value=False,
    help="By default, an identical file hash is skipped.",
)
if st.sidebar.button("Import uploaded files", disabled=not uploaded, width="stretch"):
    messages: list[tuple[str, str]] = []
    for upload in uploaded or []:
        try:
            result = ingestion.ingest_bytes(
                upload.getvalue(),
                upload.name,
                force=force_import,
            )
            if result.duplicate:
                messages.append(
                    (
                        "warning",
                        (
                            f"{upload.name} is already archived as dataset "
                            f"{result.dataset_id[:8]}. It was not duplicated. "
                            "Use the re-import option if intentional."
                        ),
                    )
                )
            else:
                targets = ", ".join(result.target_names)
                messages.append(
                    (
                        "success",
                        f"Imported {upload.name}: {result.row_count} observations for {targets}.",
                    )
                )
                if result.warnings:
                    messages.append(("warning", f"{upload.name}: " + " ".join(result.warnings)))
        except Exception as exc:
            messages.append(("error", f"{upload.name}: {exc}"))
    st.session_state["import_messages"] = messages
    st.rerun()

with st.sidebar.expander("Quality review thresholds", expanded=False):
    snr_min = st.number_input(
        "Minimum SNR",
        min_value=0.0,
        value=float(database.get_setting("snr_min", str(config.DEFAULT_SNR_MIN))),
        step=1.0,
    )
    mag_err_max = st.number_input(
        "Maximum Mag(err)",
        min_value=0.001,
        value=float(database.get_setting("mag_err_max", str(config.DEFAULT_MAG_ERR_MAX))),
        step=0.01,
        format="%.3f",
    )
    spike_sigma = st.number_input(
        "Spike threshold (sigma)",
        min_value=1.0,
        value=float(database.get_setting("spike_sigma", str(config.DEFAULT_SPIKE_SIGMA))),
        step=0.5,
    )
    spike_min_delta = st.number_input(
        "Spike minimum delta (mag)",
        min_value=0.01,
        value=float(database.get_setting("spike_min_delta", str(config.DEFAULT_SPIKE_MIN_DELTA))),
        step=0.01,
        format="%.2f",
    )
    if st.button("Save as defaults", width="stretch"):
        database.set_setting("snr_min", str(snr_min))
        database.set_setting("mag_err_max", str(mag_err_max))
        database.set_setting("spike_sigma", str(spike_sigma))
        database.set_setting("spike_min_delta", str(spike_min_delta))
        st.success("Quality thresholds saved.")
    st.caption("Thresholds are used for review flags only; no observations are removed.")

seed_error = database.get_setting("workbook_seed_error")
if seed_error:
    st.sidebar.warning(f"Workbook auto-seed issue: {seed_error}")

datasets = database.list_datasets()
if datasets.empty:
    st.info("No observations are stored yet. Upload one or more Seestar CSV files in the sidebar.")
    st.stop()

dataset_options = datasets["id"].tolist()
with st.sidebar.expander("Saved sessions", expanded=False):
    selected_dataset_ids = st.multiselect(
        "Datasets in view",
        options=dataset_options,
        default=dataset_options,
        format_func=lambda dataset_id: ui.dataset_label(
            datasets.loc[datasets["id"] == dataset_id].iloc[0]
        ),
        key="dataset_filter",
    )
    st.caption(f"{len(datasets)} archived CSV dataset(s). Raw files are stored under the data volume.")
    delete_id = st.selectbox(
        "Delete an archived dataset",
        options=["", *dataset_options],
        format_func=lambda value: "Select a dataset…"
        if not value
        else ui.dataset_label(datasets.loc[datasets["id"] == value].iloc[0]),
        key="delete_dataset_id",
    )
    confirm_delete = st.checkbox(
        "I understand this removes its observations and observation links",
        value=False,
        key="confirm_dataset_delete",
    )
    if st.button(
        "Delete dataset",
        disabled=not delete_id or not confirm_delete,
        width="stretch",
    ):
        dataset = database.get_dataset(delete_id)
        if dataset:
            path = config.UPLOADS_DIR / dataset["stored_filename"]
            database.delete_dataset(delete_id)
            path.unlink(missing_ok=True)
            st.session_state.pop("dataset_filter", None)
            st.success("Dataset deleted. Logbook entries were retained.")
            st.rerun()

entry_filter_id = ui.query_param("entry_id")
entry_filter = None
if entry_filter_id:
    try:
        entry_filter = database.get_logbook_entry(int(entry_filter_id))
    except (TypeError, ValueError):
        entry_filter = None
    if entry_filter is None:
        st.warning("The requested logbook entry was not found. Showing the normal dataset view.")
        del st.query_params["entry_id"]
    else:
        st.info(
            f"Showing observations linked to logbook entry **{entry_filter['session_id']}** "
            f"({entry_filter['target_name']})."
        )
        if st.button("Clear logbook filter"):
            ui.clear_view_filters()
            st.rerun()

if entry_filter:
    source_df = database.get_observations(entry_id=int(entry_filter["id"]))
    if source_df.empty:
        st.warning("This logbook entry has no linked observations yet.")
        st.page_link("pages/1_Logbook.py", label="Open the logbook to link observations")
        st.stop()
else:
    if not selected_dataset_ids:
        st.warning("Select at least one dataset in the sidebar.")
        st.stop()
    source_df = database.get_observations(dataset_ids=selected_dataset_ids)
    if source_df.empty:
        st.warning("The selected datasets have no observations.")
        st.stop()

observed_targets = database.list_observed_targets()
available_keys = set(source_df["target_key"].astype(str))
available_targets = [item for item in observed_targets if item["target_key"] in available_keys]
if not available_targets:
    st.warning("No targets are available in this view.")
    st.stop()

requested_target = ui.query_param("target")
query_token = f"{entry_filter_id or ''}|{requested_target or ''}"
if st.session_state.get("_query_token") != query_token:
    st.session_state.pop("active_target", None)
    st.session_state["_query_token"] = query_token
current_active = st.session_state.get("active_target")
if isinstance(current_active, dict) and current_active.get("target_key") not in available_keys:
    st.session_state.pop("active_target", None)
default_index = 0
if requested_target:
    for index, item in enumerate(available_targets):
        if item["target_key"] == requested_target:
            default_index = index
            break
target_choice = st.selectbox(
    "Target",
    options=available_targets,
    index=default_index,
    format_func=lambda item: f"{item['target_name']} ({item['count']} observations)",
    key="active_target",
)
target_key = str(target_choice["target_key"])
target_name = str(target_choice["target_name"])

if entry_filter:
    target_df = database.get_observations(
        entry_id=int(entry_filter["id"]), target_key=target_key
    )
else:
    target_df = database.get_observations(
        dataset_ids=selected_dataset_ids, target_key=target_key
    )

obs = transforms.prepare_observations(target_df)
obs = transforms.compute_quality_flags(
    obs,
    snr_min=float(snr_min),
    mag_err_max=float(mag_err_max),
    spike_sigma=float(spike_sigma),
    spike_min_delta=float(spike_min_delta),
)
if obs.empty:
    st.warning("No observations are available for this target in the current view.")
    st.stop()

st.header(target_name)
ui.render_target_summary(target_name, target_key)
ui.render_online_resources(target_name, target_key)

night_count = int(obs["night_key"].nunique())
flag_count = int(obs["is_flagged"].fillna(False).sum())
date_range = transforms.format_datetime_range(obs["display_datetime"].tolist())
metric_columns = st.columns(4)
metric_columns[0].metric("Observations", f"{len(obs):,}")
metric_columns[1].metric("Nights / files", f"{night_count:,}")
metric_columns[2].metric("Flagged for review", f"{flag_count:,}")
metric_columns[3].metric("Local date range", date_range or "—")

metadata = ui.target_metadata(target_name, target_key)
period_default = metadata.get("period_days") if metadata else None
epoch_default = metadata.get("epoch_jd") if metadata else None
phase_context = f"{target_key}|{period_default}|{epoch_default}"
if st.session_state.get("_phase_context") != phase_context:
    st.session_state.pop("phase_period", None)
    st.session_state.pop("phase_epoch", None)
    st.session_state["_phase_context"] = phase_context

link_editor_epoch = int(st.session_state.get("link_editor_epoch", 0))
link_editor_scope = (
    f"{target_key}_{entry_filter['id'] if entry_filter else 'all'}_"
    f"{len(selected_dataset_ids)}"
)

light_fig = None
phase_fig = None
summary_frame = summaries.summarize(obs, by_night=False)

tab_curve, tab_phase, tab_quality, tab_summary, tab_exports, tab_links = st.tabs(
    ["Light Curves", "Phase Folding", "Quality", "Summary", "Exports", "Logbook Links"]
)

with tab_curve:
    st.subheader("Light curve")
    mode_label = st.radio(
        "X axis",
        options=list(plots.MODE_LABELS.values()),
        index=0,
        key="light_curve_mode",
    )
    mode = next(key for key, value in plots.MODE_LABELS.items() if value == mode_label)
    option_columns = st.columns(3)
    show_lines = option_columns[0].toggle(
        "Connect points within each night", value=False, key="light_curve_lines"
    )
    highlight_flags = option_columns[1].toggle(
        "Highlight flagged points", value=True, key="light_curve_flags"
    )
    option_columns[2].caption(
        "Elapsed modes never offset one night against another. Per-night elapsed is opt-in."
    )
    light_fig = plots.light_curve_figure(
        obs,
        target_name,
        mode,
        show_lines=show_lines,
        highlight_flags=highlight_flags,
    )
    st.plotly_chart(light_fig, width="stretch")
    ui.download_plot_buttons(
        light_fig,
        stem=f"{target_name.replace(' ', '_')}_light_curve",
        key_prefix="light_curve",
    )
    with st.expander("Time-axis and provenance notes"):
        st.write(
            "**Calendar date** uses the Seestar `EXP start` local timestamp; if it cannot be "
            "parsed, UTC from `EXP start(JD)` is used. **Julian Date** uses the raw JD. "
            "**Elapsed (all nights)** subtracts one global reference time and preserves gaps. "
            "**Elapsed within each night** starts each nightly trace at zero for display only."
        )
        st.write(
            "No night-to-night vertical offsets, median normalization, or smoothing are applied. "
            "The magnitude axis is inverted so brighter measurements appear higher."
        )

with tab_phase:
    st.subheader("Phase folding")
    st.write(
        "Enter a known period and optional epoch. Phase is computed from absolute JD; "
        "observations are not shifted or aligned by night."
    )
    phase_columns = st.columns(4)
    period_input = phase_columns[0].number_input(
        "Period (days)",
        min_value=0.0,
        value=float(period_default or 0.0),
        format="%.8f",
        step=0.0001,
        key="phase_period",
    )
    epoch_input = phase_columns[1].number_input(
        "Epoch (JD, optional)",
        min_value=0.0,
        value=float(epoch_default or 0.0),
        format="%.6f",
        step=0.01,
        key="phase_epoch",
    )
    period_minutes = period_input * 1440.0
    phase_columns[2].metric("Period in minutes", f"{period_minutes:.3f}" if period_input else "—")
    phase_columns[3].metric("Raw observations", f"{len(obs):,}")
    save_columns = st.columns([1, 1, 3])
    if save_columns[0].button("Save period/epoch", width="stretch"):
        catalog_target = database.get_catalog_target(target_key)
        if catalog_target:
            database.update_target_period(target_key, period_input, epoch_input)
        else:
            database.upsert_catalog_target(
                {
                    "target_key": target_key,
                    "target_name": target_name,
                    "period_days": period_input,
                    "epoch_jd": epoch_input,
                }
            )
        database.set_setting(f"period_days:{target_key}", str(period_input))
        st.success("Period and epoch saved to the target catalog.")
    show_phase_lines = save_columns[1].toggle("Connect points", value=False, key="phase_lines")
    save_columns[2].caption("Automatic period searching is intentionally deferred to a later version.")
    if period_input > 0:
        try:
            phase_data = transforms.phase_fold(obs, period_input, epoch_input)
            phase_fig = plots.phase_figure(
                phase_data,
                target_name,
                period_input,
                epoch_input,
                show_lines=show_phase_lines,
            )
            st.plotly_chart(phase_fig, width="stretch")
            ui.download_plot_buttons(
                phase_fig,
                stem=f"{target_name.replace(' ', '_')}_phase_fold",
                key_prefix="phase_fold",
            )
            phase_csv = exports.analysis_export_frame(phase_data)
            st.download_button(
                "Download folded analysis CSV",
                data=exports.dataframe_csv_bytes(phase_csv),
                file_name=exports.csv_filename(f"{target_name}_phase_fold"),
                mime="text/csv",
                key="download_phase_csv",
            )
            st.caption(
                f"phase = ((JD − {epoch_input:.6f}) / {period_input:.8f}) mod 1. "
                "The raw CSV export remains unchanged."
            )
        except ValueError as exc:
            st.error(str(exc))
    else:
        st.info("Enter a period greater than zero in the sidebar or above to enable phase folding.")

with tab_quality:
    st.subheader("Data quality review")
    quality_metrics = st.columns(4)
    quality_metrics[0].metric("Below SNR threshold", int((obs["snr"] < snr_min).sum()))
    quality_metrics[1].metric("Above error threshold", int((obs["mag_err"] > mag_err_max).sum()))
    quality_metrics[2].metric("Possible spikes", int(obs["flag_reasons"].str.contains("possible spike", na=False).sum()))
    quality_metrics[3].metric("All flagged rows", flag_count)
    st.caption(
        "Flags are review aids. They never delete, smooth, or shift observations. "
        "Variable-star changes can legitimately appear as local spikes."
    )
    counts = transforms.flag_counts(obs)
    if counts.empty:
        st.success("No quality flags were triggered with the current thresholds.")
    else:
        st.dataframe(counts, width="stretch", hide_index=True)
    quality_plot = plots.quality_distributions(obs, snr_min=snr_min, mag_err_max=mag_err_max)
    st.plotly_chart(quality_plot, width="stretch")
    timeseries_plot = plots.quality_timeseries(obs, snr_min=snr_min, mag_err_max=mag_err_max)
    st.plotly_chart(timeseries_plot, width="stretch")
    ui.download_plot_buttons(
        timeseries_plot,
        stem=f"{target_name.replace(' ', '_')}_quality_timeseries",
        key_prefix="quality_timeseries",
    )
    flagged = obs[obs["is_flagged"].fillna(False)].copy()
    st.subheader(f"Flagged observations ({len(flagged):,})")
    display_columns = [
        "id",
        "source_file",
        "local_start",
        "jd_start",
        "mag_obs",
        "mag_err",
        "snr",
        "flag_reasons",
    ]
    if flagged.empty:
        st.info("No observations are flagged.")
    else:
        st.dataframe(
            flagged[[column for column in display_columns if column in flagged]].rename(
                columns={
                    "id": "Observation ID",
                    "source_file": "Source file",
                    "local_start": "Local start",
                    "jd_start": "JD",
                    "mag_obs": "Mag(obs)",
                    "mag_err": "Mag(err)",
                    "snr": "SNR",
                    "flag_reasons": "Flags",
                }
            ),
            width="stretch",
            hide_index=True,
        )
        st.download_button(
            "Download flagged observations CSV",
            data=exports.dataframe_csv_bytes(exports.analysis_export_frame(flagged)),
            file_name=exports.csv_filename(f"{target_name}_flagged"),
            mime="text/csv",
            key="download_flagged",
        )

with tab_summary:
    st.subheader("Photometry summary")
    by_night = st.toggle("Break down by night", value=False, key="summary_by_night")
    summary_frame = summaries.summarize(obs, by_night=by_night)
    if summary_frame.empty:
        st.info("No summary is available.")
    else:
        st.dataframe(summary_frame, width="stretch", hide_index=True)
        st.download_button(
            "Download summary CSV",
            data=exports.dataframe_csv_bytes(summary_frame),
            file_name=exports.csv_filename(f"{target_name}_summary"),
            mime="text/csv",
            key="download_summary",
        )
    st.caption(
        "Statistics describe the reported magnitudes in this selection. "
        "Weighted means use 1 / Mag(err)² weights. No detrending or night alignment is implied."
    )

with tab_exports:
    st.subheader("Exports")
    st.write(
        "Raw exports preserve the original Seestar columns and cell strings. "
        "Derived columns are prefixed with `STARLIGHT_`."
    )
    current_raw = exports.raw_export_frame(obs)
    current_analysis = exports.analysis_export_frame(obs)
    export_columns = st.columns(2)
    export_columns[0].download_button(
        "Download raw observations CSV",
        data=exports.dataframe_csv_bytes(current_raw),
        file_name=exports.csv_filename(f"{target_name}_raw"),
        mime="text/csv",
        key="download_raw_current",
        width="stretch",
    )
    export_columns[1].download_button(
        "Download analysis CSV",
        data=exports.dataframe_csv_bytes(current_analysis),
        file_name=exports.csv_filename(f"{target_name}_analysis"),
        mime="text/csv",
        key="download_analysis_current",
        width="stretch",
    )
    all_target_df = database.get_observations(dataset_ids=selected_dataset_ids)
    all_imported_df = database.get_observations()
    all_columns = st.columns(2)
    all_columns[0].download_button(
        "Download all targets in selected datasets (raw)",
        data=exports.dataframe_csv_bytes(exports.raw_export_frame(all_target_df)),
        file_name=exports.csv_filename("all_targets_selected_datasets_raw"),
        mime="text/csv",
        key="download_raw_selected_datasets",
        width="stretch",
    )
    all_columns[1].download_button(
        "Download all imported observations (raw)",
        data=exports.dataframe_csv_bytes(exports.raw_export_frame(all_imported_df)),
        file_name=exports.csv_filename("all_imported_observations_raw"),
        mime="text/csv",
        key="download_raw_all_imported",
        width="stretch",
    )
    st.divider()
    st.subheader("Observing-logbook bundle")
    bundle_files = {
        f"{target_name.replace(' ', '_')}_raw.csv": exports.dataframe_csv_bytes(current_raw),
        f"{target_name.replace(' ', '_')}_analysis.csv": exports.dataframe_csv_bytes(
            current_analysis
        ),
        f"{target_name.replace(' ', '_')}_summary.csv": exports.dataframe_csv_bytes(
            summary_frame
        ),
        f"{target_name.replace(' ', '_')}_flags.csv": exports.dataframe_csv_bytes(
            exports.analysis_export_frame(obs[obs["is_flagged"].fillna(False)])
        ),
    }
    bundle_figures = [("light_curve", light_fig)]
    if phase_fig is not None:
        bundle_figures.append(("phase_fold", phase_fig))
    bundle_figures.append(("quality", quality_plot))
    for name, figure in bundle_figures:
        if figure is not None:
            bundle_files[f"{name}.html"] = exports.figure_html_bytes(figure)
            png = exports.figure_png_bytes(figure)
            if png:
                bundle_files[f"{name}.png"] = png
    selected_dataset_rows = (
        datasets[datasets["id"].isin(selected_dataset_ids)]
        if not entry_filter
        else pd.DataFrame()
    )
    metadata_payload = exports.metadata_payload(
        target=target_name,
        period_days=period_input if "period_input" in locals() else period_default,
        epoch_jd=epoch_input if "epoch_input" in locals() else epoch_default,
        thresholds={
            "snr_min": snr_min,
            "mag_err_max": mag_err_max,
            "spike_sigma": spike_sigma,
            "spike_min_delta": spike_min_delta,
        },
        datasets=selected_dataset_rows.to_dict(orient="records")
        if not selected_dataset_rows.empty
        else [],
        extra={
            "entry_filter": entry_filter,
            "observation_count": int(len(obs)),
            "night_count": night_count,
            "flagged_count": flag_count,
            "source_files": sorted(obs["source_file"].dropna().astype(str).unique().tolist()),
        },
    )
    bundle = exports.zip_bundle(bundle_files, metadata_payload)
    st.download_button(
        "Download observing-logbook ZIP bundle",
        data=bundle,
        file_name=exports.bundle_filename(f"{target_name}_observing_bundle"),
        mime="application/zip",
        key="download_bundle",
        width="stretch",
    )
    st.caption(
        "The ZIP bundle includes raw and analysis CSVs, summary and flags, interactive plots, "
        "plot PNGs when kaleido is available, and metadata describing the exact settings used."
    )
    st.page_link("pages/1_Logbook.py", label="Open the observing logbook")

with tab_links:
    st.subheader("Link individual observations to the logbook")
    st.write(
        "Check any number of rows, or use **Select all shown**, then create a logbook entry or "
        "attach them to an existing entry. Each observation has one active logbook link and can "
        "be reassigned or unlinked."
    )
    if entry_filter:
        st.caption(
            f"Currently viewing observations linked to {entry_filter['session_id']}. "
            "Use the clear filter button above to work with the full target."
        )
    filter_columns = st.columns([1, 1, 1, 2])
    show_unlinked_only = filter_columns[0].toggle(
        "Only unlinked observations", value=False, key="only_unlinked"
    )
    link_view = obs[obs["logbook_entry_id"].isna()] if show_unlinked_only else obs
    select_revision_key = (
        f"link_select_revision_{link_editor_scope}_{show_unlinked_only}_{link_editor_epoch}"
    )
    select_revision = int(st.session_state.get(select_revision_key, 0))
    select_default = bool(
        st.session_state.get(f"{select_revision_key}_default", False)
    )
    editor_key = (
        f"link_editor_{link_editor_scope}_{show_unlinked_only}_"
        f"{link_editor_epoch}_{select_revision}"
    )
    editor_frame = pd.DataFrame(
        {
            "select": select_default,
            "Observation ID": link_view["id"].astype(int),
            "Local start": link_view["local_start"].fillna(""),
            "JD": pd.to_numeric(link_view["jd_start"], errors="coerce").round(6),
            "Mag": pd.to_numeric(link_view["mag_obs"], errors="coerce").round(4),
            "Err": pd.to_numeric(link_view["mag_err"], errors="coerce").round(4),
            "SNR": pd.to_numeric(link_view["snr"], errors="coerce").round(2),
            "Flags": link_view["flag_reasons"].fillna(""),
            "Linked session": link_view["logbook_session_id"].fillna(""),
        }
    )
    if filter_columns[1].button(
        "Select all shown",
        disabled=link_view.empty,
        width="stretch",
        key=f"link_select_all_button_{select_revision_key}",
    ):
        st.session_state[select_revision_key] = select_revision + 1
        st.session_state[f"{select_revision_key}_default"] = True
        st.rerun()
    if filter_columns[2].button(
        "Clear selection",
        disabled=link_view.empty,
        width="stretch",
        key=f"link_clear_button_{select_revision_key}",
    ):
        st.session_state[select_revision_key] = select_revision + 1
        st.session_state[f"{select_revision_key}_default"] = False
        st.rerun()
    edited = st.data_editor(
        editor_frame,
        hide_index=True,
        width="stretch",
        key=editor_key,
        column_config={
            "select": st.column_config.CheckboxColumn("Link", width="small"),
            "Observation ID": st.column_config.NumberColumn(disabled=True, width="small"),
            "Local start": st.column_config.TextColumn(disabled=True, width="medium"),
            "JD": st.column_config.NumberColumn(disabled=True, format="%.6f"),
            "Mag": st.column_config.NumberColumn(disabled=True, format="%.4f"),
            "Err": st.column_config.NumberColumn(disabled=True, format="%.4f"),
            "SNR": st.column_config.NumberColumn(disabled=True, format="%.2f"),
            "Flags": st.column_config.TextColumn(disabled=True, width="large"),
            "Linked session": st.column_config.TextColumn(disabled=True, width="medium"),
        },
    )
    checked_ids = edited.loc[edited["select"].fillna(False), "Observation ID"].astype(int).tolist()
    if checked_ids:
        st.caption(f"{len(checked_ids)} observation(s) checked.")
    entries = database.list_logbook_entries(target_key=target_key)
    action_columns = st.columns(3)
    if action_columns[0].button(
        "Prepare new logbook entry from checked",
        disabled=not checked_ids,
        width="stretch",
    ):
        st.session_state["pending_link_obs"] = checked_ids
        st.session_state["pending_link_target"] = target_key
        st.session_state["pending_link_token"] = database.utc_now()
        st.rerun()
    if action_columns[1].button(
        "Unlink checked observations",
        disabled=not checked_ids,
        width="stretch",
    ):
        database.unlink_observations(checked_ids)
        st.session_state["link_editor_epoch"] = link_editor_epoch + 1
        st.success(f"Unlinked {len(checked_ids)} observation(s). Raw data was not changed.")
        st.rerun()
    if entries.empty:
        action_columns[2].caption("No logbook entries exist for this target yet.")

    pending_ids = st.session_state.get("pending_link_obs", [])
    pending_target = st.session_state.get("pending_link_target")
    if pending_ids and pending_target == target_key:
        selected_rows = obs[obs["id"].isin(pending_ids)].copy()
        if not selected_rows.empty:
            local_times = selected_rows["display_datetime"].dropna()
            date_local = (
                pd.Timestamp(local_times.min()).strftime("%Y-%m-%d") if not local_times.empty else ""
            )
            start_local = (
                pd.Timestamp(local_times.min()).strftime("%H:%M:%S") if not local_times.empty else ""
            )
            end_local = (
                pd.Timestamp(local_times.max()).strftime("%H:%M:%S") if not local_times.empty else ""
            )
            exposures = pd.to_numeric(selected_rows["exp_seconds"], errors="coerce").dropna()
            sources = ", ".join(
                sorted(selected_rows["source_file"].dropna().astype(str).unique().tolist())
            )
            st.divider()
            st.subheader(f"New logbook entry for {target_name}")
            st.caption("A unique session ID is generated automatically when the entry is created.")
            if "pending_link_token" not in st.session_state:
                st.session_state["pending_link_token"] = database.utc_now()
            pending_token = (
                str(st.session_state["pending_link_token"])
                .replace(" ", "_")
                .replace(":", "")
            )
            new_link_date_key = f"new_link_date_{pending_token}"
            new_link_start_key = f"new_link_start_{pending_token}"
            new_link_end_key = f"new_link_end_{pending_token}"
            new_link_moon_key = f"new_link_moon_{pending_token}"
            new_link_status_key = f"new_link_status_{pending_token}"
            ui.show_conditions_status(new_link_status_key)
            with st.form("new_logbook_from_observations"):
                form_columns = st.columns(2)
                date_value = form_columns[0].text_input(
                    "Date (local)", value=date_local, key=new_link_date_key
                )
                time_standard = form_columns[1].text_input(
                    "Time standard in CSV", value=config.TIME_STANDARD
                )
                form_columns = st.columns(3)
                start_value = form_columns[0].text_input(
                    "Start time (local)", value=start_local, key=new_link_start_key
                )
                end_value = form_columns[1].text_input(
                    "End time (local)", value=end_local, key=new_link_end_key
                )
                filter_value = form_columns[2].text_input("Filter", value="Unfiltered")
                form_columns = st.columns(4)
                exposure_value = form_columns[0].number_input(
                    "Exposure (s)",
                    min_value=0.0,
                    value=float(exposures.median()) if not exposures.empty else 0.0,
                    step=1.0,
                )
                frames_value = form_columns[1].number_input(
                    "Frames / points", min_value=1, value=len(selected_rows), step=1
                )
                settings_value = form_columns[2].text_input("Seestar mode/settings", value="Seestar")
                processed_value = form_columns[3].checkbox("Processed?", value=False)
                transparency = st.text_input("Sky transparency", value="")
                seeing = st.text_input("Seeing / focus", value="")
                moon = st.text_area(
                    "Moon / conditions", value="", height=80, key=new_link_moon_key
                )
                ui.conditions_lookup_caption()
                lookup_columns = st.columns([1, 2])
                lookup_columns[0].form_submit_button(
                    "Look up Moon & weather",
                    key=f"new_link_lookup_conditions_{pending_token}",
                    on_click=ui.fill_conditions_from_state,
                    args=(
                        new_link_date_key,
                        new_link_start_key,
                        new_link_end_key,
                        new_link_moon_key,
                        new_link_status_key,
                    ),
                    disabled=ui.observer_coordinates() is None,
                    width="stretch",
                )
                csv_filename = st.text_input("CSV filename(s)", value=sources)
                notes = st.text_area("Notes / issues", value="")
                submitted = lookup_columns[1].form_submit_button(
                    "Create entry and link checked observations",
                    key=f"new_link_create_submit_{pending_token}",
                    width="stretch",
                )
                if submitted:
                    try:
                        entry_id = database.create_logbook_entry(
                            {
                                "target_name": target_name,
                                "target_key": target_key,
                                "date_local": date_value,
                                "start_local": start_value,
                                "end_local": end_value,
                                "time_standard": time_standard,
                                "filter": filter_value,
                                "exposure_s": exposure_value,
                                "frames": frames_value,
                                "settings": settings_value,
                                "transparency": transparency,
                                "seeing": seeing,
                                "moon": moon,
                                "csv_filename": csv_filename,
                                "notes": notes,
                                "processed": processed_value,
                            },
                            observation_ids=pending_ids,
                        )
                        st.session_state.pop("pending_link_obs", None)
                        st.session_state.pop("pending_link_target", None)
                        st.session_state.pop("pending_link_token", None)
                        st.session_state["link_editor_epoch"] = link_editor_epoch + 1
                        st.success(
                            f"Created logbook entry and linked {len(pending_ids)} observations."
                        )
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
            if st.button("Cancel pending logbook entry", key="cancel_pending_entry"):
                st.session_state.pop("pending_link_obs", None)
                st.session_state.pop("pending_link_target", None)
                st.session_state.pop("pending_link_token", None)
                st.rerun()

    if not entries.empty:
        st.divider()
        st.subheader("Attach checked observations to an existing entry")
        with st.form("link_existing_entry"):
            entry_options = entries["id"].astype(int).tolist()
            entry_labels = {
                int(row["id"]): (
                    f"{row['session_id']} · {row['target_name']} · "
                    f"{row.get('date_local') or 'no date'} · {int(row.get('linked_count', 0))} linked"
                )
                for _, row in entries.iterrows()
            }
            selected_entry = st.selectbox(
                "Logbook entry",
                options=entry_options,
                format_func=lambda value: entry_labels.get(int(value), str(value)),
            )
            link_submit = st.form_submit_button(
                "Link checked observations", width="stretch", disabled=not checked_ids
            )
        if link_submit and checked_ids:
            database.link_observations(checked_ids, int(selected_entry))
            st.session_state["link_editor_epoch"] = link_editor_epoch + 1
            st.success(f"Linked {len(checked_ids)} observation(s).")
            st.rerun()

        with st.expander("Bulk-link unlinked observations in this view", expanded=False):
            unlinked_ids = obs.loc[obs["logbook_entry_id"].isna(), "id"].astype(int).tolist()
            st.caption(f"{len(unlinked_ids)} observation(s) in this view are currently unlinked.")
            with st.form("bulk_link_entry"):
                bulk_entry = st.selectbox(
                    "Target entry",
                    options=entry_options,
                    format_func=lambda value: entry_labels.get(int(value), str(value)),
                    key="bulk_entry",
                )
                bulk_confirm = st.checkbox(
                    "I want to link every unlinked observation in this view", value=False
                )
                bulk_submit = st.form_submit_button(
                    "Link all unlinked observations in this view",
                    width="stretch",
                    disabled=not unlinked_ids or not bulk_confirm,
                )
            if bulk_submit and unlinked_ids:
                database.link_observations(unlinked_ids, int(bulk_entry))
                st.session_state["link_editor_epoch"] = link_editor_epoch + 1
                st.success(f"Linked {len(unlinked_ids)} observation(s).")
                st.rerun()

    linked_entry_ids = (
        obs["logbook_entry_id"].dropna().astype(int).unique().tolist()
        if "logbook_entry_id" in obs
        else []
    )
    if linked_entry_ids:
        st.divider()
        st.subheader("Open a linked logbook entry")
        link_columns = st.columns([2, 1, 2])
        open_entry = link_columns[0].selectbox(
            "Linked entry",
            options=linked_entry_ids,
            format_func=lambda value: f"Entry {value}",
            key="open_linked_entry",
        )
        if link_columns[1].button("Open entry", width="stretch"):
            st.query_params["entry_id"] = str(int(open_entry))
            st.query_params["target"] = target_key
            st.switch_page("pages/1_Logbook.py")
