"""
Dashboard page — the customer's results view.

Layout sections (top to bottom):
  - Page header (profile name, profile id) — static
  - LIVE FRAGMENT: status banner + hero strip + leaderboard
    Re-runs every 5 seconds on its own schedule (no full-page reload).
  - By-prompt drill-down — static, refreshes on page interaction
  - By-model section — static, conditional on len(models_used) >= 2
  - Refresh queries (regenerate trigger) — static
  - Profile management (soft + GDPR hard delete) — static

The fragment scope is deliberate: live data goes in (the things customers
watch tick up during a run), expensive drill-downs stay out (no need to
re-render every 5s).
"""
from pathlib import Path
import yaml
import streamlit as st
import pandas as pd

from src.streamlit_styles.yten_theme import apply as apply_theme, NAVY, GOLD, MUTED
from src.visibility_metrics import compute_metrics, normalize_name
from src.metrics_extensions import (
    models_used, by_prompt, by_model, full_leaderboard,
)
from src import run_status
from src.client_discovery import get_client


REFRESH_INTERVAL_SEC = 5


# ----------------------------------------------------------------------
# Static helpers (called once per page render)
# ----------------------------------------------------------------------

def _empty_state():
    st.title("Dashboard")
    st.info(
        "No profile selected yet. Use the sidebar to pick an existing "
        "profile, or onboard a new business from the Onboarding page."
    )


def _load_client_aliases(client_id: str) -> tuple[str, list[str]]:
    """Read the client's YAML to extract the business name and aliases."""
    client_meta = get_client(client_id)
    if not client_meta:
        return "", []
    try:
        with open(client_meta["path"]) as f:
            data = yaml.safe_load(f) or {}
        name = data.get("client", {}).get("name", client_id)
        variants = data.get("brand_variants", []) or []
        return name, variants
    except Exception:
        return client_id, []


# ----------------------------------------------------------------------
# Fragment-internal helpers (called every REFRESH_INTERVAL_SEC during runs)
# ----------------------------------------------------------------------

def _format_elapsed(started_at_iso: str | None,
                    finished_at_iso: str | None = None) -> str:
    """Format elapsed time between two ISO timestamps as HH:MM:SS.

    If finished_at_iso is None, computes elapsed up to 'now' (UTC) —
    used for the live progress banner during an active run.
    Returns '--:--:--' when started_at is missing or unparseable.
    """
    from datetime import datetime, timezone
    if not started_at_iso:
        return "--:--:--"
    try:
        # Times are stored as UTC ISO strings (datetime.utcnow().isoformat())
        # without timezone suffix — treat as UTC.
        start = datetime.fromisoformat(started_at_iso).replace(
            tzinfo=timezone.utc
        )
        if finished_at_iso:
            end = datetime.fromisoformat(finished_at_iso).replace(
                tzinfo=timezone.utc
            )
        else:
            end = datetime.now(timezone.utc)
        secs = max(0, int((end - start).total_seconds()))
        hours, rem = divmod(secs, 3600)
        mins, secs = divmod(rem, 60)
        return f"{hours:02d}:{mins:02d}:{secs:02d}"
    except Exception:
        return "--:--:--"
    
def _status_banner(client_id: str):
    status = run_status.get_status(client_id)
    if status is None:
        return

    state = status["state"]
    pct = status.get("percent", 0.0)
    completed = status.get("completed_calls", 0)
    total = status.get("total_calls", 0)
    current = status.get("current_prompt_id") or "-"

    if state == "running":
        elapsed = _format_elapsed(status.get("started_at"))
        st.info(
            f"Run in progress · {elapsed} elapsed · {pct:.0f}% complete  \n"
            f"{completed} of {total} calls · currently on {current}"
        )
        st.progress(min(pct / 100, 1.0))
    elif state == "completed":
        elapsed = _format_elapsed(status.get("started_at"),
                                  status.get("finished_at"))
        finished = status.get("finished_at", "")
        st.success(
            f"Run completed in {elapsed} · finished "
            f"{finished[:19].replace('T', ' ')} UTC"
        )
    elif state == "failed":
        st.error(
            f"Run failed: {status.get('error_message', 'unknown error')} "
            f"(progress reached {pct:.0f}%)"
        )
    elif state == "orphaned":
        st.warning(
            "The previous run died without completing. Partial data is shown "
            "below; start a new run for a complete picture."
        )


