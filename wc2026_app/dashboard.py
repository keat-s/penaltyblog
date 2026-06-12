"""WC2026 Streamlit dashboard — layout only.

All logic lives in wc26.slate / wc26.data / wc26.cache / wc26.knockout /
wc26.providers.  This file contains no testable business logic; it is
excluded from the test suite.

Launch from wc2026_app/:
    streamlit run dashboard.py
"""

from __future__ import annotations

import io
import os
import time
from datetime import date, datetime

import pandas as pd
import streamlit as st

from penaltyblog.betting.kelly import kelly_criterion

from wc26.cache import fit_cached
from wc26.data import fixtures, load_results, training_data
from wc26 import knockout, props, slate
from wc26.live import live_grid
from wc26.providers import make_provider

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="WC2026 Betting Dashboard",
    page_icon="⚽",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Honest-expectations banner
# ---------------------------------------------------------------------------
st.caption(
    "Model-based EV is a few percent of turnover at best — roughly a 1-in-5 chance "
    "that a +EV tournament ends negative. The in-play module is **experimental**: "
    "no verified evidence shows realized in-play ROI net of margin. "
    "See [docs/methodology.md](docs/methodology.md) for assumptions and limitations."
)

# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------
if "api_call_count" not in st.session_state:
    st.session_state.api_call_count = 0

# ---------------------------------------------------------------------------
# Sidebar controls
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Settings")

    bankroll = st.number_input(
        "Bankroll (£)",
        min_value=0.0,
        value=1000.0,
        step=50.0,
    )

    kelly_fraction = st.slider(
        "Kelly fraction",
        min_value=0.05,
        max_value=0.50,
        value=0.25,
        step=0.05,
        help="Fractional Kelly stake sizing (0.25 = quarter-Kelly).",
    )

    min_ev = st.slider(
        "Minimum EV",
        min_value=0.00,
        max_value=0.10,
        value=0.02,
        step=0.005,
        format="%.3f",
        help="Only recommend bets with EV ≥ this threshold.",
    )

    asof = st.date_input(
        "As-of date (model cutoff)",
        value=date.today(),
        help="Model is trained on matches before this date.",
    )

    model_kind = st.selectbox(
        "Model kind",
        options=["dixon_coles", "poisson", "bivariate", "negbin"],
        index=0,
    )

    provider_name = st.selectbox(
        "Odds provider",
        options=["api-football", "sportmonks", "csv-upload"],
        index=0,
    )

    # Key status indicator — show set/missing, never the value
    _key_env = {
        "api-football": "WC26_APIFOOTBALL_KEY",
        "sportmonks": "WC26_SPORTMONKS_KEY",
        "csv-upload": None,
    }
    _env_var = _key_env.get(provider_name)
    if _env_var is not None:
        if os.environ.get(_env_var):
            st.success(f"`{_env_var}` set ✓")
        else:
            st.warning(f"`{_env_var}` missing")
    else:
        st.info("CSV upload — no API key needed")

    refresh_interval = st.slider(
        "Live refresh interval (s)",
        min_value=5,
        max_value=60,
        value=15,
        step=5,
    )
    st.session_state.refresh_interval = refresh_interval

    st.metric("API calls this session", st.session_state.api_call_count)


# ---------------------------------------------------------------------------
# Provider call counter wrapper
# ---------------------------------------------------------------------------

def _make_counted_provider(name: str, env_var: str | None):
    """Build provider *name*, wrapping live_state / odds so each call
    increments st.session_state.api_call_count.

    *env_var* is the environment variable holding the API key (None for
    keyless providers). Returns None if the provider cannot be built.
    """
    if name == "csv-upload":
        # CSV upload path — no live provider needed; return None
        return None

    key_val = os.environ.get(env_var) if env_var else None

    try:
        raw = make_provider(name, api_key=key_val)
    except Exception:
        return None

    class _Counted:
        def __init__(self):
            self.name = raw.name

        def live_state(self, home, away):
            st.session_state.api_call_count += 1
            return raw.live_state(home, away)

        def odds(self, home, away, date=None):
            st.session_state.api_call_count += 1
            # Pre-match fixtures are only findable by date — without it the
            # adapters' live-fixture search misses and returns no quotes.
            return raw.odds(home, away, date=date)

        # Props endpoints (api-football only). Disk-cached upstream, so the
        # session counter records calls made, not raw HTTP requests.
        def player_goal_stats(self, team_name, season):
            if not hasattr(raw, "player_goal_stats"):
                raise RuntimeError(
                    f"provider '{raw.name}' does not support player statistics"
                )
            st.session_state.api_call_count += 1
            return raw.player_goal_stats(team_name, season)

        def team_stat_records(self, team_name, last_n=20, stat="corners"):
            if not hasattr(raw, "team_stat_records"):
                raise RuntimeError(
                    f"provider '{raw.name}' does not support match statistics"
                )
            st.session_state.api_call_count += 1
            return raw.team_stat_records(team_name, last_n=last_n, stat=stat)

    return _Counted()


