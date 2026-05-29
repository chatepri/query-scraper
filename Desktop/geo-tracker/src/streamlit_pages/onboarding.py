"""
Onboarding page — the customer's first experience.

Flow:
  1. Empty state: name + URL form, single 'Generate Queries' button
  2. After generate: inferred profile (read-only) + editable query list
  3. User edits/adds/deletes (capped at 5 queries)
  4. Two save buttons: 'Save and Run Now' / 'Save for Later'

Session state contract:
  ob_profile         -- the BusinessProfile after auto-gen (None until generated)
  ob_queries         -- current editable list of query strings
  ob_client_id       -- derived from business name, used as filename
  ob_saved_path      -- set after a successful save (YAML path)
  ob_next_action     -- 'run' | 'later' | None, drives routing after save
"""
import streamlit as st
from pathlib import Path
from datetime import datetime
import re

from src.streamlit_styles.yten_theme import apply as apply_theme, NAVY, GOLD, MUTED


MAX_QUERIES = 5
AUTO_DIR = Path("config/clients/auto")
SAVED_DIR = Path("config/clients")


def _slugify(name: str) -> str:
    """Convert business name to a safe filename slug."""
    s = re.sub(r"[^a-zA-Z0-9_\s-]", "", name).strip().lower()
    s = re.sub(r"[\s-]+", "_", s)
    return s[:48] or "client"


