"""Command-line interface for WC2026 betting recommendations.

Commands:
  update                          download/refresh results data
  fixtures [--days N]             upcoming WC fixtures with model 1X2
  recs --odds-file F [...]        pre-match recommendations from an odds CSV
  live --home H --away A --minute M --score 1-0 [--reds 0-0] --odds-file F

Odds CSV columns: home,away,market,outcome,line,odds
  markets: 1x2 (home/draw/away), ou (over/under, line), ah (home/away, line),
           btts (yes/no), dnb (home/away), dc (1x/x2/12), exact ("2-1")
"""

from __future__ import annotations

import argparse

import pandas as pd

from . import data as data_mod
from .cache import fit_cached
from .edge import build_candidates
from .knockout import advance_probabilities
from .live import live_grid_from_model
from .model import predict_fixture
from .recommend import recommend


def _fit(args):
    df = data_mod.load_results()
    train = data_mod.training_data(df, asof=args.asof, years=args.years)
    print(f"training on {len(train.goals_home)} matches (asof {args.asof})")
    return df, fit_cached(train, kind=args.model, use_cache=not args.no_cache)


def _match_label(home: str, away: str) -> str:
    return f"{home} v {away}"


def cmd_update(args) -> None:
    df = data_mod.load_results(refresh=True)
    played = df.dropna(subset=["home_score"])
    print(f"results: {len(df)} rows, latest played {played['date'].max().date()}")


def cmd_fixtures(args) -> None:
    df, model = _fit(args)
    fx = data_mod.fixtures(df, date_from=args.asof, days=args.days)
    for _, r in fx.iterrows():
        g = predict_fixture(model, r["home_team"], r["away_team"], r["neutral"])
        print(
            f"{r['date'].date()} {_match_label(r['home_team'], r['away_team']):<45}"
            f" 1X2 {g.home_win:.3f}/{g.draw:.3f}/{g.away_win:.3f}"
            f"  O2.5 {g.totals(2.5)[2]:.3f}  BTTS {g.btts_yes:.3f}"
        )


def _load_odds(path: str) -> pd.DataFrame:
    odds = pd.read_csv(path)
    required = {"home", "away", "market", "outcome", "odds"}
    missing = required - set(odds.columns)
    if missing:
        raise SystemExit(f"odds file missing columns: {sorted(missing)}")
    return odds


def cmd_recs(args) -> None:
    df, model = _fit(args)
    odds = _load_odds(args.odds_file)
    fx = data_mod.fixtures(df, date_from=args.asof, days=args.days)
    neutral_map = {
        _match_label(r["home_team"], r["away_team"]): r["neutral"] for _, r in fx.iterrows()
    }

    candidates = []
    for (home, away), rows in odds.groupby(["home", "away"]):
        match = _match_label(home, away)
        neutral = neutral_map.get(match)
        if neutral is None:
            print(
                f"warning: '{match}' not in fixture window; assuming neutral venue. "
                "Check team spelling matches the results dataset."
            )
            neutral = True
        grid = predict_fixture(model, home, away, neutral)
        candidates += build_candidates(grid, match, rows.to_dict("records"))

    recs = recommend(
        candidates,
        bankroll=args.bankroll,
        kelly_fraction=args.kelly,
        min_ev=args.min_ev,
    )
    if not recs:
        print("no +EV recommendations at current thresholds")
        return
    print(f"\n{len(recs)} recommendations (bankroll {args.bankroll:.0f}):")
    for r in recs:
        print("  " + r.describe())
    print(f"\ntotal staked: {sum(r.stake for r in recs):.2f}")


def cmd_live(args) -> None:
    _df, model = _fit(args)
    provider = None
    if args.provider != "manual":
        from .providers import make_provider

        provider = make_provider(args.provider)
        state = provider.live_state(args.home, args.away)
        if state is None:
            raise SystemExit(f"{args.provider}: match not found / not live")
        score_h, score_a = state.score_home, state.score_away
        red_h, red_a = state.red_home, state.red_away
        args.minute = state.minute
        print(f"[{args.provider}] {state.minute:.0f}' {score_h}-{score_a} reds {red_h}-{red_a}")
    else:
        if args.minute is None or not args.score:
            raise SystemExit("--minute and --score required with --provider manual")
        score_h, score_a = (int(x) for x in args.score.split("-"))
        red_h, red_a = (int(x) for x in args.reds.split("-"))
    grid = live_grid_from_model(
        model,
        args.home,
        args.away,
        neutral=not args.not_neutral,
        minute=args.minute,
        score_home=score_h,
        score_away=score_a,
        red_home=red_h,
        red_away=red_a,
    )
    match = _match_label(args.home, args.away)
    print(
        f"{match} {score_h}-{score_a} @ {args.minute}' "
        f"-> 1X2 {grid.home_win:.3f}/{grid.draw:.3f}/{grid.away_win:.3f}"
    )
    odds_rows = []
    if args.odds_file:
        odds = _load_odds(args.odds_file)
        odds_rows = odds[(odds["home"] == args.home) & (odds["away"] == args.away)].to_dict(
            "records"
        )
    elif provider is not None:
        # Reuse the instance that fetched the state — a fresh fixture search
        # seconds later can land on a different game state.
        odds_rows = [q.as_row() for q in provider.odds(args.home, args.away)]
    if odds_rows:
        candidates = build_candidates(grid, match, odds_rows)
        recs = recommend(
            candidates, bankroll=args.bankroll, kelly_fraction=args.kelly, min_ev=args.min_ev
        )
        for r in recs:
            print("  " + r.describe())


