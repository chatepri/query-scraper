"""
Edit prompts page — direct editing without re-scraping or LLM inference.

Use case: customer knows exactly what they want to fix (a typo, a stale
location, replace a low-signal query). They don't need new LLM proposals,
just an editor for their current 5 queries.

Flow:
  1. Load existing prompts from the profile YAML
  2. User edits inline, adds custom queries, removes ones they don't want
  3. Save updates the YAML in place — same client_id, same history
"""
import streamlit as st
import yaml

from src.streamlit_styles.yten_theme import apply as apply_theme
from src.client_discovery import get_client


MAX_QUERIES = 5
EDIT_STATE_KEYS = ["edit_queries"]


def _clear_edit_state(keep_target: bool = False):
    for k in EDIT_STATE_KEYS:
        st.session_state.pop(k, None)
    if not keep_target:
        st.session_state.pop("edit_target", None)


def _save_in_place(yaml_path: str, existing_cfg: dict,
                   final_queries: list[str]) -> None:
    """Update the YAML's prompts list. Preserves everything else (variables,
    client.id/name/url, etc.). Strips any sweeps block since we don't expose
    that in the editor."""
    cfg = dict(existing_cfg)
    cfg["prompts"] = list(final_queries)
    cfg.pop("sweeps", None)
    with open(yaml_path, "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)


def render():
    apply_theme()

    target_id = st.session_state.get("edit_target")
    if not target_id:
        st.title("Edit prompts")
        st.info(
            "No profile selected. Open a profile from the Dashboard and click "
            "**Edit prompts** to make direct edits."
        )
        if st.button("Back to Dashboard"):
            st.session_state.page = "dashboard"
            st.rerun()
        return

    client_meta = get_client(target_id)
    if not client_meta:
        st.error(f"Profile `{target_id}` not found.")
        _clear_edit_state()
        return

    yaml_path = client_meta["path"]
    try:
        with open(yaml_path) as f:
            existing_cfg = yaml.safe_load(f) or {}
    except Exception as e:
        st.error(f"Could not load `{yaml_path}`: {e}")
        return

    business_name = existing_cfg.get("client", {}).get("name", target_id)
    existing_prompts = existing_cfg.get("prompts", [])

    # Initialize editable state on first visit (or if profile changed)
    if "edit_queries" not in st.session_state:
        st.session_state.edit_queries = list(existing_prompts)

    st.title(f"Edit prompts for {business_name}")
    st.caption(f"Updating profile at `{yaml_path}`")

    st.caption(
        "Direct editor for your current queries. Edit text inline, "
        f"remove with ✕, or add new ones. Maximum {MAX_QUERIES} queries. "
        "No re-scraping — use **Refresh queries** if you want LLM proposals."
    )

    st.divider()

    # Render editable list with delete buttons
    queries = list(st.session_state.edit_queries)
    new_queries = []
    for i, q in enumerate(queries):
        ecol, dcol = st.columns([10, 1])
        with ecol:
            edited = st.text_input(
                f"query_{i}",
                value=q,
                key=f"edit_input_{i}",
                label_visibility="collapsed",
            )
        with dcol:
            if st.button("✕", key=f"edit_del_{i}",
                         help="Remove this query"):
                continue  # skip in rebuilt list
            new_queries.append(edited)

    if new_queries != st.session_state.edit_queries:
        st.session_state.edit_queries = new_queries
        st.rerun()

    # Add button (disabled at cap)
    can_add = len(st.session_state.edit_queries) < MAX_QUERIES
    add_label = (
        "+ Add query" if can_add
        else f"Maximum {MAX_QUERIES} queries reached"
    )
    if st.button(add_label, type="secondary", disabled=not can_add):
        st.session_state.edit_queries.append("")
        st.rerun()

    st.divider()

    # Validation + save
    valid_queries = [q for q in st.session_state.edit_queries if q.strip()]

    if not valid_queries:
        st.warning("Add at least one non-empty query before saving.")
        save_disabled = True
    elif len(valid_queries) > MAX_QUERIES:
        st.warning(f"{len(valid_queries)} queries — remove "
                   f"{len(valid_queries) - MAX_QUERIES} to enable save.")
        save_disabled = True
    else:
        st.success(f"{len(valid_queries)} of {MAX_QUERIES} queries — ready to save.")
        save_disabled = False

    # Show what changed compared to disk (helpful for "did I actually edit anything?")
    if [q.strip() for q in valid_queries] != [q.strip() for q in existing_prompts]:
        with st.expander("Preview changes"):
            st.markdown("**Current (on disk):**")
            for q in existing_prompts:
                st.markdown(f"- `{q}`")
            st.markdown("**After save:**")
            for q in valid_queries:
                st.markdown(f"- `{q}`")

    bcol1, bcol2, _ = st.columns([2, 2, 1])
    with bcol1:
        if st.button(
            "Save edits",
            type="primary",
            use_container_width=True,
            disabled=save_disabled,
        ):
            try:
                _save_in_place(
                    yaml_path=yaml_path,
                    existing_cfg=existing_cfg,
                    final_queries=valid_queries,
                )
                _clear_edit_state()
                st.success(f"Saved {len(valid_queries)} queries.")
                st.session_state.page = "dashboard"
                st.rerun()
            except Exception as e:
                st.error(f"Save failed: {type(e).__name__}: {e}")

    with bcol2:
        if st.button("Cancel", type="secondary", use_container_width=True):
            _clear_edit_state()
            st.session_state.page = "dashboard"
            st.rerun()