def _hero_strip(metrics):
    strip = metrics.as_strip()
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Mention Rate", f"{strip['mention_rate_pct']}%",
                  help="How often your business appears in any response.")
        st.caption(strip["mention_rate_caption"])
    with c2:
        if strip["top3_rate_pct"] is not None:
            st.metric("Top-3 Rate", f"{strip['top3_rate_pct']}%",
                      help="Of mentions, what percent ranked in the top 3.")
        else:
            st.metric("Top-3 Rate", "—")
        st.caption(strip["top3_rate_caption"])
    with c3:
        if strip["rank"]:
            st.metric("Rank", f"#{strip['rank']}",
                      help="Position in the competitive leaderboard "
                           "(businesses with ≥2 mentions).")
        else:
            st.metric("Rank", "—")
        st.caption(strip["rank_caption"])

    if "surfaced_caption" in strip:
        st.caption(f"_{strip['surfaced_caption']}_")


def _leaderboard_table(client_id: str, user_aliases: set[str]):
    rows = full_leaderboard(client_id, min_mentions=2, limit=30)
    if not rows:
        st.info("No competitor data yet. Once your run produces responses, "
                "this section will populate.")
        return

    df = pd.DataFrame([
        {
            "Rank": i,
            "Business": r["display_name"],
            "Mentions": r["total_mentions"],
            "Avg Pos": r["avg_position"],
            "Times #1": r["times_ranked_first"],
            "Models": r["models_mentioning"],
        }
        for i, r in enumerate(rows, 1)
    ])
    if "Avg Pos" in df.columns:
        df["Avg Pos"] = df["Avg Pos"].round(1)

    # Track which rows are the user (by dataframe index, not as a column)
    user_row_indices = {
        i for i, r in enumerate(rows) if r["normalized_name"] in user_aliases
    }

    def _highlight(row):
        if row.name in user_row_indices:
            return [f"background-color: {GOLD}33; font-weight: 600"] * len(row)
        return [""] * len(row)

    st.dataframe(
        df.style.apply(_highlight, axis=1),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Rank": st.column_config.NumberColumn(width="small"),
            "Business": st.column_config.TextColumn(width="large"),
            "Mentions": st.column_config.NumberColumn(width="small"),
            "Avg Pos": st.column_config.NumberColumn(width="small", format="%.1f"),
            "Times #1": st.column_config.NumberColumn(width="small"),
            "Models": st.column_config.NumberColumn(width="small"),
        },
    )


# ----------------------------------------------------------------------
# THE LIVE FRAGMENT
# Re-runs every REFRESH_INTERVAL_SEC seconds without re-rendering the rest
# of the page. This is what fixes the "page freezes during refresh" UX.
# ----------------------------------------------------------------------

@st.fragment(run_every=REFRESH_INTERVAL_SEC)
def _live_section(client_id: str, business_name: str,
                  extra_aliases: list[str]):
    """Live-updating block: banner + hero strip + leaderboard.

    Receives stable inputs (aliases) from outer scope, recomputes metrics
    on each refresh. Cost: 3-4 SQL queries every 5s, all cheap.
    """
    _status_banner(client_id)
    st.divider()

    # Fresh metrics on each refresh
    metrics = compute_metrics(
        client_id=client_id,
        business_name=business_name,
        extra_aliases=extra_aliases,
    )

    # Aliases for highlighting can drift during a run as new variants appear;
    # we recompute here so the highlight tracks the latest data.
    user_aliases = set(metrics.matched_normalized_names)
    user_aliases.add(normalize_name(business_name))

    st.subheader("Visibility metrics")
    _hero_strip(metrics)
    st.divider()

    st.subheader("Competitive leaderboard")
    st.caption(
        "Businesses surfaced across your tracked queries. Filtered to those "
        "with at least 2 mentions (long-tail noise hidden)."
    )
    _leaderboard_table(client_id, user_aliases)


# ----------------------------------------------------------------------
# Static sections below the fold (page-interaction refresh only)
# ----------------------------------------------------------------------

