"""Source catalog tests."""

import pytest

import sources
from sources import feeds_for


def test_all_four_verticals_present():
    assert set(sources.VERTICALS) == {"politics", "finance", "sports", "entertainment"}


def test_feeds_for_returns_well_formed_specs():
    feeds = feeds_for()
    assert len(feeds) > 30  # extensive
    for f in feeds:
        assert set(f.keys()) == {"url", "name", "vertical", "region"}
        assert f["url"].startswith("http")
        assert f["vertical"] in sources.VERTICALS
        assert f["region"] in sources.REGIONS


def test_feeds_for_filters_by_vertical_and_region():
    feeds = feeds_for(["politics"], ["india"])
    assert feeds, "expected some india politics feeds"
    assert all(f["vertical"] == "politics" and f["region"] == "india" for f in feeds)


def test_feeds_for_region_union_adds_up():
    india = feeds_for(["politics"], ["india"])
    us = feeds_for(["politics"], ["us"])
    both = feeds_for(["politics"], ["india", "us"])
    assert len(both) == len(india) + len(us)


def test_feeds_for_multiple_verticals():
    feeds = feeds_for(["finance", "sports"])
    verts = {f["vertical"] for f in feeds}
    assert verts == {"finance", "sports"}


def test_no_duplicate_urls_globally():
    urls = [f["url"] for f in feeds_for()]
    assert len(urls) == len(set(urls))


def test_unknown_vertical_raises():
    with pytest.raises(ValueError):
        feeds_for(["astrology"])


def test_us_and_india_both_covered_for_politics():
    regions = {f["region"] for f in feeds_for(["politics"])}
    assert {"india", "us"}.issubset(regions)