# ---------------------------------------------------------------------------
# Cached data / model helpers
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Loading results…")
def _load_results():
    return load_results()


@st.cache_resource(show_spinner="Fitting model…")
def _get_model(asof_str: str, years: float, kind: str):
    df = _load_results()
    train = training_data(df, asof=asof_str, years=years)
    return fit_cached(train, kind=kind)


@st.cache_data(show_spinner=False)
def _get_fixtures(date_from: str, days: int) -> pd.DataFrame:
    """Cached upcoming-fixtures window (underlying results CSV also cached)."""
    return fixtures(_load_results(), date_from=date_from, days=days)


_YEARS = 6.0
_asof_str = str(asof)
_model = _get_model(_asof_str, _YEARS, model_kind)

# ---------------------------------------------------------------------------
# All upcoming fixtures (used across tabs), keyed on asof
# ---------------------------------------------------------------------------
# Deliberately broad window so the pre-match multiselect covers the whole tournament.
_all_fixtures = _get_fixtures(_asof_str, 365 * 2)

# Label helper
def _match_label(row) -> str:
    return f"{row['home_team']} v {row['away_team']}"


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_fixtures, tab_prematch, tab_live, tab_knockout, tab_props = st.tabs(
    ["Fixtures", "Pre-match slate", "Live", "Knockout", "Props"]
)

# ── Tab 1: Fixtures ──────────────────────────────────────────────────────────
with tab_fixtures:
    st.subheader("Upcoming fixtures with model probabilities")

    days_ahead = st.slider(
        "Days ahead",
        min_value=1,
        max_value=14,
        value=7,
        key="fixtures_days",
    )

    fx_window = _get_fixtures(_asof_str, days_ahead)

    if fx_window.empty:
        st.info("No fixtures found in this window.")
    else:
        rows = slate.fixture_rows(_model, fx_window)
        df_rows = pd.DataFrame(rows)
        # Format probabilities as percentages for readability
        for col in ["p_home", "p_draw", "p_away", "p_over25", "p_btts"]:
            if col in df_rows.columns:
                df_rows[col] = df_rows[col].map(lambda x: f"{x:.1%}")
        st.dataframe(df_rows, use_container_width=True)

