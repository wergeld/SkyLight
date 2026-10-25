from __future__ import annotations

import pandas as pd
import streamlit as st

from starlight import database, ui, workbook

ui.page_setup("Logbook", "📓")
ui.sidebar_common()

st.title("Observing logbook")
st.caption(
    "Persistent browser logbook modeled on the Tampa Variable Star Observing Logbook. "
    "Entries can be linked to individual observations and exported back to Excel."
)
ui.preservation_notice()

flash = st.session_state.pop("logbook_flash", None)
if flash:
    st.success(flash)
logbook_editor_epoch = int(st.session_state.get("logbook_editor_epoch", 0))

observed = database.list_observed_targets()
catalog = database.get_catalog()
target_names = sorted(
    {
        *(str(item["target_name"]) for item in observed),
        *(str(value) for value in catalog.get("target_name", pd.Series(dtype=str)).tolist()),
    },
    key=str.casefold,
)

tab_browse, tab_new, tab_data = st.tabs(["Browse & Edit", "New Entry", "Import / Export"])

with tab_browse:
    st.subheader("Logbook entries")
    filter_columns = st.columns([2, 1])
    search = filter_columns[0].text_input(
        "Search session, target, notes, or filename", value="", key="logbook_search"
    )
    target_filter = filter_columns[1].selectbox(
        "Target filter",
        options=["", *target_names],
        format_func=lambda value: "All targets" if not value else value,
        key="logbook_target_filter",
    )
    entries = database.list_logbook_entries(
        search=search or None,
        target_key=target_filter or None,
    )
    if entries.empty:
        st.info("No logbook entries match the current filter. Create one in the New Entry tab.")
    else:
        display_entries = entries[
            [
                "session_id",
                "target_name",
                "date_local",
                "start_local",
                "end_local",
                "filter",
                "linked_count",
                "processed",
            ]
        ].rename(
            columns={
                "session_id": "Session ID",
                "target_name": "Target",
                "date_local": "Date",
                "start_local": "Start",
                "end_local": "End",
                "filter": "Filter",
                "linked_count": "Linked observations",
                "processed": "Processed",
            }
        )
        st.dataframe(display_entries, width="stretch", hide_index=True)

        query_entry = ui.query_param("entry_id")
        ids = entries["id"].astype(int).tolist()
        default_entry = ids[0]
        if query_entry:
            try:
                requested = int(query_entry)
                if requested in ids:
                    default_entry = requested
            except ValueError:
                pass
        label_map = {
            int(row["id"]): (
                f"{row['session_id']} · {row['target_name']} · "
                f"{row.get('date_local') or 'no date'}"
            )
            for _, row in entries.iterrows()
        }
        selected_id = st.selectbox(
            "Open entry",
            options=ids,
            index=ids.index(default_entry),
            format_func=lambda value: label_map.get(int(value), str(value)),
            key="logbook_selected_entry",
        )
        entry = database.get_logbook_entry(int(selected_id))
        if entry:
            linked = database.get_entry_observations(int(selected_id))
            summary_columns = st.columns(4)
            summary_columns[0].metric("Linked observations", f"{len(linked):,}")
            summary_columns[1].metric("Target", str(entry["target_name"]))
            summary_columns[2].metric("Date", str(entry.get("date_local") or "—"))
            summary_columns[3].metric(
                "Processed", "Yes" if entry.get("processed") else "No"
            )
            action_columns = st.columns([1.2, 1, 1.5])
            if action_columns[0].button(
                "View linked observations",
                disabled=linked.empty,
                width="stretch",
            ):
                st.query_params["entry_id"] = str(int(selected_id))
                st.query_params["target"] = str(entry["target_key"])
                st.switch_page("app.py")
            if action_columns[1].button("Copy session ID", width="stretch"):
                st.code(str(entry["session_id"]))
            action_columns[2].caption(
                "Open the Observations page to link or reassign individual measurements."
            )

            edit_date_key = f"logbook_edit_date_{selected_id}"
            edit_start_key = f"logbook_edit_start_{selected_id}"
            edit_end_key = f"logbook_edit_end_{selected_id}"
            edit_moon_key = f"logbook_edit_moon_{selected_id}"
            edit_status_key = f"logbook_edit_status_{selected_id}"
            ui.show_conditions_status(edit_status_key)
            with st.form(f"edit_logbook_{selected_id}"):
                st.subheader("Edit entry")
                st.caption(
                    f"Session ID: {entry.get('session_id') or ''} "
                    "(generated automatically; not editable)"
                )
                form_columns = st.columns(3)
                target_name = form_columns[0].text_input(
                    "Target", value=str(entry.get("target_name") or "")
                )
                date_local = form_columns[1].text_input(
                    "Date (local)",
                    value=str(entry.get("date_local") or ""),
                    key=edit_date_key,
                )
                time_standard = form_columns[2].text_input(
                    "Time standard in CSV",
                    value=str(entry.get("time_standard") or ""),
                )
                form_columns = st.columns(2)
                start_local = form_columns[0].text_input(
                    "Start time (local)",
                    value=str(entry.get("start_local") or ""),
                    key=edit_start_key,
                )
                end_local = form_columns[1].text_input(
                    "End time (local)",
                    value=str(entry.get("end_local") or ""),
                    key=edit_end_key,
                )
                form_columns = st.columns(4)
                filter_value = form_columns[0].text_input(
                    "Filter", value=str(entry.get("filter") or "")
                )
                exposure_s = form_columns[1].number_input(
                    "Exposure (s)",
                    min_value=0.0,
                    value=float(entry.get("exposure_s") or 0.0),
                    step=1.0,
                )
                frames = form_columns[2].number_input(
                    "Frames / points",
                    min_value=0,
                    value=int(entry.get("frames") or 0),
                    step=1,
                )
                processed = form_columns[3].checkbox(
                    "Processed?", value=bool(entry.get("processed"))
                )
                settings = st.text_input(
                    "Seestar mode/settings", value=str(entry.get("settings") or "")
                )
                form_columns = st.columns(2)
                transparency = form_columns[0].text_input(
                    "Sky transparency", value=str(entry.get("transparency") or "")
                )
                seeing = form_columns[1].text_input(
                    "Seeing / focus", value=str(entry.get("seeing") or "")
                )
                moon = st.text_area(
                    "Moon / conditions",
                    value=str(entry.get("moon") or ""),
                    height=80,
                    key=edit_moon_key,
                )
                ui.conditions_lookup_caption()
                lookup_columns = st.columns([1, 2])
                lookup_columns[0].form_submit_button(
                    "Look up Moon & weather",
                    key=f"edit_lookup_conditions_{selected_id}",
                    on_click=ui.fill_conditions_from_state,
                    args=(
                        edit_date_key,
                        edit_start_key,
                        edit_end_key,
                        edit_moon_key,
                        edit_status_key,
                    ),
                    disabled=ui.observer_coordinates() is None,
                    width="stretch",
                )
                csv_filename = st.text_input(
                    "CSV filename", value=str(entry.get("csv_filename") or "")
                )
                notes = st.text_area("Notes / issues", value=str(entry.get("notes") or ""))
                save_entry = lookup_columns[1].form_submit_button(
                    "Save entry",
                    key=f"save_logbook_{selected_id}",
                    width="stretch",
                )
            if save_entry:
                try:
                    database.update_logbook_entry(
                        int(selected_id),
                        {
                            "target_name": target_name,
                            "date_local": date_local,
                            "start_local": start_local,
                            "end_local": end_local,
                            "time_standard": time_standard,
                            "filter": filter_value,
                            "exposure_s": exposure_s,
                            "frames": frames,
                            "settings": settings,
                            "transparency": transparency,
                            "seeing": seeing,
                            "moon": moon,
                            "csv_filename": csv_filename,
                            "notes": notes,
                            "processed": processed,
                        },
                    )
                    st.session_state["logbook_flash"] = "Logbook entry saved."
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

            st.divider()
            st.subheader("Linked observations")
            if linked.empty:
                st.info("No observations are linked to this entry yet.")
            else:
                linked_editor = pd.DataFrame(
                    {
                        "select": False,
                        "Observation ID": linked["id"].astype(int),
                        "Local start": linked["local_start"].fillna(""),
                        "JD": pd.to_numeric(linked["jd_start"], errors="coerce").round(6),
                        "Mag": pd.to_numeric(linked["mag_obs"], errors="coerce").round(4),
                        "SNR": pd.to_numeric(linked["snr"], errors="coerce").round(2),
                        "Source": linked["source_file"].fillna(""),
                    }
                )
                linked_edited = st.data_editor(
                    linked_editor,
                    width="stretch",
                    hide_index=True,
                    key=f"unlink_editor_{selected_id}_{logbook_editor_epoch}",
                    column_config={
                        "select": st.column_config.CheckboxColumn("Unlink", width="small"),
                        "Observation ID": st.column_config.NumberColumn(disabled=True),
                        "Local start": st.column_config.TextColumn(disabled=True),
                        "JD": st.column_config.NumberColumn(disabled=True, format="%.6f"),
                        "Mag": st.column_config.NumberColumn(disabled=True, format="%.4f"),
                        "SNR": st.column_config.NumberColumn(disabled=True, format="%.2f"),
                        "Source": st.column_config.TextColumn(disabled=True),
                    },
                )
                unlink_ids = linked_edited.loc[
                    linked_edited["select"].fillna(False), "Observation ID"
                ].astype(int).tolist()
                if st.button(
                    "Unlink checked observations",
                    disabled=not unlink_ids,
                    key=f"unlink_button_{selected_id}",
                ):
                    database.unlink_observations(unlink_ids)
                    st.session_state["logbook_editor_epoch"] = logbook_editor_epoch + 1
                    st.session_state["logbook_flash"] = (
                        f"Unlinked {len(unlink_ids)} observation(s). Raw data was retained."
                    )
                    st.rerun()

            st.divider()
            st.subheader("Link available observations")
            candidates = database.get_observations(
                target_key=str(entry["target_key"]), unlinked_only=True
            )
            if candidates.empty:
                st.info("There are no unlinked observations for this target.")
            else:
                candidate_frame = pd.DataFrame(
                    {
                        "select": False,
                        "Observation ID": candidates["id"].astype(int),
                        "Local start": candidates["local_start"].fillna(""),
                        "JD": pd.to_numeric(candidates["jd_start"], errors="coerce").round(6),
                        "Mag": pd.to_numeric(candidates["mag_obs"], errors="coerce").round(4),
                        "SNR": pd.to_numeric(candidates["snr"], errors="coerce").round(2),
                        "Source": candidates["source_file"].fillna(""),
                    }
                )
                candidate_edited = st.data_editor(
                    candidate_frame,
                    width="stretch",
                    hide_index=True,
                    key=f"candidate_editor_{selected_id}_{logbook_editor_epoch}",
                    column_config={
                        "select": st.column_config.CheckboxColumn("Link", width="small"),
                        "Observation ID": st.column_config.NumberColumn(disabled=True),
                        "Local start": st.column_config.TextColumn(disabled=True),
                        "JD": st.column_config.NumberColumn(disabled=True, format="%.6f"),
                        "Mag": st.column_config.NumberColumn(disabled=True, format="%.4f"),
                        "SNR": st.column_config.NumberColumn(disabled=True, format="%.2f"),
                        "Source": st.column_config.TextColumn(disabled=True),
                    },
                )
                link_ids = candidate_edited.loc[
                    candidate_edited["select"].fillna(False), "Observation ID"
                ].astype(int).tolist()
                if st.button(
                    "Link checked observations to this entry",
                    disabled=not link_ids,
                    key=f"candidate_link_button_{selected_id}",
                ):
                    database.link_observations(link_ids, int(selected_id))
                    st.session_state["logbook_editor_epoch"] = logbook_editor_epoch + 1
                    st.session_state["logbook_flash"] = (
                        f"Linked {len(link_ids)} observation(s) to {entry['session_id']}."
                    )
                    st.rerun()

            with st.expander("Delete this entry", expanded=False):
                confirm_delete = st.checkbox(
                    "I understand the observations will be unlinked, not deleted",
                    key=f"confirm_delete_{selected_id}",
                )
                if st.button(
                    "Delete logbook entry",
                    disabled=not confirm_delete,
                    key=f"delete_entry_{selected_id}",
                ):
                    database.delete_logbook_entry(int(selected_id))
                    st.session_state["logbook_flash"] = "Logbook entry deleted. Observations retained."
                    st.session_state.pop("logbook_selected_entry", None)
                    st.rerun()