def _init_state():
    """Ensure session state keys exist (Streamlit reruns the file every interaction)."""
    defaults = {
        "ob_profile": None,
        "ob_queries": [],
        "ob_client_id": "",
        "ob_saved_path": None,
        "ob_next_action": None,
        "ob_gen_warnings": [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _reset():
    """Clear onboarding state — used by 'Start Over' button."""
    for k in ["ob_profile", "ob_queries", "ob_client_id",
              "ob_saved_path", "ob_next_action", "ob_gen_warnings"]:
        st.session_state[k] = None if k != "ob_queries" else []
        if k in ("ob_client_id", "ob_gen_warnings"):
            st.session_state[k] = "" if k == "ob_client_id" else []


def _generate(name: str, url: str):
    """Call the auto-generator and populate session state."""
    from src.query_generator import generate_queries
    profile = generate_queries(name, url)
    st.session_state.ob_profile = profile
    st.session_state.ob_queries = list(profile.proposed_queries)
    st.session_state.ob_client_id = _slugify(name)
    st.session_state.ob_gen_warnings = list(profile.warnings)


def _save_yaml(target_dir: Path, mark_as_draft: bool) -> Path:
    """Write a runnable client YAML. Returns the path."""
    import yaml
    target_dir.mkdir(parents=True, exist_ok=True)

    profile = st.session_state.ob_profile
    queries = [q.strip() for q in st.session_state.ob_queries if q and q.strip()]
    client_id = st.session_state.ob_client_id

    if mark_as_draft:
        ts = datetime.now().strftime("%Y_%m_%d_%H_%M")
        path = target_dir / f"{client_id}_{ts}.yaml"
    else:
        path = target_dir / f"{client_id}.yaml"

    cfg = {
        "client": {"id": client_id, "name": profile.name},
        "variables": {
            "industry": profile.industry or "",
            "geography": profile.geography or "",
            "audience": profile.audience or "",
        },
        "prompts": queries,
    }

    header = ""
    if mark_as_draft:
        header = (
            f"# AUTO-GENERATED DRAFT — saved from onboarding for later use\n"
            f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"# Source: scrape of {profile.url} + LLM inference\n"
            f"# Move to config/clients/<id>.yaml when ready to run.\n\n"
        )

    with open(path, "w") as f:
        if header:
            f.write(header)
        yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)
    return path


# ----------------------------------------------------------------------
# Page render
# ----------------------------------------------------------------------

def render():
    apply_theme()
    _init_state()

    st.title("Set up your visibility profile")
    st.caption("Enter your business details. We'll scrape your site, "
               "propose 5 prospect-style queries, and let you edit before running.")

    # --- Stage 1: input form ----------------------------------------------
    if st.session_state.ob_profile is None:
        with st.form("onboard_form", clear_on_submit=False):
            col1, col2 = st.columns([2, 3])
            with col1:
                name = st.text_input(
                    "Business name",
                    placeholder="e.g. You're The Expert Now",
                )
            with col2:
                url = st.text_input(
                    "Website URL",
                    placeholder="e.g. youretheexpertnow.com",
                )
            submitted = st.form_submit_button(
                "Generate Queries", type="primary", use_container_width=False,
            )

        if submitted:
            if not name or not url:
                st.error("Please enter both a business name and a website URL.")
                return
            with st.spinner("Scraping your site and proposing queries (~15s)..."):
                try:
                    _generate(name, url)
                except Exception as e:
                    st.error(f"Generation failed: {type(e).__name__}: {e}")
                    return
            st.rerun()
        return

    # --- Stage 2: review and edit ----------------------------------------
    profile = st.session_state.ob_profile

    st.subheader("What we found")
    pcol1, pcol2 = st.columns(2)
    with pcol1:
        st.markdown(f"**Industry**  \n{profile.industry or '*not detected*'}")
        st.markdown(f"**Geography**  \n{profile.geography or '*not detected*'}")
    with pcol2:
        st.markdown(f"**Audience**  \n{profile.audience or '*not detected*'}")
        st.markdown(f"**Pages scraped**  \n{len(profile.scraped_pages)}")

    if st.session_state.ob_gen_warnings:
        with st.expander(f"{len(st.session_state.ob_gen_warnings)} warning(s)"):
            for w in st.session_state.ob_gen_warnings:
                st.warning(w)

    st.divider()
    st.subheader("Review and edit your queries")
    st.caption(
        f"Up to {MAX_QUERIES} queries. Edit any text inline. "
        "Use ✕ to remove. These should be how a real prospect would search."
    )

    # --- Editable query list ---------------------------------------------
    # Use a copy so we can mutate during render without invalidating the loop
    queries = list(st.session_state.ob_queries)

    new_queries: list[str] = []
    for i, q in enumerate(queries):
        ecol, dcol = st.columns([10, 1])
        with ecol:
            edited = st.text_input(
                f"Query {i + 1}",
                value=q,
                key=f"ob_q_{i}",
                label_visibility="collapsed",
            )
        with dcol:
            if st.button("✕", key=f"ob_del_{i}", help="Remove this query"):
                # Skip this one in the rebuilt list
                continue
            new_queries.append(edited)

    # Detect changes (text edits OR deletes) and persist
    if new_queries != st.session_state.ob_queries:
        st.session_state.ob_queries = new_queries
        st.rerun()

    # Add button (disabled at cap)
    can_add = len(st.session_state.ob_queries) < MAX_QUERIES
    if st.button(
        "+ Add custom query" if can_add else f"Maximum {MAX_QUERIES} queries reached",
        disabled=not can_add,
        type="secondary",
    ):
        st.session_state.ob_queries.append("")
        st.rerun()

    st.divider()

    # --- Action row ------------------------------------------------------
    valid_queries = [q for q in st.session_state.ob_queries if q.strip()]
    if not valid_queries:
        st.warning("Add at least one non-empty query before saving.")
        return

    acol1, acol2, acol3 = st.columns([2, 2, 1])
    with acol1:
        if st.button("Save and Run Now", type="primary", use_container_width=True):
            try:
                path = _save_yaml(SAVED_DIR, mark_as_draft=False)
                st.session_state.ob_saved_path = str(path)
                st.session_state.ob_next_action = "run"
                st.success(f"Saved profile → {path}")
                st.rerun()
            except Exception as e:
                st.error(f"Save failed: {e}")

    with acol2:
        if st.button("Save for Later", type="secondary", use_container_width=True):
            try:
                path = _save_yaml(AUTO_DIR, mark_as_draft=True)
                st.session_state.ob_saved_path = str(path)
                st.session_state.ob_next_action = "later"
                st.success(f"Draft saved → {path}")
                st.rerun()
            except Exception as e:
                st.error(f"Save failed: {e}")

    with acol3:
        if st.button("Start Over", type="secondary", use_container_width=True):
            _reset()
            st.rerun()

    # --- Post-save: show the routing decision the app router will use ----
    if st.session_state.ob_next_action == "run":
        st.info(
            f"Profile saved. The Run page will pick this up and start your "
            f"preview run (30 iterations × {len(valid_queries)} prompts × 1 model). "
            f"Estimated wait: ~25 minutes."
        )
    elif st.session_state.ob_next_action == "later":
        st.info(
            "Draft saved. You can review the YAML directly, or come back to "
            "this app and load the profile when you're ready to run."
        )


if __name__ == "__main__":
    render()