"""
Streamlit app entry point.

Sidebar:
  - Page nav (Onboarding / Run / Dashboard)
  - Profile selector (lists everything in config/clients/*.yaml)
  - Clicking a profile sets active_client_id and jumps to Dashboard

Multi-user auth deferred to v2. For v1 single-user local, active state
lives in st.session_state.
"""
from dotenv import load_dotenv
load_dotenv()

import streamlit as st

from src.streamlit_styles.yten_theme import apply as apply_theme
from src.streamlit_pages import onboarding, dashboard, run_page, regenerate
from src.client_discovery import list_clients


st.set_page_config(
    page_title="YTEN GEO Tracker",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)
apply_theme()


# --- Session state initialization -------------------------------------
def _init_state():
    defaults = {
        "page": "onboarding",
        "active_client_id": None,    # which profile the dashboard shows
        "run_target": None,           # path of yaml the Run page should run
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_state()


# --- Sidebar ----------------------------------------------------------
with st.sidebar:
    st.title("YTEN")
    st.caption("GEO Visibility Tracker")
    st.divider()

    # Primary nav. When the page state is one of the radio's three options,
    # the radio reflects + drives navigation. When it's something else
    # (e.g. "regenerate"), we still show the radio for context but DON'T
    # let it overwrite the page state — that would clobber programmatic
    # navigation from button clicks elsewhere in the app.
    page_options = ["Onboarding", "Run", "Dashboard"]
    page_keys = ["onboarding", "run", "dashboard"]

    current = st.session_state.page
    in_radio = current in page_keys
    current_index = page_keys.index(current) if in_radio else 0

    chosen = st.radio(
        "Navigate",
        page_options,
        index=current_index,
        label_visibility="collapsed",
    )
    chosen_key = page_keys[page_options.index(chosen)]

    # Only update page state if the user actually changed the radio.
    # When we're on a non-radio page (like "regenerate"), the radio's
    # value is just "whatever was last on a radio page" — ignore it.
    if in_radio and chosen_key != current:
        st.session_state.page = chosen_key
        st.rerun()
    elif not in_radio:
        # On a non-radio page; leave state alone, just show context
        pass
    else:
        # Radio matches current state, no change
        pass

    st.divider()

    # Profile selector
    st.markdown("**Profiles**")
    profiles = list_clients(include_drafts=False)
    if not profiles:
        st.caption("No saved profiles yet. Onboard a new client to get started.")
    else:
        for p in profiles:
            is_active = (p["id"] == st.session_state.active_client_id)
            label = ("◉ " if is_active else "○ ") + p["name"]
            if st.button(label, key=f"profile_{p['id']}",
                         use_container_width=True):
                st.session_state.active_client_id = p["id"]
                st.session_state.page = "dashboard"
                st.rerun()

    # Drafts section (optional, collapsed)
    drafts = list_clients(include_drafts=True)
    drafts = [d for d in drafts if d["is_draft"]]
    if drafts:
        with st.expander(f"Drafts ({len(drafts)})"):
            for d in drafts:
                st.caption(f"{d['name']} — {d['path']}")

    st.divider()
    st.caption("v1 · local · single-user")


# --- Page dispatch ----------------------------------------------------
if st.session_state.page == "onboarding":
    onboarding.render()

elif st.session_state.page == "run":
    run_page.render()

elif st.session_state.page == "dashboard":
    dashboard.render()

elif st.session_state.page == "regenerate":
    from src.streamlit_pages import regenerate
    regenerate.render()

elif st.session_state.page == "edit_prompts":
    from src.streamlit_pages import edit_prompts
    edit_prompts.render()