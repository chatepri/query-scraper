"""
Dashboard page — the customer's results view.

Renders:
  - Status banner (if a run is in progress, completed recently, or failed)
  - Hero metrics strip: 3 columns (mention rate / top-3 rate / rank)
  - Full leaderboard table (filtered to min_mentions for sane competitor counts)
  - By-prompt drill-down (expandable section per prompt)
  - By-model breakdown (rendered only when 2+ models have data)

State contract:
  st.session_state.active_client_id  -- which client's data to show
                                        (set by sidebar profile selector)

If no client is selected, shows an empty state pointing to onboarding.
"""
from pathlib import Path
import yaml
import streamlit as st
import pandas as pd

from src.streamlit_styles.yten_theme import apply as apply_theme, NAVY, GOLD, MUTED
from src.visibility_metrics import compute_metrics
from src.metrics_extensions import (
    models_used, by_prompt, by_model, full_leaderboard,
)
from src import run_status
from src.client_discovery import get_client


REFRESH_INTERVAL_SEC = 5


def _empty_state():
    """Shown when no profile is selected or no data exists yet."""
    st.title("Dashboard")
    st.info(
        "No profile selected yet. Use the sidebar to pick an existing "
        "profile, or onboard a new business from the Onboarding page."
    )


def _status_banner(client_id: str):
    """Renders the run-state banner at the top of the dashboard."""
    status = run_status.get_status(client_id)
    if status is None:
        return

    state = status["state"]
    pct = status.get("percent", 0.0)
    completed = status.get("completed_calls", 0)
    total = status.get("total_calls", 0)
    current = status.get("current_prompt_id") or "-"

    if state == "running":
        st.info(
            f"Run in progress — {pct:.0f}% complete  "
            f"({completed} of {total} calls, currently on {current})"
        )
        st.progress(min(pct / 100, 1.0))
        st.caption(f"This page refreshes every {REFRESH_INTERVAL_SEC}s while a run is active.")
    elif state == "completed":
        finished = status.get("finished_at", "")
        st.success(f"Run completed {finished[:19].replace('T', ' ')} UTC")
    elif state == "failed":
        st.error(
            f"Run failed: {status.get('error_message', 'unknown error')}  "
            f"(progress reached {pct:.0f}%)"
        )
    elif state == "orphaned":
        st.warning(
            "The previous run died without completing. Partial data is shown below; "
            "start a new run for a complete picture."
        )


def _hero_strip(metrics):
    """Three-column metric strip: mention rate, top-3 rate, rank."""
    strip = metrics.as_strip()
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric(
            "Mention Rate",
            f"{strip['mention_rate_pct']}%",
            help="How often your business appears in any response across all prompts and models.",
        )
        st.caption(strip["mention_rate_caption"])
    with c2:
        if strip["top3_rate_pct"] is not None:
            st.metric(
                "Top-3 Rate",
                f"{strip['top3_rate_pct']}%",
                help="Of the times you appeared, what percent ranked in the top 3.",
            )
        else:
            st.metric("Top-3 Rate", "—")
        st.caption(strip["top3_rate_caption"])
    with c3:
        if strip["rank"]:
            st.metric("Rank", f"#{strip['rank']}",
                      help="Your position in the competitive leaderboard "
                           "(businesses with at least 2 mentions).")
        else:
            st.metric("Rank", "—")
        st.caption(strip["rank_caption"])

    if "surfaced_caption" in strip:
        st.caption(f"_{strip['surfaced_caption']}_")


def _leaderboard_table(client_id: str, user_aliases: set[str]):
    """Full ranked leaderboard with the user's row highlighted."""
    rows = full_leaderboard(client_id, min_mentions=2, limit=30)
    if not rows:
        st.info("No competitor data yet. Once your run produces responses, "
                "this section will populate.")
        return

    # Build dataframe with all display columns
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
    # Round Avg Pos to 1 decimal for readability — SQL AVG returns 6 decimals
    if "Avg Pos" in df.columns:
        df["Avg Pos"] = df["Avg Pos"].round(1)

    # Track which rows are the user (by index, not as a dataframe column)
    user_row_indices = {
        i for i, r in enumerate(rows) if r["normalized_name"] in user_aliases
    }

    def _highlight(row):
        # row.name is the dataframe index of this row
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


