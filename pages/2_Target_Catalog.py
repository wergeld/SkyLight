from __future__ import annotations

import pandas as pd
import streamlit as st

from starlight import database, resources, ui

ui.page_setup("Target Catalog", "🗂️")
ui.sidebar_common()

st.title("Target catalog and annual plan")
st.caption(
    "Catalog metadata seeds phase-folding defaults and online resources. "
    "The annual plan and references are imported from the bundled Tampa workbook."
)
ui.preservation_notice()

flash = st.session_state.pop("catalog_flash", None)
if flash:
    st.success(flash)

catalog = database.get_catalog()
annual_plan = database.get_annual_plan()
observed = database.list_observed_targets()
observed_counts = {str(item["target_key"]): int(item["count"]) for item in observed}

catalog_tab, add_tab, plan_tab, resource_tab = st.tabs(
    ["Catalog", "Add Target", "Annual Plan", "Resources"]
)

with catalog_tab:
    st.subheader("Cataloged targets")
    if catalog.empty:
        st.info("The target catalog is empty. Add a target or retry the workbook auto-seed in Logbook.")
    else:
        search = st.text_input("Filter by target, type, constellation, or notes", key="catalog_search")
        filtered = catalog.copy()
        if search:
            needle = search.casefold()
            mask = pd.Series(False, index=filtered.index)
            for column in (
                "target_name",
                "common_designation",
                "variable_type",
                "constellation",
                "notes",
            ):
                if column in filtered:
                    mask = mask | filtered[column].fillna("").astype(str).str.casefold().str.contains(
                        needle, regex=False
                    )
            filtered = filtered[mask]
        display = filtered[
            [
                "target_name",
                "common_designation",
                "variable_type",
                "constellation",
                "brightness_range",
                "period_timescale",
            ]
        ].rename(
            columns={
                "target_name": "Target",
                "common_designation": "Common designation",
                "variable_type": "Variable type",
                "constellation": "Constellation",
                "brightness_range": "Brightness range",
                "period_timescale": "Period / timescale",
            }
        )
        st.dataframe(display, width="stretch", hide_index=True)

        st.divider()
        st.subheader("Open a target")
        ids = filtered["target_key"].astype(str).tolist()
        if not ids:
            st.info("No catalog targets match the filter.")
        else:
            selected_key = st.selectbox(
                "Target record",
                options=ids,
                format_func=lambda key: str(
                    filtered.loc[filtered["target_key"] == key, "target_name"].iloc[0]
                ),
                key="catalog_selected_target",
            )
            target = database.get_catalog_target(selected_key)
            if target:
                metric_columns = st.columns(4)
                metric_columns[0].metric("Imported observations", f"{observed_counts.get(selected_key, 0):,}")
                metric_columns[1].metric("Variable type", str(target.get("variable_type") or "—"))
                metric_columns[2].metric("Constellation", str(target.get("constellation") or "—"))
                period = target.get("period_days")
                metric_columns[3].metric(
                    "Period",
                    f"{float(period):.6f} d" if period else "not recorded",
                )
                ui.render_online_resources(str(target["target_name"]), selected_key)

                with st.expander("Edit target metadata", expanded=True):
                    with st.form(f"edit_target_{selected_key}"):
                        edit_columns = st.columns(2)
                        target_name = edit_columns[0].text_input(
                            "Target", value=str(target.get("target_name") or "")
                        )
                        common = edit_columns[1].text_input(
                            "Common designation",
                            value=str(target.get("common_designation") or ""),
                        )
                        edit_columns = st.columns(2)
                        variable_type = edit_columns[0].text_input(
                            "Variable type", value=str(target.get("variable_type") or "")
                        )
                        constellation = edit_columns[1].text_input(
                            "Constellation", value=str(target.get("constellation") or "")
                        )
                        brightness = st.text_input(
                            "Brightness range", value=str(target.get("brightness_range") or "")
                        )
                        edit_columns = st.columns(2)
                        period_value = edit_columns[0].number_input(
                            "Period (days; 0 = unknown)",
                            min_value=0.0,
                            value=float(target.get("period_days") or 0.0),
                            step=0.0001,
                            format="%.8f",
                        )
                        epoch_value = edit_columns[1].number_input(
                            "Epoch (JD; 0 = none)",
                            min_value=0.0,
                            value=float(target.get("epoch_jd") or 0.0),
                            step=0.01,
                            format="%.6f",
                        )
                        period_timescale = st.text_input(
                            "Period source / timescale",
                            value=str(target.get("period_timescale") or ""),
                        )
                        edit_columns = st.columns(3)
                        season = edit_columns[0].text_input(
                            "Season", value=str(target.get("season") or "")
                        )
                        session_length = edit_columns[1].text_input(
                            "Session length", value=str(target.get("session_length") or "")
                        )
                        cadence = edit_columns[2].text_input(
                            "Cadence / schedule", value=str(target.get("cadence") or "")
                        )
                        project_goal = st.text_area(
                            "Project goal", value=str(target.get("project_goal") or "")
                        )
                        notes = st.text_area("Notes / caveats", value=str(target.get("notes") or ""))
                        save_target = st.form_submit_button("Save target", width="stretch")
                    if save_target:
                        try:
                            database.upsert_catalog_target(
                                {
                                    "target_key": selected_key,
                                    "target_name": target_name,
                                    "common_designation": common,
                                    "variable_type": variable_type,
                                    "constellation": constellation,
                                    "brightness_range": brightness,
                                    "period_days": period_value or None,
                                    "epoch_jd": epoch_value or None,
                                    "period_timescale": period_timescale,
                                    "season": season,
                                    "session_length": session_length,
                                    "cadence": cadence,
                                    "project_goal": project_goal,
                                    "notes": notes,
                                }
                            )
                            database.seed_aliases()
                            resources.ensure_default_resources()
                            st.session_state["catalog_flash"] = "Target catalog entry saved."
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))

                    st.subheader("Aliases")
                    aliases = target.get("aliases") or []
                    if aliases:
                        st.write(", ".join(f"`{alias}`" for alias in aliases))
                    else:
                        st.caption("No aliases recorded.")
                    with st.form(f"add_alias_{selected_key}"):
                        alias_columns = st.columns([3, 1])
                        alias = alias_columns[0].text_input(
                            "New alias (for example, DY Peg)", value=""
                        )
                        add_alias = alias_columns[1].form_submit_button(
                            "Add alias", width="stretch"
                        )
                    if add_alias:
                        if not alias.strip():
                            st.error("Enter an alias first.")
                        else:
                            database.add_alias(alias, selected_key)
                            st.session_state["catalog_flash"] = f"Added alias {alias.strip()}."
                            st.rerun()
                    if aliases:
                        remove_alias = st.selectbox(
                            "Remove an alias",
                            options=["", *aliases],
                            format_func=lambda value: "Select an alias…" if not value else value,
                            key=f"remove_alias_select_{selected_key}",
                        )
                        if st.button(
                            "Remove selected alias",
                            disabled=not remove_alias,
                            key=f"remove_alias_{selected_key}",
                        ):
                            database.delete_alias(remove_alias)
                            st.session_state["catalog_flash"] = "Alias removed."
                            st.rerun()

                with st.expander("Delete target from catalog", expanded=False):
                    st.caption(
                        "Observations and logbook entries are retained. Only the catalog record "
                        "and aliases are removed; archived CSVs remain untouched."
                    )
                    confirm_key = st.checkbox(
                        f"Delete {target['target_name']}",
                        key=f"confirm_catalog_delete_{selected_key}",
                    )
                    if st.button(
                        "Delete catalog target",
                        disabled=not confirm_key,
                        key=f"delete_catalog_{selected_key}",
                    ):
                        database.delete_catalog_target(selected_key)
                        st.session_state["catalog_flash"] = "Catalog target deleted."
                        st.session_state.pop("catalog_selected_target", None)
                        st.rerun()