def _by_prompt_section(client_id: str, business_aliases: list[str]):
    prompts = by_prompt(client_id, business_aliases)
    if not prompts:
        return

    st.subheader("By prompt")
    st.caption(
        "Which queries surface you, and which don't. Click any prompt to "
        "expand its competitive set."
    )

    for p in prompts:
        rate = p["user_appearance_rate"] * 100
        if rate >= 75:
            indicator = "✓"
        elif rate >= 25:
            indicator = "~"
        else:
            indicator = "✗"

        appearances = f"{p['user_appearances']}/{p['total_responses']}"
        avg_pos = (f", avg pos {p['user_avg_position']}"
                   if p['user_avg_position'] else "")

        with st.expander(
            f"{indicator}  {p['prompt_text']}  ·  you in {appearances} "
            f"({rate:.0f}%){avg_pos}"
        ):
            if p["top_others"]:
                st.caption("Top competitors surfaced for this prompt:")
                df = pd.DataFrame([
                    {
                        "Business": o["display_name"],
                        "Mentions": o["n"],
                        "Avg Pos": o["avg_pos"],
                    }
                    for o in p["top_others"]
                ])
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.caption("No recurring competitors for this prompt yet.")


def _by_model_section(client_id: str, business_aliases: list[str]):
    models = models_used(client_id)
    if len(models) < 2:
        return

    st.subheader("By model")
    st.caption("How each tracked model fares for your business.")

    rows = by_model(client_id, business_aliases)
    df = pd.DataFrame([
        {
            "Model": r["model_name"],
            "Responses": r["total_responses"],
            "You Appeared": r["user_appearances"],
            "Appearance Rate": f"{r['user_appearance_rate']*100:.0f}%",
            "Avg Position": r["user_avg_position"] or "—",
        }
        for r in rows
    ])
    st.dataframe(df, use_container_width=True, hide_index=True)


def _refresh_queries_section(client_id: str):
    """Two affordances:
    - Quick inline editor (edit existing prompts without leaving dashboard)
    - Link to full Edit page (more breathing room for serious revisions)
    - Regenerate trigger (LLM proposals, separate flow)
    """
    import yaml
    from src.client_discovery import get_client

    with st.expander("Edit or refresh queries"):
        # Load current prompts inline so we can edit them right here
        client_meta = get_client(client_id)
        if not client_meta:
            st.error("Could not load profile.")
            return

        try:
            with open(client_meta["path"]) as f:
                cfg = yaml.safe_load(f) or {}
            current_prompts = cfg.get("prompts", [])
        except Exception as e:
            st.error(f"Could not load profile: {e}")
            return

        # --- Quick inline view ----------------------------------------
        st.markdown("**Current queries**")
        st.caption(
            "Quick view. For full editing (add, remove, reorder), open the "
            "full editor below."
        )
        for i, q in enumerate(current_prompts, 1):
            st.markdown(f"{i}. `{q}`")

        st.divider()

        # --- Two actions: edit or regenerate --------------------------
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Open prompt editor**")
            st.caption("Edit text, add custom queries, remove. No re-scraping.")
            if st.button("Edit prompts", key="trigger_edit",
                         use_container_width=True):
                # Clear any stale edit state
                for k in ["edit_queries"]:
                    st.session_state.pop(k, None)
                st.session_state.edit_target = client_id
                st.session_state.page = "edit_prompts"
                st.rerun()

        with col2:
            st.markdown("**Regenerate queries**")
            st.caption("Re-scrape your site, get fresh LLM proposals.")
            st.caption(
                "_Note: leaderboard mixes responses from different prompt "
                "sets across regenerations._"
            )
            if st.button("Regenerate queries", key="trigger_regenerate",
                         use_container_width=True):
                # Clear any stale regenerate state
                for k in ["regen_url", "regen_new_profile",
                          "regen_old_selected", "regen_new_selected",
                          "regen_old_edited", "regen_new_edited",
                          "regen_custom_queries",
                          "regen_duplicates_dropped"]:
                    st.session_state.pop(k, None)
                st.session_state.regen_target = client_id
                st.session_state.page = "regenerate"
                st.rerun()


