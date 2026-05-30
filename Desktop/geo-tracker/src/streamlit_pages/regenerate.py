"""
Regenerate page — propose new queries while preserving customer history.

Triggered from the Dashboard's "Refresh queries" button. The user lands here
with a `regen_target` already set in session state. Flow:

  1. Confirm/collect URL (uses client.url if stored, else prompts user)
  2. Re-scrape + LLM inference (~15s spinner)
  3. Merge UI: old queries + new proposals, max 5 selected total, edit inline
  4. Save updates the YAML in place — same client_id, same SQLite history

Apples-to-oranges note: regenerating mid-history means the leaderboard
aggregates responses from different prompt sets. We surface this in the UI
so the customer understands the comparison.
"""
import streamlit as st
import yaml
from pathlib import Path

from src.streamlit_styles.yten_theme import apply as apply_theme
from src.client_discovery import get_client

def _normalize_for_match(q: str) -> str:
    """Collapse whitespace and lowercase for comparison."""
    return " ".join(q.split()).lower()


def _dedupe_proposals(existing: list[str], proposed: list[str]) -> tuple[list[str], list[str]]:
    """Return (new_proposals, duplicates) split by whether each proposal
    already exists in the current query set. Case-insensitive, whitespace-normalized."""
    existing_keys = {_normalize_for_match(q) for q in existing}
    new_proposals, duplicates = [], []
    for p in proposed:
        if _normalize_for_match(p) in existing_keys:
            duplicates.append(p)
        else:
            new_proposals.append(p)
    return new_proposals, duplicates

MAX_QUERIES = 5
REGEN_STATE_KEYS = [
    "regen_url", "regen_new_profile",
    "regen_old_selected", "regen_new_selected",
    "regen_old_edited", "regen_new_edited",
    "regen_custom_queries", "regen_duplicates_dropped",
]


def _clear_regen_state(keep_target: bool = False):
    """Wipe regenerate session state. Called on save, cancel, or new target."""
    for k in REGEN_STATE_KEYS:
        st.session_state.pop(k, None)
    if not keep_target:
        st.session_state.pop("regen_target", None)