with tab_new:
    st.subheader("Create a logbook entry")
    st.write(
        "Use this form for an entry without a linked observation selection. To create an entry "
        "from specific measurements, use the Logbook Links tab on the Observations page."
    )
    st.caption("A unique session ID is generated automatically when the entry is created.")
    new_date_key = "new_logbook_date"
    new_start_key = "new_logbook_start"
    new_end_key = "new_logbook_end"
    new_moon_key = "new_logbook_moon"
    new_status_key = "new_logbook_conditions_status"
    ui.show_conditions_status(new_status_key)
    with st.form("create_logbook_entry"):
        form_columns = st.columns(3)
        new_target = form_columns[0].text_input("Target", value="")
        new_date = form_columns[1].text_input(
            "Date (local)", value="", key=new_date_key
        )
        new_time_standard = form_columns[2].text_input(
            "Time standard in CSV", value="Local (Seestar EXP start)"
        )
        form_columns = st.columns(2)
        new_start = form_columns[0].text_input(
            "Start time (local)", value="", key=new_start_key
        )
        new_end = form_columns[1].text_input(
            "End time (local)", value="", key=new_end_key
        )
        form_columns = st.columns(4)
        new_filter = form_columns[0].text_input("Filter", value="Unfiltered")
        new_exposure = form_columns[1].number_input(
            "Exposure (s)", min_value=0.0, value=30.0, step=1.0
        )
        new_frames = form_columns[2].number_input(
            "Frames / points", min_value=0, value=0, step=1
        )
        new_processed = form_columns[3].checkbox("Processed?", value=False)
        new_settings = st.text_input("Seestar mode/settings", value="Seestar")
        form_columns = st.columns(2)
        new_transparency = form_columns[0].text_input("Sky transparency", value="")
        new_seeing = form_columns[1].text_input("Seeing / focus", value="")
        new_moon = st.text_area(
            "Moon / conditions", value="", height=80, key=new_moon_key
        )
        ui.conditions_lookup_caption()
        lookup_columns = st.columns([1, 2])
        lookup_columns[0].form_submit_button(
            "Look up Moon & weather",
            key="new_logbook_lookup_conditions",
            on_click=ui.fill_conditions_from_state,
            args=(
                new_date_key,
                new_start_key,
                new_end_key,
                new_moon_key,
                new_status_key,
            ),
            disabled=ui.observer_coordinates() is None,
            width="stretch",
        )
        new_csv = st.text_input("CSV filename", value="")
        new_notes = st.text_area("Notes / issues", value="")
        create_submit = lookup_columns[1].form_submit_button(
            "Create entry",
            key="new_logbook_create_submit",
            width="stretch",
        )
    if create_submit:
        try:
            if not new_target.strip():
                raise ValueError("Target is required.")
            database.create_logbook_entry(
                {
                    "target_name": new_target,
                    "date_local": new_date,
                    "start_local": new_start,
                    "end_local": new_end,
                    "time_standard": new_time_standard,
                    "filter": new_filter,
                    "exposure_s": new_exposure,
                    "frames": new_frames,
                    "settings": new_settings,
                    "transparency": new_transparency,
                    "seeing": new_seeing,
                    "moon": new_moon,
                    "csv_filename": new_csv,
                    "notes": new_notes,
                    "processed": new_processed,
                }
            )
            st.session_state["logbook_flash"] = "Logbook entry created."
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

