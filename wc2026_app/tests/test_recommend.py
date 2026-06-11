from wc26.edge import Candidate
from wc26.recommend import recommend, select_diverse


def _cand(match="A v B", market="1x2", outcome="home", odds=2.5, p_win=0.5, **kw):
    return Candidate(match=match, market=market, outcome=outcome, odds=odds, p_win=p_win, **kw)


def test_negative_ev_filtered_out():
    cands = [_cand(odds=1.8, p_win=0.5)]  # ev = -0.1
    assert select_diverse(cands) == []


def test_never_both_sides_of_same_market():
    cands = [
        _cand(outcome="home", odds=2.5, p_win=0.5),   # ev +0.25
        _cand(outcome="away", odds=4.0, p_win=0.28),  # ev +0.12
    ]
    sel = select_diverse(cands)
    assert len(sel) == 1
    assert sel[0].outcome == "home"  # higher EV wins


def test_max_per_match_cap():
    cands = [
        _cand(market="1x2", outcome="home", odds=2.5, p_win=0.5),
        _cand(market="ou", outcome="over", line=2.5, odds=2.1, p_win=0.55),
        _cand(market="btts", outcome="yes", odds=2.2, p_win=0.55),
    ]
    sel = select_diverse(cands, max_per_match=2)
    assert len(sel) == 2


def test_tier_cap_limits_high_variance():
    cands = [
        _cand(market="exact", outcome="2-1", odds=12.0, p_win=0.12, match=f"m{i}")
        for i in range(5)
    ]
    sel = select_diverse(cands, max_per_tier={"high": 2})
    assert len(sel) == 2


def test_recommend_stakes_positive_and_bounded():
    cands = [
        _cand(match="A v B", odds=2.5, p_win=0.5),
        _cand(match="C v D", market="ah", outcome="home", line=-0.5, odds=2.0, p_win=0.55),
    ]
    recs = recommend(cands, bankroll=1000, kelly_fraction=0.25)
    assert recs
    total = sum(r.stake for r in recs)
    assert 0 < total <= 150  # max_total_stake default 0.15
    assert all(r.stake > 0 for r in recs)