# ── Tab 2: Pre-match slate ────────────────────────────────────────────────────
with tab_prematch:
    st.subheader("Pre-match betting slate")

    # Build label list for multiselect
    fx_labels = [_match_label(row) for _, row in _all_fixtures.iterrows()]

    selected_matches = st.multiselect(
        "Select fixtures",
        options=fx_labels,
        default=[],
        placeholder="Pick one or more fixtures…",
    )

    st.divider()
    st.markdown("**Option A — fetch odds from provider**")

    fetch_btn = st.button("Fetch odds & build slate", disabled=(not selected_matches))

    if fetch_btn and selected_matches:
        provider = _make_counted_provider(provider_name, _key_env.get(provider_name))
        if provider is None:
            st.error("Provider unavailable (csv-upload selected, key missing, or init failed). Use the CSV upload below instead.")
        else:
            label_to_date = {
                _match_label(row): str(pd.Timestamp(row["date"]).date())
                for _, row in _all_fixtures.iterrows()
            }
            odds_rows_by_match: dict[str, list[dict]] = {}
            with st.spinner("Fetching odds…"):
                for label in selected_matches:
                    parts = label.split(" v ", 1)
                    if len(parts) == 2:
                        home, away = parts
                        quotes = provider.odds(home, away, date=label_to_date.get(label))
                        odds_rows_by_match[label] = [q.as_row() for q in quotes]
                        if not quotes:
                            st.warning(
                                f"{label}: provider returned no odds — team naming may "
                                "differ at the provider, or odds aren't posted yet."
                            )

            result = slate.prematch_slate(
                _model,
                _all_fixtures,
                odds_rows_by_match,
                bankroll=bankroll,
                kelly_fraction=kelly_fraction,
                min_ev=min_ev,
            )

            for w in result["warnings"]:
                st.warning(w)

            recs = result["recommendations"]
            st.metric("Total stake", f"£{result['total_stake']:.2f}")
            st.metric("Candidates evaluated", result["n_candidates"])

            if recs:
                st.dataframe(pd.DataFrame(recs), use_container_width=True)
            else:
                st.info("No +EV recommendations found with current settings.")

    st.divider()
    st.markdown("**Option B — upload odds CSV** (columns: home, away, market, outcome, line, odds[, bookmaker])")

    uploaded = st.file_uploader("Upload odds CSV", type=["csv"], key="prematch_csv")

    if uploaded is not None:
        try:
            odds_df = pd.read_csv(io.BytesIO(uploaded.read()))
            required = {"home", "away", "market", "outcome", "odds"}
            if not required.issubset(set(odds_df.columns)):
                st.error(f"CSV must have columns: {required}")
            else:
                # Group rows by match label, filter to selected (or use all)
                odds_rows_by_match_csv: dict[str, list[dict]] = {}
                for _, row in odds_df.iterrows():
                    lbl = f"{row['home']} v {row['away']}"
                    odds_rows_by_match_csv.setdefault(lbl, []).append(row.to_dict())

                # If user also selected matches, filter; otherwise use all in CSV
                if selected_matches:
                    odds_rows_by_match_csv = {
                        k: v for k, v in odds_rows_by_match_csv.items() if k in selected_matches
                    }

                if not odds_rows_by_match_csv:
                    st.warning("No matching fixtures found in uploaded CSV.")
                else:
                    result_csv = slate.prematch_slate(
                        _model,
                        _all_fixtures,
                        odds_rows_by_match_csv,
                        bankroll=bankroll,
                        kelly_fraction=kelly_fraction,
                        min_ev=min_ev,
                    )
                    for w in result_csv["warnings"]:
                        st.warning(w)
                    recs_csv = result_csv["recommendations"]
                    st.metric("Total stake (CSV)", f"£{result_csv['total_stake']:.2f}")
                    if recs_csv:
                        st.dataframe(pd.DataFrame(recs_csv), use_container_width=True)
                    else:
                        st.info("No +EV recommendations found with current settings.")
        except Exception as exc:
            st.error(f"Error reading CSV: {exc}")