def cmd_benchmark(args) -> None:
    from .benchmark import run_benchmark
    from .providers import make_provider

    provider = make_provider(args.provider)
    print(f"benchmarking {args.provider}: {args.polls} polls @ {args.interval}s ...")
    result = run_benchmark(
        provider,
        args.home,
        args.away,
        polls=args.polls,
        interval=args.interval,
        include_odds=args.odds,
    )
    print(result.summary())


def cmd_advance(args) -> None:
    _df, model = _fit(args)
    grid = predict_fixture(model, args.home, args.away, not args.not_neutral)
    adv = advance_probabilities(grid, et_factor=args.et_factor, pens_home=args.pens_home)
    fair_h, fair_a = adv.fair_odds()
    print(
        f"{_match_label(args.home, args.away)} (knockout)\n"
        f"  90': {adv.win_90:.3f}/{adv.draw_90:.3f}/{adv.lose_90:.3f}"
        f"  ET (if drawn): {adv.win_et:.3f}/{adv.draw_et:.3f}/{adv.lose_et:.3f}"
        f"  pens(home): {adv.pens_home:.2f}\n"
        f"  advance: {args.home} {adv.advance_home:.3f} (fair {fair_h:.2f})"
        f" | {args.away} {adv.advance_away:.3f} (fair {fair_a:.2f})"
    )
    if args.odds:
        odds_h, odds_a = (float(x) for x in args.odds.split(","))
        ev_h = adv.advance_home * odds_h - 1
        ev_a = adv.advance_away * odds_a - 1
        print(f"  to-qualify EV: {args.home} @ {odds_h} -> {ev_h:+.3f} | {args.away} @ {odds_a} -> {ev_a:+.3f}")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="wc26", description=__doc__)
    p.add_argument("--asof", default=str(pd.Timestamp.today().date()))
    p.add_argument("--years", type=float, default=6.0)
    p.add_argument("--model", default="dixon_coles")
    p.add_argument("--no-cache", action="store_true", help="force model refit")
    p.add_argument("--bankroll", type=float, default=1000.0)
    p.add_argument("--kelly", type=float, default=0.25)
    p.add_argument("--min-ev", type=float, default=0.02)
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("update")

    fx = sub.add_parser("fixtures")
    fx.add_argument("--days", type=int, default=7)

    recs = sub.add_parser("recs")
    recs.add_argument("--odds-file", required=True)
    recs.add_argument("--days", type=int, default=7)

    live = sub.add_parser("live")
    live.add_argument("--home", required=True)
    live.add_argument("--away", required=True)
    live.add_argument("--provider", default="manual", help="manual | api-football | sportmonks")
    live.add_argument("--minute", type=float, help="required with --provider manual")
    live.add_argument("--score", help="e.g. 1-0 (required with --provider manual)")
    live.add_argument("--reds", default="0-0", help="red cards e.g. 0-1")
    live.add_argument("--not-neutral", action="store_true")
    live.add_argument("--odds-file")

    bench = sub.add_parser("benchmark", help="measure real provider latency with your API key")
    bench.add_argument("--provider", required=True, help="api-football | sportmonks")
    bench.add_argument("--home", required=True)
    bench.add_argument("--away", required=True)
    bench.add_argument("--polls", type=int, default=20)
    bench.add_argument("--interval", type=float, default=5.0)
    bench.add_argument("--odds", action="store_true", help="also poll odds endpoint")

    adv = sub.add_parser("advance", help="knockout tie: P(advance) incl. ET + pens")
    adv.add_argument("--home", required=True)
    adv.add_argument("--away", required=True)
    adv.add_argument("--not-neutral", action="store_true")
    adv.add_argument("--et-factor", type=float, default=1.0)
    adv.add_argument("--pens-home", type=float, default=0.5)
    adv.add_argument("--odds", help="to-qualify decimal odds 'home,away' e.g. 1.8,2.1")

    args = p.parse_args(argv)
    {
        "update": cmd_update,
        "fixtures": cmd_fixtures,
        "recs": cmd_recs,
        "live": cmd_live,
        "advance": cmd_advance,
        "benchmark": cmd_benchmark,
    }[args.command](args)


if __name__ == "__main__":
    main()
