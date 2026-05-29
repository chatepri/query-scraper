"""
Streamlit app entry point.

Routes between three pages based on session state:
  - onboarding    -- name+URL form, auto-gen, edit, save
  - run           -- progress bar during the live run (next commit)
  - dashboard     -- leaderboard + metric strip (next commit)

For v1 (local single-user) the router is simple: sidebar nav + state.
Multi-user auth deferred to v2.

Run with:
    python -m streamlit run streamlit_app.py
"""
from dotenv import load_dotenv
load_dotenv()

import streamlit as st

from src.streamlit_styles.yten_theme import apply as apply_theme
from src.streamlit_pages import onboarding


st.set_page_config(
    page_title="YTEN GEO Tracker",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_theme()


# --- Sidebar nav ------------------------------------------------------
with st.sidebar:
    st.title("YTEN")
    st.caption("GEO Visibility Tracker")
    st.divider()

    # Page selector — for v1 we keep it explicit and minimal.
    # In Commit 3 the dashboard becomes the default landing when results exist.
    if "page" not in st.session_state:
        st.session_state.page = "onboarding"

    page = st.radio(
        "Navigate",
        ["Onboarding", "Run", "Dashboard"],
        index=["onboarding", "run", "dashboard"].index(st.session_state.page),
        label_visibility="collapsed",
    )
    st.session_state.page = page.lower()

    st.divider()
    st.caption("v1 · local · single-user")


# --- Page dispatch ----------------------------------------------------
if st.session_state.page == "onboarding":
    onboarding.render()

elif st.session_state.page == "run":
    st.title("Run")
    st.info(
        "The Run page lands in Commit 3. It will pick up the saved profile "
        "from onboarding and stream results as each prompt completes."
    )
    saved = st.session_state.get("ob_saved_path")
    if saved:
        st.caption(f"Last saved profile: {saved}")

elif st.session_state.page == "dashboard":
    st.title("Dashboard")
    st.info(
        "The Dashboard lands in Commit 3. It will read the SQLite store and "
        "show the three hero metrics plus the leaderboard."
    )