# ── Tab 3: Live ───────────────────────────────────────────────────────────────
with tab_live:
    st.subheader("Live in-play — experimental")
    st.caption(
        "This module is experimental. In-play odds move fast; model repricing "
        "is approximate and no live ROI has been validated."
    )

    # Today's fixtures
    today_str = str(date.today())
    _today_fx = _get_fixtures(today_str, 1)
    _today_labels = [_match_label(row) for _, row in _today_fx.iterrows()]

    _live_label_options = _today_labels if _today_labels else ["(no fixtures today)"]
    selected_live = st.selectbox(
        "Select today's fixture",
        options=_live_label_options,
        key="live_fixture_select",
    )

    # Free-text overrides
    col_home, col_away = st.columns(2)
    with col_home:
        live_home_override = st.text_input("Override home team", value="", key="live_home")
    with col_away:
        live_away_override = st.text_input("Override away team", value="", key="live_away")

    # Determine effective home/away
    if live_home_override.strip() and live_away_override.strip():
        _live_home = live_home_override.strip()
        _live_away = live_away_override.strip()
    elif selected_live and " v " in selected_live:
        _live_home, _live_away = selected_live.split(" v ", 1)
    else:
        _live_home, _live_away = "", ""

    # Resolve neutral flag from today's fixtures (host home games are not neutral)
    _live_neutral = True
    if _live_home and _live_away and not _today_fx.empty:
        _fx_match = _today_fx[
            (_today_fx["home_team"] == _live_home)
            & (_today_fx["away_team"] == _live_away)
        ]
        if not _fx_match.empty:
            _live_neutral = bool(_fx_match.iloc[0]["neutral"])

    # Live feed needs an API provider with its key set; csv-upload has no
    # live feed, so it falls through to the manual input form.
    _env_var_live = _key_env.get(provider_name)
    _key_available = _env_var_live is not None and bool(os.environ.get(_env_var_live))

    if not _key_available:
        # Manual fallback: no live provider (key missing, or csv-upload selected)
        st.warning("No live API provider available — using manual input mode.")
        with st.form("live_manual_form"):
            col1, col2, col3 = st.columns(3)
            with col1:
                manual_minute = st.number_input("Minute", min_value=0, max_value=120, value=45)
            with col2:
                manual_score_home = st.number_input("Score (home)", min_value=0, value=0)
                manual_score_away = st.number_input("Score (away)", min_value=0, value=0)
            with col3:
                manual_red_home = st.number_input("Reds (home)", min_value=0, value=0)
                manual_red_away = st.number_input("Reds (away)", min_value=0, value=0)
            submitted = st.form_submit_button("Update live grid")

        if submitted and _live_home and _live_away:
            pre = _model.predict(_live_home, _live_away, neutral_venue=_live_neutral)
            live = live_grid(
                pre.home_goal_expectation,
                pre.away_goal_expectation,
                minute=float(manual_minute),
                score_home=int(manual_score_home),
                score_away=int(manual_score_away),
                red_home=int(manual_red_home),
                red_away=int(manual_red_away),
            )
            _, _, over25 = live.totals(2.5)

            st.markdown(f"**{_live_home} {manual_score_home}–{manual_score_away} {_live_away}** | Minute {manual_minute}")
            m1, m2, m3 = st.columns(3)
            m1.metric("P(home win)", f"{live.home_win:.1%}")
            m2.metric("P(draw)", f"{live.draw:.1%}")
            m3.metric("P(away win)", f"{live.away_win:.1%}")
            st.progress(int(live.home_win * 100), text=f"Home {live.home_win:.1%}")
            st.progress(int(live.draw * 100), text=f"Draw {live.draw:.1%}")
            st.progress(int(live.away_win * 100), text=f"Away {live.away_win:.1%}")
            st.progress(int(over25 * 100), text=f"Over 2.5 {over25:.1%}")

    else:
        # Provider-driven live fragment
        @st.fragment(run_every=st.session_state.refresh_interval)
        def _live_fragment():
            if not _live_home or not _live_away:
                st.info("Select or enter a fixture above.")
                return

            provider = _make_counted_provider(provider_name, _key_env.get(provider_name))
            if provider is None:
                st.error("Provider could not be initialised.")
                return

            snap = slate.live_snapshot(
                _model,
                provider,
                _live_home,
                _live_away,
                neutral=_live_neutral,
                bankroll=bankroll,
                kelly_fraction=kelly_fraction,
                min_ev=min_ev,
            )

            if snap.get("status") == "not_live":
                st.info(f"{_live_home} v {_live_away} is not currently live.")
                return

            for w in snap.get("warnings", []):
                st.warning(w)

            # Score / minute / reds metrics row
            score_h, score_a = snap["score"]
            red_h, red_a = snap["reds"]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Score", f"{score_h}–{score_a}")
            c2.metric("Minute", f"{snap['minute']:.0f}'")
            c3.metric("Reds (home)", red_h)
            c4.metric("Reds (away)", red_a)

            # 1X2 + O2.5 probability bars
            st.markdown("**Win probabilities**")
            st.progress(int(snap["p_home"] * 100), text=f"Home {snap['p_home']:.1%}")
            st.progress(int(snap["p_draw"] * 100), text=f"Draw {snap['p_draw']:.1%}")
            st.progress(int(snap["p_away"] * 100), text=f"Away {snap['p_away']:.1%}")
            st.progress(int(snap["p_over25"] * 100), text=f"Over 2.5 {snap['p_over25']:.1%}")

            # Recommendations
            recs = snap.get("recommendations", [])
            if recs:
                st.markdown("**Recommendations**")
                st.dataframe(pd.DataFrame(recs), use_container_width=True)
            else:
                st.info("No +EV live recommendations at current settings.")

            # Fetched-at caption
            fetched_dt = datetime.fromtimestamp(snap["fetched_at"]).strftime("%H:%M:%S")
            st.caption(f"Fetched at {fetched_dt}")

        _live_fragment()