with add_tab:
    st.subheader("Add a target")
    st.write(
        "The normalized target name becomes the catalog key. Add aliases so CSVs using other "
        "designations resolve to the same target."
    )
    with st.form("add_catalog_target"):
        add_columns = st.columns(2)
        new_name = add_columns[0].text_input("Target name", value="")
        new_common = add_columns[1].text_input("Common designation", value="")
        add_columns = st.columns(2)
        new_type = add_columns[0].text_input("Variable type", value="")
        new_constellation = add_columns[1].text_input("Constellation", value="")
        new_brightness = st.text_input("Brightness range", value="")
        add_columns = st.columns(2)
        new_period = add_columns[0].number_input(
            "Period (days; 0 = unknown)", min_value=0.0, value=0.0, step=0.0001, format="%.8f"
        )
        new_epoch = add_columns[1].number_input(
            "Epoch (JD; 0 = none)", min_value=0.0, value=0.0, step=0.01, format="%.6f"
        )
        new_period_text = st.text_input("Period source / timescale", value="")
        new_season = st.text_input("Season", value="")
        new_session = st.text_input("Session length", value="")
        new_cadence = st.text_input("Cadence / schedule", value="")
        new_goal = st.text_area("Project goal", value="")
        new_notes = st.text_area("Notes / caveats", value="")
        new_alias = st.text_input("Aliases (comma separated, optional)", value="")
        add_submit = st.form_submit_button("Add target", width="stretch")
    if add_submit:
        try:
            if not new_name.strip():
                raise ValueError("Target name is required.")
            target_key = database.upsert_catalog_target(
                {
                    "target_name": new_name,
                    "common_designation": new_common,
                    "variable_type": new_type,
                    "constellation": new_constellation,
                    "brightness_range": new_brightness,
                    "period_days": new_period or None,
                    "epoch_jd": new_epoch or None,
                    "period_timescale": new_period_text,
                    "season": new_season,
                    "session_length": new_session,
                    "cadence": new_cadence,
                    "project_goal": new_goal,
                    "notes": new_notes,
                }
            )
            for alias in [new_common, *new_alias.split(",")]:
                if alias.strip():
                    database.add_alias(alias, target_key)
            resources.ensure_default_resources()
            st.session_state["catalog_flash"] = f"Added {new_name.strip()} to the catalog."
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

