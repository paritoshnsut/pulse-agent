"""Moments calendar — the proactive layer. Pure date math + idempotent insert."""

from datetime import date

import pytest

import moments
from moments import resolve, upcoming
from pipeline import memory
from watch.moments import MomentsWatcher


# ----------------------------------------------------------------- date rules
def test_fixed_rule():
    assert resolve(("fixed", 4, 22), 2026) == date(2026, 4, 22)


def test_nth_weekday_rule():
    # Mother's Day 2026 = 2nd Sunday of May = May 10
    assert resolve(("nth_weekday", 5, 6, 2), 2026) == date(2026, 5, 10)
    # Thanksgiving 2026 = 4th Thursday of Nov = Nov 26
    assert resolve(("nth_weekday", 11, 3, 4), 2026) == date(2026, 11, 26)
    # a 5th occurrence that doesn't exist -> None, never a wrong month
    assert resolve(("nth_weekday", 2, 0, 5), 2026) is None


def test_last_weekday_rule():
    # last Saturday of March 2026 = Mar 28
    assert resolve(("last_weekday", 3, 5), 2026) == date(2026, 3, 28)


def test_offset_rule():
    # Black Friday 2026 = Thanksgiving + 1 = Nov 27
    assert resolve(("offset", ("nth_weekday", 11, 3, 4), 1), 2026) == date(2026, 11, 27)


def test_lookup_rule_missing_year_is_none_not_guessed():
    rule = ("lookup", {2026: (11, 8)})
    assert resolve(rule, 2026) == date(2026, 11, 8)
    assert resolve(rule, 2031) is None


def test_unknown_rule_raises():
    with pytest.raises(ValueError):
        resolve(("vibes", 1, 1), 2026)


# ------------------------------------------------------------------- calendar
def test_calendar_entries_well_formed():
    assert len(moments.MOMENTS) > 60
    slugs = [m["slug"] for m in moments.MOMENTS]
    assert len(slugs) == len(set(slugs))            # unique slugs
    for m in moments.MOMENTS:
        assert m["kind"] and m["name"] and m["blurb"]
        assert m["lead_days"] > 0
        assert m["region"] in ("india", "us", None)
        # every rule resolves for SOME year without raising
        resolve(m["rule"], 2026)


def test_upcoming_window_and_ordering():
    # 10 days before Diwali 2026 (Nov 8): inside its 28-day lead window
    found = upcoming(date(2026, 10, 29))
    slugs = {m["slug"] for m in found}
    assert "diwali" in slugs
    assert all(0 <= m["days_out"] <= m["lead_days"] for m in found)
    assert [m["days_out"] for m in found] == sorted(m["days_out"] for m in found)
    # 60 days out: not yet
    assert "diwali" not in {m["slug"] for m in upcoming(date(2026, 9, 1))}


def test_upcoming_crosses_year_boundary():
    # late December sees New Year's Day (next year)
    found = upcoming(date(2026, 12, 28))
    assert "new-years-day" in {m["slug"] for m in found}


# -------------------------------------------------------------------- watcher
def test_watcher_inserts_once_and_dedups(temp_db):
    w = MomentsWatcher(db_path=temp_db)
    day = date(2026, 10, 29)
    first = w.run(today=day)
    assert first["new"] > 0 and first["duplicate"] == 0
    again = w.run(today=day)                        # same day re-run: all dups
    assert again["new"] == 0 and again["duplicate"] == first["new"]


def test_moment_article_reaches_vertical_scoped_account(temp_db):
    """A universal (NULL-vertical) moment must reach scoped brand accounts —
    the NULL-vertical visibility fix."""
    aid = memory.upsert_account(handle="dtc", kind="brand",
                                verticals=["lifestyle"], regions=["india"],
                                db_path=temp_db)
    acct = memory.get_account(aid, db_path=temp_db)
    MomentsWatcher(db_path=temp_db).run(today=date(2026, 10, 29))
    queue = memory.get_unscored_for_account(acct, db_path=temp_db, limit=100)
    titles = " | ".join(a["title"] for a in queue)
    assert "Diwali" in titles                       # india + NULL vertical
    # a US-only moment must NOT reach an india-scoped account
    assert "Halloween" not in titles