# ── Tab 4: Knockout ───────────────────────────────────────────────────────────
with tab_knockout:
    st.subheader("Knockout round calculator")

    col_a, col_b = st.columns(2)
    with col_a:
        ko_home = st.text_input("Home team", value="Argentina", key="ko_home")
    with col_b:
        ko_away = st.text_input("Away team", value="France", key="ko_away")

    ko_neutral = st.checkbox("Neutral venue", value=True, key="ko_neutral")

    ko_et_factor = st.slider(
        "Extra-time intensity factor",
        min_value=0.8,
        max_value=1.2,
        value=1.0,
        step=0.05,
        help="Scale pre-match rates for extra time (1.0 = same intensity).",
    )

    ko_pens_home = st.slider(
        "Home penalty shootout win probability",
        min_value=0.3,
        max_value=0.7,
        value=0.5,
        step=0.05,
        help="Prior probability home side wins the penalty shootout.",
    )

    if ko_home.strip() and ko_away.strip():
        try:
            ko_grid = _model.predict(ko_home.strip(), ko_away.strip(), neutral_venue=ko_neutral)
            adv = knockout.advance_probabilities(
                ko_grid,
                et_factor=ko_et_factor,
                pens_home=ko_pens_home,
            )
            fair_home, fair_away = adv.fair_odds()

            st.markdown(f"### {ko_home.strip()} vs {ko_away.strip()}")

            c1, c2 = st.columns(2)
            c1.metric(f"{ko_home.strip()} advance", f"{adv.advance_home:.1%}", help=f"Fair odds: {fair_home:.2f}")
            c2.metric(f"{ko_away.strip()} advance", f"{adv.advance_away:.1%}", help=f"Fair odds: {fair_away:.2f}")

            with st.expander("Full breakdown"):
                st.table(
                    pd.DataFrame(
                        {
                            "Phase": [
                                "Win 90'", "Draw 90'", "Lose 90'",
                                "Win ET (cond.)", "Draw ET (cond.)", "Lose ET (cond.)",
                                "Pens home win",
                            ],
                            "Probability": [
                                f"{adv.win_90:.1%}", f"{adv.draw_90:.1%}", f"{adv.lose_90:.1%}",
                                f"{adv.win_et:.1%}", f"{adv.draw_et:.1%}", f"{adv.lose_et:.1%}",
                                f"{adv.pens_home:.1%}",
                            ],
                        }
                    )
                )

            st.markdown("**Fair odds**")
            fc1, fc2 = st.columns(2)
            fc1.metric(f"{ko_home.strip()} to qualify", f"{fair_home:.2f}")
            fc2.metric(f"{ko_away.strip()} to qualify", f"{fair_away:.2f}")

            st.markdown("**Optional: to-qualify market odds → EV**")
            oc1, oc2 = st.columns(2)
            with oc1:
                market_odds_home = st.number_input(
                    f"{ko_home.strip()} market odds", min_value=1.01, value=fair_home, step=0.05, key="ko_mkt_home"
                )
                ev_home = adv.advance_home * market_odds_home - 1.0
                st.caption(f"EV: {ev_home:+.3f} ({'positive' if ev_home > 0 else 'negative'})")
            with oc2:
                market_odds_away = st.number_input(
                    f"{ko_away.strip()} market odds", min_value=1.01, value=fair_away, step=0.05, key="ko_mkt_away"
                )
                ev_away = adv.advance_away * market_odds_away - 1.0
                st.caption(f"EV: {ev_away:+.3f} ({'positive' if ev_away > 0 else 'negative'})")

        except Exception as exc:
            st.error(f"Could not compute knockout probabilities: {exc}")
    else:
        st.info("Enter both team names to compute knockout probabilities.")