with plan_tab:
    st.subheader("Annual observing plan")
    if annual_plan.empty:
        st.info("No annual plan is stored. Use Logbook → Import / Export to import the workbook.")
    else:
        plan_display = annual_plan[
            [
                "when_text",
                "primary_targets",
                "what_to_do",
                "time_per_target",
                "repeat_cadence",
                "deliverable",
                "priority",
            ]
        ].rename(
            columns={
                "when_text": "When",
                "primary_targets": "Primary target(s)",
                "what_to_do": "What to do",
                "time_per_target": "Time per target",
                "repeat_cadence": "Repeat cadence",
                "deliverable": "Deliverable / milestone",
                "priority": "Priority",
            }
        )
        st.dataframe(plan_display, width="stretch", hide_index=True)
        st.download_button(
            "Download annual plan CSV",
            data=plan_display.to_csv(index=False).encode("utf-8-sig"),
            file_name="StarLight_Annual_Plan.csv",
            mime="text/csv",
        )

with resource_tab:
    st.subheader("Online resources")
    st.write(
        "Global references and target-specific catalog links. StarLight also generates standard "
        "AAVSO, SIMBAD, VizieR, and VSP links for every target."
    )
    stored_resources = database.get_resources()
    if stored_resources:
        resource_frame = pd.DataFrame(stored_resources)
        resource_frame["target"] = resource_frame["target_key"].fillna("Global")
        st.dataframe(
            resource_frame[["id", "target", "category", "label", "url", "notes", "source"]].rename(
                columns={
                    "id": "ID",
                    "target": "Target",
                    "category": "Category",
                    "label": "Label",
                    "url": "URL",
                    "notes": "Notes",
                    "source": "Source",
                }
            ),
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("No stored resources yet.")

    with st.form("add_resource"):
        st.subheader("Add a resource")
        target_options = {"Global": None, **{str(row["target_name"]): str(row["target_key"]) for _, row in catalog.iterrows()}}
        resource_target = st.selectbox("Applies to", options=list(target_options), index=0)
        resource_columns = st.columns(3)
        resource_label = resource_columns[0].text_input("Label", value="")
        resource_category = resource_columns[1].text_input("Category", value="Reference")
        resource_url = resource_columns[2].text_input("URL", value="https://")
        resource_notes = st.text_input("Notes / use", value="")
        add_resource = st.form_submit_button("Add resource", width="stretch")
    if add_resource:
        if not resource_label.strip() or not resource_url.strip().startswith(("http://", "https://")):
            st.error("Enter a label and a valid http(s) URL.")
        else:
            try:
                database.upsert_resource(
                    {
                        "target_key": target_options[resource_target],
                        "label": resource_label,
                        "url": resource_url,
                        "category": resource_category,
                        "notes": resource_notes,
                        "source": "User",
                    }
                )
                st.session_state["catalog_flash"] = "Resource saved."
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    if stored_resources:
        delete_resource_id = st.selectbox(
            "Delete a resource",
            options=[""] + [int(item["id"]) for item in stored_resources],
            format_func=lambda value: "Select a resource…"
            if not value
            else next(
                f"{item['label']} · {item['url']}"
                for item in stored_resources
                if int(item["id"]) == int(value)
            ),
            key="delete_resource_id",
        )
        if st.button("Delete selected resource", disabled=not delete_resource_id):
            database.delete_resource(int(delete_resource_id))
            st.session_state["catalog_flash"] = "Resource deleted."
            st.rerun()