def _by_prompt_section(client_id: str, business_aliases: list[str]):
    """Expandable section per prompt — which queries surface the user, which don't."""
    prompts = by_prompt(client_id, business_aliases)
    if not prompts:
        return

    st.subheader("By prompt")
    st.caption(
        "Which queries surface you, and which don't. Click to expand each "
        "prompt and see the competitive set."
    )

    for p in prompts:
        # Header line — show user appearance rate at-a-glance
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
            f"{indicator}  {p['prompt_text']}  ·  you in {appearances} ({rate:.0f}%){avg_pos}"
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
    """Per-model breakdown — only rendered when 2+ models have data."""
    models = models_used(client_id)
    if len(models) < 2:
        return  # silently skip; single-model section is redundant

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


def _load_client_aliases(client_id: str) -> tuple[str, list[str]]:
    """Read the client's YAML to extract the business name and aliases."""
    client_meta = get_client(client_id)
    if not client_meta:
        return "", []
    try:
        with open(client_meta["path"]) as f:
            data = yaml.safe_load(f) or {}
        name = data.get("client", {}).get("name", client_id)
        # Use 'brand_variants' if present (hand-curated), else just the name
        variants = data.get("brand_variants", []) or []
        return name, variants
    except Exception:
        return client_id, []

def _danger_zone(client_id: str, business_name: str):
    """Profile management controls. Collapsed by default since deletion
    is destructive — user has to deliberately open it.

    Two tiers:
      - Remove profile (soft delete): YAML gone, run data preserved.
        Reversible by re-onboarding the same business.
      - Erase all data (hard delete, GDPR): YAML + all SQLite data
        + subprocess logs. Irreversible.
    """
    with st.expander("Profile management", expanded=False):
        st.caption(
            "Two ways to remove this profile. **Soft delete** removes the "
            "profile YAML but preserves historical run data — useful if you "
            "may onboard the same business again. **Erase all data** is a "
            "GDPR-compliant purge that removes everything for this client_id."
        )

        col1, col2 = st.columns(2)

        # --- Soft delete -----------------------------------------------
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

        # --- Hard delete (GDPR) ---------------------------------------
        with col2:
            st.markdown("**Erase all data (GDPR)**")
            st.caption("Profile + run data + logs. Irreversible.")
            if st.session_state.get("confirm_hard_delete") == client_id:
                st.error(
                    f"⚠️ This will PERMANENTLY delete all data for "
                    f"`{business_name}`:\n"
                    f"- The profile YAML\n"
                    f"- All historical run data (responses, extractions, citations)\n"
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
                            st.success(
                                f"Erased: {result['summary']}"
                            )
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

def render():
    apply_theme()

    active = st.session_state.get("active_client_id")
    if not active:
        _empty_state()
        return

    business_name, extra_aliases = _load_client_aliases(active)
    if not business_name:
        st.error(f"Could not load profile for {active}. Check that "
                 f"`config/clients/{active}.yaml` exists and is valid.")
        return

    # Compute everything once at the top
    metrics = compute_metrics(
        client_id=active,
        business_name=business_name,
        extra_aliases=extra_aliases,
    )
    user_aliases = set(metrics.matched_normalized_names)
    # Also include the normalized business name itself (covers zero-state case)
    from src.visibility_metrics import normalize_name
    user_aliases.add(normalize_name(business_name))
    user_aliases_list = sorted(user_aliases)

    # --- Page sections ----------------------------------------------------
    st.title(f"{business_name}")
    st.caption(f"Profile: `{active}`")

    _status_banner(active)
    st.divider()

    st.subheader("Visibility metrics")
    _hero_strip(metrics)
    st.divider()

    st.subheader("Competitive leaderboard")
    st.caption(
        "Businesses surfaced across your tracked queries. Filtered to those "
        "with at least 2 mentions (long-tail noise hidden)."
    )
    _leaderboard_table(active, user_aliases)
    st.divider()

    _by_prompt_section(active, user_aliases_list)

    # By-model only renders if 2+ models — internally no-ops otherwise
    _by_model_section(active, user_aliases_list)
    
    # --- Profile management (soft + hard delete) -------------------------
    st.divider()
    _danger_zone(active, business_name)

    # --- Auto-refresh while a run is in progress -------------------------
    status = run_status.get_status(active)
    if status and status.get("state") == "running":
        ...
    # --- Auto-refresh while a run is in progress -------------------------
    status = run_status.get_status(active)
    if status and status.get("state") == "running":
        import time
        time.sleep(REFRESH_INTERVAL_SEC)
        st.rerun()