# ── Tab 5: Props ──────────────────────────────────────────────────────────────
with tab_props:
    st.subheader("Prop markets — experimental")
    st.caption(
        "Prop markets carry **higher bookmaker margins and lower limits** than "
        "main markets, and our research base contains no verified evidence of "
        "exploitable inefficiency in them. Treat everything below as fair prices "
        "under stated assumptions, not proven edges. "
        "See [docs/props.md](docs/props.md)."
    )

    _props_labels = [_match_label(row) for _, row in _all_fixtures.iterrows()]

    if not _props_labels:
        st.info("No upcoming fixtures found — adjust the as-of date in the sidebar.")
    else:
        props_label = st.selectbox(
            "Fixture", options=_props_labels, key="props_fixture"
        )
        _props_home, _props_away = props_label.split(" v ", 1)

        # Neutral-aware team lambdas from the cached match model (same
        # pattern as the Live tab: host home games are not neutral).
        _props_fx = _all_fixtures[
            (_all_fixtures["home_team"] == _props_home)
            & (_all_fixtures["away_team"] == _props_away)
        ]
        _props_neutral = (
            bool(_props_fx.iloc[0]["neutral"]) if not _props_fx.empty else True
        )

        try:
            _props_grid = _model.predict(
                _props_home, _props_away, neutral_venue=_props_neutral
            )
            _team_lambdas = {
                _props_home: _props_grid.home_goal_expectation,
                _props_away: _props_grid.away_goal_expectation,
            }
        except Exception as exc:
            _team_lambdas = None
            st.error(f"Could not price this fixture with the model: {exc}")

        # ── Anytime scorer ─────────────────────────────────────────────────
        st.markdown("### Anytime scorer")
        st.caption(
            "P(score) = 1 − exp(−λ_team × share). Shares come from season goal "
            "counts (Laplace-smoothed) — the **weakest input** in this model: "
            "international scoring data is thin and lineups are not modelled."
        )

        # Free API-Football plans only serve seasons 2022-2024 (verified live).
        props_season = st.selectbox(
            "Season (player stats)",
            options=[2023, 2024, 2025],
            index=1,
            key="props_season",
            help="2025 requires a paid API-Football plan; free plans serve 2022-2024.",
        )

        if st.button(
            "Fetch player stats (costs ~2-6 API requests per team, cached 24h)",
            key="props_scorer_btn",
            disabled=_team_lambdas is None,
        ):
            provider = _make_counted_provider(provider_name, _key_env.get(provider_name))
            if provider is None:
                st.error(
                    "Provider unavailable — select api-football in the sidebar "
                    "and set its API key."
                )
            else:
                try:
                    with st.spinner("Fetching player stats…"):
                        _stats_by_team = {
                            team: provider.player_goal_stats(team, props_season)
                            for team in (_props_home, _props_away)
                        }
                    st.session_state["props_scorer_data"] = {
                        "fixture": props_label,
                        "season": props_season,
                        "stats": _stats_by_team,
                    }
                except RuntimeError as exc:
                    st.error(f"Provider error: {exc}")

        _scorer_data = st.session_state.get("props_scorer_data")
        if (
            _team_lambdas is not None
            and _scorer_data
            and _scorer_data["fixture"] == props_label
        ):
            if _scorer_data["season"] != props_season:
                st.info("Season changed — fetch player stats again to update.")
            for team in (_props_home, _props_away):
                players = _scorer_data["stats"].get(team, [])
                st.markdown(f"**{team}** — model λ = {_team_lambdas[team]:.2f}")
                if not players:
                    st.info(
                        f"No player stats returned for {team} — team naming may "
                        "differ at the provider, or no season data exists."
                    )
                    continue

                _apps = {p["player"]: p["appearances"] for p in players}
                _n_thin = sum(1 for a in _apps.values() if a < 5)
                if _n_thin:
                    st.warning(
                        f"{_n_thin} player(s) have fewer than 5 appearances — "
                        "their shares are mostly smoothing, not signal."
                    )

                _table = props.scorer_table(
                    _team_lambdas[team],
                    {p["player"]: p["goals"] for p in players},
                )
                _df = pd.DataFrame(_table)
                _df["appearances"] = _df["player"].map(_apps)
                _df["odds"] = 0.0
                edited = st.data_editor(
                    _df,
                    key=f"props_scorer_editor_{team}",
                    hide_index=True,
                    use_container_width=True,
                    disabled=[c for c in _df.columns if c != "odds"],
                    column_config={
                        "odds": st.column_config.NumberColumn(
                            "odds", min_value=0.0, step=0.05,
                            help="Enter bookmaker anytime-scorer odds (decimal).",
                        ),
                    },
                )

                _priced = edited[edited["odds"] > 1.0]
                if not _priced.empty:
                    _out = _priced[["player", "p_score", "fair_odds", "odds"]].copy()
                    _out["ev"] = [
                        props.ev(p, o)
                        for p, o in zip(_out["p_score"], _out["odds"])
                    ]
                    _out["stake"] = [
                        kelly_criterion(o, p, fraction=kelly_fraction).stake * bankroll
                        for p, o in zip(_out["p_score"], _out["odds"])
                    ]
                    st.markdown("Priced selections (EV and fractional-Kelly stake):")
                    st.dataframe(_out, use_container_width=True, hide_index=True)

        # ── Corners / Shots on target ──────────────────────────────────────
        st.divider()
        st.markdown("### Corners / Shots on target")
        st.caption(
            "Per-team for/against rates from recent finished fixtures, shrunk "
            "toward the global mean (weight n/(n+k)); totals from an independent "
            "Poisson grid. Quality depends entirely on how much fixture data has "
            "been collected."
        )

        props_stat = st.selectbox(
            "Stat",
            options=["corners", "shots_on_goal"],
            format_func=lambda s: {"corners": "Corners", "shots_on_goal": "Shots on target"}[s],
            key="props_stat",
        )
        props_last_n = st.slider(
            "Finished fixtures per team", min_value=5, max_value=30, value=15,
            key="props_last_n",
        )

        if st.button(
            f"Collect team stats (≈2×{props_last_n} API requests on first run, cached after)",
            key="props_count_btn",
        ):
            provider = _make_counted_provider(provider_name, _key_env.get(provider_name))
            if provider is None:
                st.error(
                    "Provider unavailable — select api-football in the sidebar "
                    "and set its API key."
                )
            else:
                try:
                    with st.spinner("Collecting fixture statistics…"):
                        _records = []
                        for team in (_props_home, _props_away):
                            _records.extend(
                                provider.team_stat_records(
                                    team, last_n=props_last_n, stat=props_stat
                                )
                            )
                    st.session_state["props_count_data"] = {
                        "fixture": props_label,
                        "stat": props_stat,
                        "records": _records,
                    }
                except RuntimeError as exc:
                    st.error(f"Provider error: {exc}")

        _count_data = st.session_state.get("props_count_data")
        if (
            _count_data
            and _count_data["fixture"] == props_label
            and _count_data["stat"] == props_stat
        ):
            _records = _count_data["records"]
            if not _records:
                st.info(
                    "No statistics records collected — team naming may differ at "
                    "the provider, or no finished fixtures had statistics."
                )
            else:
                _rates = props.fit_team_rates(_records)
                _n_home = _rates.counts.get(_props_home, 0)
                _n_away = _rates.counts.get(_props_away, 0)

                sc1, sc2 = st.columns(2)
                sc1.metric(f"{_props_home} samples", _n_home)
                sc2.metric(f"{_props_away} samples", _n_away)
                if _n_home < 8 or _n_away < 8:
                    st.warning(
                        "Thin data: fewer than 8 sampled fixtures for at least one "
                        "team — rates are shrunk hard toward the global mean "
                        "(0 samples means the team name did not match any record "
                        "and the global mean is used outright)."
                    )

                _lam_h, _lam_a = props.predict_lambdas(
                    _rates, _props_home, _props_away
                )
                st.markdown(
                    f"Expected {props_stat.replace('_', ' ')}: "
                    f"**{_props_home} {_lam_h:.2f}**, **{_props_away} {_lam_a:.2f}** "
                    f"(total {_lam_h + _lam_a:.2f})"
                )

                _cgrid = props.count_grid(_lam_h, _lam_a)
                _default_line = 9.5 if props_stat == "corners" else 8.5
                props_line = st.number_input(
                    "Total line",
                    min_value=0.5,
                    value=_default_line,
                    step=0.5,
                    key=f"props_line_{props_stat}",
                )
                _ou = props.over_under(_cgrid, props_line)

                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "side": "Over",
                                "probability": _ou["over"],
                                "fair_odds": _ou["fair_over"],
                            },
                            {
                                "side": "Under",
                                "probability": _ou["under"],
                                "fair_odds": _ou["fair_under"],
                            },
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
                if _ou["push"] > 0:
                    st.caption(f"Push probability (stake refund): {_ou['push']:.1%}")

                oc1, oc2 = st.columns(2)
                with oc1:
                    _odds_over = st.number_input(
                        "Over odds", min_value=0.0, value=0.0, step=0.05,
                        key=f"props_over_odds_{props_stat}",
                    )
                    if _odds_over > 1.0:
                        _ev_over = props.ev(_ou["over"], _odds_over, push=_ou["push"])
                        st.caption(f"EV: {_ev_over:+.3f}")
                with oc2:
                    _odds_under = st.number_input(
                        "Under odds", min_value=0.0, value=0.0, step=0.05,
                        key=f"props_under_odds_{props_stat}",
                    )
                    if _odds_under > 1.0:
                        _ev_under = props.ev(_ou["under"], _odds_under, push=_ou["push"])
                        st.caption(f"EV: {_ev_under:+.3f}")