def _danger_zone(client_id: str, business_name: str):
    """Soft delete (YAML only) + GDPR hard delete (everything)."""
    with st.expander("Profile management", expanded=False):
        st.caption(
            "Two ways to remove this profile. **Soft delete** removes the "
            "profile YAML but preserves historical run data — useful if you "
            "may onboard the same business again. **Erase all data** is a "
            "GDPR-compliant purge that removes everything for this client_id."
        )

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("**Remove profile**")
            st.caption("YAML removed. Run data retained.")
            if st.session_state.get("confirm_soft_delete") == client_id:
                st.warning(f"Confirm removing `{business_name}` profile?")
                cc1, cc2 = st.columns(2)
                with cc1:
                    if st.button("Yes, remove", key="confirm_soft_yes",
                                 type="primary", use_container_width=True):
                        from src.client_discovery import delete_client
                        result = delete_client(client_id, include_drafts=False)
                        if result["errors"]:
                            st.error(f"Failed: {result['errors']}")
                        else:
                            st.session_state.active_client_id = None
                            st.session_state.confirm_soft_delete = None
                            st.rerun()
                with cc2:
                    if st.button("Cancel", key="confirm_soft_no",
                                 use_container_width=True):
                        st.session_state.confirm_soft_delete = None
                        st.rerun()
            else:
                if st.button("Remove profile", key="soft_delete_trigger",
                             use_container_width=True):
                    st.session_state.confirm_soft_delete = client_id
                    st.rerun()

        with col2:
            st.markdown("**Erase all data (GDPR)**")
            st.caption("Profile + run data + logs. Irreversible.")
            if st.session_state.get("confirm_hard_delete") == client_id:
                st.error(
                    f"⚠️ This will PERMANENTLY delete all data for "
                    f"`{business_name}`:\n"
                    f"- The profile YAML\n"
                    f"- All historical run data\n"
                    f"- Subprocess log files\n"
                    f"- Run status records\n\n"
                    f"This cannot be undone. Type the business name to confirm:"
                )
                typed = st.text_input(
                    "Type business name exactly",
                    key="hard_delete_confirm_input",
                    label_visibility="collapsed",
                )
                cc1, cc2 = st.columns(2)
                with cc1:
                    confirm_disabled = (typed != business_name)
                    if st.button(
                        "Erase all data",
                        key="confirm_hard_yes",
                        type="primary",
                        use_container_width=True,
                        disabled=confirm_disabled,
                    ):
                        from src.client_discovery import erase_all_client_data
                        result = erase_all_client_data(client_id)
                        if result["errors"]:
                            st.error(f"Partial failure: {result['errors']}")
                        else:
                            st.success(f"Erased: {result['summary']}")
                        st.session_state.active_client_id = None
                        st.session_state.confirm_hard_delete = None
                        st.rerun()
                with cc2:
                    if st.button("Cancel", key="confirm_hard_no",
                                 use_container_width=True):
                        st.session_state.confirm_hard_delete = None
                        st.rerun()
            else:
                if st.button("Erase all data...", key="hard_delete_trigger",
                             use_container_width=True):
                    st.session_state.confirm_hard_delete = client_id
                    st.rerun()


# ----------------------------------------------------------------------
# Render
# ----------------------------------------------------------------------

def render():
    apply_theme()

    active = st.session_state.get("active_client_id")
    if not active:
        _empty_state()
        return

    business_name, extra_aliases = _load_client_aliases(active)
    if not business_name:
        st.error(f"Could not load profile for {active}.")
        return

    # Compute static aliases once for the drill-down sections
    metrics_init = compute_metrics(active, business_name,
                                   extra_aliases=extra_aliases)
    user_aliases_static = set(metrics_init.matched_normalized_names)
    user_aliases_static.add(normalize_name(business_name))
    user_aliases_list = sorted(user_aliases_static)

    # Header (static)
    st.title(business_name)
    st.caption(f"Profile: `{active}`")

    # Live-updating section (banner + hero + leaderboard) — fragment-scoped
    _live_section(active, business_name, extra_aliases)

    # Static sections below — refresh on page interaction, not on the clock
    st.divider()
    _by_prompt_section(active, user_aliases_list)
    _by_model_section(active, user_aliases_list)

    # Management actions
    st.divider()
    _refresh_queries_section(active)
    _danger_zone(active, business_name)