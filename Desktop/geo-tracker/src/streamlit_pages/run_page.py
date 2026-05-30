"""
Run page — kicks off a subprocess run, then sends the user to the dashboard.

Flow:
  1. Read st.session_state.run_target (set by onboarding's "Save and Run Now"
     button OR by sidebar "Run This Profile" action)
  2. Show confirmation: which profile, which mode, estimated time/cost
  3. On confirm: launch subprocess, set active_client_id, redirect to dashboard
  4. Dashboard's progress banner takes over from there

If no run_target is set, show an empty state with options.
"""
import streamlit as st
import yaml
from pathlib import Path

from src.streamlit_styles.yten_theme import apply as apply_theme
from src.subprocess_runner import launch_run
from src.client_discovery import list_clients
from src import run_status


MODE_INFO = {
    "test":    {"iters": 10,  "label": "Test",    "desc": "Quick validation, lowest cost",   "time": "~6 min"},
    "preview": {"iters": 30,  "label": "Preview", "desc": "Live customer default",          "time": "~25 min"},
    "audit":   {"iters": 100, "label": "Audit",   "desc": "Pro-tier deep audit",            "time": "~3 hours"},
}


def _profile_summary(client_path: str) -> dict:
    """Read the YAML to show the user what's about to run."""
    with open(client_path) as f:
        data = yaml.safe_load(f) or {}
    return {
        "name": data.get("client", {}).get("name", "?"),
        "id": data.get("client", {}).get("id", "?"),
        "prompts": data.get("prompts", []),
        "sweeps": data.get("sweeps", []),
    }


def render():
    apply_theme()
    st.title("Run")

    # Determine what we're about to run
    target = st.session_state.get("run_target")

    # If no target, show profile picker
    if not target:
        st.caption("Pick a profile to run, or start a new one from Onboarding.")
        profiles = list_clients(include_drafts=False)
        if not profiles:
            st.info("No profiles saved yet. Use Onboarding to create one.")
            return

        choice = st.selectbox(
            "Profile",
            options=profiles,
            format_func=lambda p: f"{p['name']} ({p['id']})",
            key="run_profile_picker",
        )
        if st.button("Select", type="primary"):
            st.session_state.run_target = choice["path"]
            st.rerun()
        return

    # Show confirmation panel
    try:
        summary = _profile_summary(target)
    except Exception as e:
        st.error(f"Could not read profile at {target}: {e}")
        if st.button("Pick a different profile"):
            st.session_state.run_target = None
            st.rerun()
        return

    st.subheader(summary["name"])
    st.caption(f"Profile: `{target}`")

    # Show what'll run
    with st.expander(f"{len(summary['prompts'])} explicit prompts" +
                     (f" + {len(summary['sweeps'])} sweep block(s)" if summary['sweeps'] else "")):
        for i, p in enumerate(summary["prompts"], 1):
            st.markdown(f"{i}. {p}")
        if summary["sweeps"]:
            st.caption("Plus combinatorial expansion from sweeps.")

    # Mode selection
    st.markdown("### Run mode")
    mode_choice = st.radio(
        "Iterations per prompt per model",
        options=["test", "preview", "audit"],
        index=1,  # default to preview
        format_func=lambda m: (
            f"{MODE_INFO[m]['label']} — {MODE_INFO[m]['iters']} iters "
            f"({MODE_INFO[m]['time']}, {MODE_INFO[m]['desc']})"
        ),
        key="run_mode_choice",
    )

    # Show what's already happening for this profile, if anything
    client_id = summary["id"]
    current = run_status.get_status(client_id)
    if current and current.get("state") == "running":
        st.warning(
            f"A run is already in progress for this profile "
            f"({current['percent']:.0f}% complete). Starting a new run will "
            f"overwrite the progress counter, but in-flight subprocess will "
            f"continue and may interfere. Recommend waiting."
        )

    # Action buttons
    col1, col2 = st.columns([2, 1])
    with col1:
        if st.button(
            f"Start {MODE_INFO[mode_choice]['label']} Run",
            type="primary",
            use_container_width=True,
        ):
            try:
                pid = launch_run(client_yaml_path=target, mode=mode_choice)
                st.session_state.active_client_id = client_id
                st.session_state.run_target = None  # consume
                st.success(
                    f"Run started (PID {pid}). Redirecting to dashboard..."
                )
                st.session_state.page = "dashboard"
                st.rerun()
            except Exception as e:
                st.error(f"Failed to start run: {type(e).__name__}: {e}")

    with col2:
        if st.button("Cancel", type="secondary", use_container_width=True):
            st.session_state.run_target = None
            st.rerun()