with tab_data:
    st.subheader("Workbook and data transfer")
    st.write(
        "The bundled Tampa workbook is auto-seeded once on first launch. Manual imports are "
        "idempotent for entries and update catalog/reference rows."
    )
    workbook_columns = st.columns(2)
    workbook_columns[0].download_button(
        "Download logbook workbook (.xlsx)",
        data=workbook.export_workbook_bytes(),
        file_name="StarLight_Observing_Logbook.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )
    logbook_csv = workbook.logbook_export_frame()
    workbook_columns[1].download_button(
        "Download logbook CSV",
        data=logbook_csv.to_csv(index=False).encode("utf-8-sig"),
        file_name="StarLight_Observation_Log.csv",
        mime="text/csv",
        width="stretch",
    )
    st.divider()
    st.subheader("Import workbook")
    uploaded_workbook = st.file_uploader(
        "Upload a Tampa-style workbook", type=["xlsx"], key="workbook_upload"
    )
    if st.button("Import uploaded workbook", disabled=uploaded_workbook is None):
        try:
            counts = workbook.import_workbook(uploaded_workbook.getvalue())
            st.session_state["logbook_flash"] = (
                "Workbook imported: "
                f"{counts['targets']} target catalog rows, "
                f"{counts['annual_plan_rows']} annual plan rows, "
                f"{counts['logbook_entries']} new logbook entries, "
                f"{counts['references']} references."
            )
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    if st.button("Retry auto-seed from bundled workbook"):
        try:
            counts = workbook.import_workbook()
            st.session_state["logbook_flash"] = (
                f"Bundled workbook imported: {counts['targets']} targets, "
                f"{counts['logbook_entries']} new logbook entries."
            )
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    seed_error = database.get_setting("workbook_seed_error")
    if seed_error:
        st.warning(f"Last auto-seed error: {seed_error}")
    st.info(
        "Back up the entire data directory to preserve the SQLite database, archived CSVs, "
        "logbook entries, and observation links."
    )