def _save_in_place(yaml_path: str, existing_cfg: dict,
                   final_queries: list[str], new_profile,
                   url: str) -> None:
    """Update the existing YAML with new queries.

    Preserves: client.id, client.name, all existing variables.
    Replaces: prompts list, removes sweeps block.
    Adds:     client.url if not present (so future regenerates skip prompting).
    Merges:   new industry/geography/audience inferences over blank existing.
    """
    cfg = dict(existing_cfg)
    cfg.setdefault("client", {})

    # Persist URL for next regenerate
    if not cfg["client"].get("url"):
        cfg["client"]["url"] = url

    # Variable merge: new inferences fill blanks in existing
    existing_vars = dict(cfg.get("variables", {}))
    for k, v in [("industry", new_profile.industry),
                 ("geography", new_profile.geography),
                 ("audience", new_profile.audience)]:
        if v and not existing_vars.get(k):
            existing_vars[k] = v
    cfg["variables"] = existing_vars

    # Replace prompts; remove sweeps
    cfg["prompts"] = list(final_queries)
    cfg.pop("sweeps", None)

    with open(yaml_path, "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)


def _render_query_list(prompts, selected_state_key, edited_state_key,
                       column_label, default_checked):
    """Render a column of checkboxes + editable text inputs for a query list.

    Returns the current selected count for this column.
    """
    st.markdown(f"**{column_label}**")
    selected_count = 0
    selected_dict = st.session_state[selected_state_key]
    edited_dict = st.session_state[edited_state_key]

    for i, q in enumerate(prompts):
        cc = st.columns([1, 12])
        with cc[0]:
            # Initialize with default the first time we see this index
            if i not in selected_dict:
                selected_dict[i] = default_checked
            checked = st.checkbox(
                "select",
                value=selected_dict[i],
                key=f"{selected_state_key}_chk_{i}",
                label_visibility="collapsed",
            )
            selected_dict[i] = checked
            if checked:
                selected_count += 1
        with cc[1]:
            if checked:
                edited = st.text_input(
                    "query",
                    value=edited_dict.get(i, q),
                    key=f"{edited_state_key}_input_{i}",
                    label_visibility="collapsed",
                )
                edited_dict[i] = edited
            else:
                # Show greyed-out preview
                st.caption(f":gray[{q}]")

    return selected_count


def render():
    apply_theme()

    target_id = st.session_state.get("regen_target")
    if not target_id:
        st.title("Regenerate Queries")
        st.info(
            "No profile selected. Open a profile from the Dashboard and click "
            "**Refresh queries** to regenerate."
        )
        if st.button("Back to Dashboard"):
            st.session_state.page = "dashboard"
            st.rerun()
        return

    # Load the profile being regenerated
    client_meta = get_client(target_id)
    if not client_meta:
        st.error(f"Profile `{target_id}` not found.")
        _clear_regen_state()
        return

    yaml_path = client_meta["path"]
    try:
        with open(yaml_path) as f:
            existing_cfg = yaml.safe_load(f) or {}
    except Exception as e:
        st.error(f"Could not load `{yaml_path}`: {e}")
        return

    business_name = existing_cfg.get("client", {}).get("name", target_id)
    stored_url = existing_cfg.get("client", {}).get("url", "")
    existing_prompts = existing_cfg.get("prompts", [])

    st.title(f"Refresh queries for {business_name}")
    st.caption(f"Updating profile at `{yaml_path}`")

    # --- Stage 1: collect URL if missing ---------------------------------
    if not st.session_state.get("regen_url"):
        if stored_url:
            st.session_state.regen_url = stored_url
            st.rerun()
        else:
            st.info(
                "This profile was saved before we started storing URLs. "
                "Please enter the website URL so we can re-scrape it."
            )
            with st.form("regen_url_form"):
                url = st.text_input(
                    "Website URL",
                    placeholder="e.g. youretheexpertnow.com",
                )
                submitted = st.form_submit_button("Continue", type="primary")
            if submitted and url:
                st.session_state.regen_url = url
                st.rerun()
            elif submitted:
                st.error("URL is required.")
            return

    # --- Stage 2: regenerate if not done yet -----------------------------
    if st.session_state.get("regen_new_profile") is None:
        with st.spinner("Re-scraping your site and proposing new queries (~15s)..."):
            try:
                from src.query_generator import generate_queries
                profile = generate_queries(business_name, st.session_state.regen_url)

                # Dedupe: proposals that exactly match existing queries are noise
                new_proposals, duplicates = _dedupe_proposals(
                    existing=existing_prompts,
                    proposed=profile.proposed_queries,
                )
                profile.proposed_queries = new_proposals

                st.session_state.regen_new_profile = profile
                st.session_state.regen_duplicates_dropped = duplicates
                # Initialize selection state.
                st.session_state.regen_old_selected = {}
                st.session_state.regen_new_selected = {}
                st.session_state.regen_old_edited = {}
                st.session_state.regen_new_edited = {}
                st.session_state.regen_custom_queries = []  # blank list to append into
            except Exception as e:
                st.error(f"Regeneration failed: {type(e).__name__}: {e}")
                if st.button("Try again with a different URL"):
                    st.session_state.regen_url = None
                    st.rerun()
                return
        st.rerun()

    new_profile = st.session_state.regen_new_profile

    duplicates_dropped = st.session_state.get("regen_duplicates_dropped", [])
    if duplicates_dropped:
        st.caption(
            f"_{len(duplicates_dropped)} of "
            f"{len(duplicates_dropped) + len(new_profile.proposed_queries)} "
            f"proposed queries already match your current set — showing "
            f"{len(new_profile.proposed_queries)} new._"
        )

    if new_profile.warnings:
        with st.expander(f"{len(new_profile.warnings)} warning(s) from regeneration"):
            for w in new_profile.warnings:
                st.warning(w)

    # --- Stage 3: merge UI -----------------------------------------------
    st.subheader("Pick up to 5 queries")
    st.caption(
        "Combine your current queries with newly proposed ones. "
        f"Maximum {MAX_QUERIES} total. Edit any selected query inline. "
        "Historical run data will be preserved — this profile's `client_id` "
        "stays the same."
    )

    # Render columns
    col1, col2 = st.columns(2)
    with col1:
        old_count = _render_query_list(
            existing_prompts,
            "regen_old_selected",
            "regen_old_edited",
            f"Current queries ({len(existing_prompts)})",
            default_checked=True,
        )
    with col2:
        if new_profile.proposed_queries:
            new_count = _render_query_list(
                new_profile.proposed_queries,
                "regen_new_selected",
                "regen_new_edited",
                f"Newly proposed ({len(new_profile.proposed_queries)})",
                default_checked=False,
            )
        else:
            st.markdown("**Newly proposed (0)**")
            st.caption(
                "The auto-generator didn't produce anything new this time. "
                "Your existing queries already cover what it would suggest."
            )
            new_count = 0

    # Custom queries section
    st.markdown("---")
    st.markdown("**Add your own queries**")
    st.caption(
        "Write any query you want to track. These count toward the 5-total cap."
    )
    custom_queries = st.session_state.get("regen_custom_queries", [])
    new_custom = []
    for i, q in enumerate(custom_queries):
        cc = st.columns([10, 1])
        with cc[0]:
            edited = st.text_input(
                f"custom_{i}",
                value=q,
                key=f"regen_custom_input_{i}",
                label_visibility="collapsed",
                placeholder="e.g. AI strategy consultants Buffalo NY",
            )
            new_custom.append(edited)
        with cc[1]:
            if st.button("✕", key=f"regen_custom_del_{i}",
                         help="Remove this custom query"):
                continue  # skip in rebuilt list

    if new_custom != custom_queries:
        st.session_state.regen_custom_queries = new_custom
        st.rerun()

    if st.button("+ Add custom query", key="regen_add_custom",
                 type="secondary"):
        st.session_state.regen_custom_queries.append("")
        st.rerun()

    custom_count = sum(1 for q in st.session_state.regen_custom_queries
                       if q and q.strip())

    total_selected = old_count + new_count + custom_count

    st.divider()
    if total_selected > MAX_QUERIES:
        st.warning(
            f"{total_selected} selected — uncheck {total_selected - MAX_QUERIES} "
            "to enable save."
        )
    elif total_selected == 0:
        st.warning("Select at least one query.")
    else:
        st.success(f"{total_selected} of {MAX_QUERIES} selected — ready to save.")

    # --- Stage 4: save / cancel ------------------------------------------
    can_save = 1 <= total_selected <= MAX_QUERIES

    bcol1, bcol2, _ = st.columns([2, 2, 1])
    with bcol1:
        if st.button(
            "Save updated queries",
            type="primary",
            use_container_width=True,
            disabled=not can_save,
        ):
            # Assemble final list in display order (existing first, then new)
            final_queries = []
            for i, q in enumerate(existing_prompts):
                if st.session_state.regen_old_selected.get(i):
                    final_queries.append(
                        st.session_state.regen_old_edited.get(i, q).strip()
                    )
            for i, q in enumerate(new_profile.proposed_queries):
                if st.session_state.regen_new_selected.get(i):
                    final_queries.append(
                        st.session_state.regen_new_edited.get(i, q).strip()
                    )
            for q in st.session_state.get("regen_custom_queries", []):
                if q and q.strip():
                    final_queries.append(q.strip())
            final_queries = [q for q in final_queries if q]

            try:
                _save_in_place(
                    yaml_path=yaml_path,
                    existing_cfg=existing_cfg,
                    final_queries=final_queries,
                    new_profile=new_profile,
                    url=st.session_state.regen_url,
                )
                _clear_regen_state()
                st.success(
                    f"Profile updated with {len(final_queries)} queries. "
                    f"Run the profile to measure visibility on the new query set."
                )
                st.session_state.page = "dashboard"
                st.rerun()
            except Exception as e:
                st.error(f"Save failed: {type(e).__name__}: {e}")

    with bcol2:
        if st.button("Cancel", type="secondary", use_container_width=True):
            _clear_regen_state()
            st.session_state.page = "dashboard"
            st.rerun()