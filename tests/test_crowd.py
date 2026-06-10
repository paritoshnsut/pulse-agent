"""Genome B (crowd wisdom) tests — injected fetcher + stub client, no keys."""

import json

import pytest

from conftest import StubClient
from pipeline import memory
from style import crowd


JUDGED = {
    "hook_patterns": ["open with a stark number"],
    "structural_patterns": ["one-line paragraphs", "twist in the last line"],
    "emotional_registers": ["outrage", "curiosity"],
    "winning_topics": ["fuel prices", "rbi policy"],
}

TWEETS = [
    {"text": "Petrol just crossed ₹110. Nobody in the press conference asked why.", "likeCount": 5000},
    {"text": "3 numbers the budget speech skipped. A thread.", "likeCount": 2400},
    {"text": "RBI says inflation is 'transitory'. Your grocery bill disagrees.", "likeCount": 1200},
]


def test_build_query_quotes_multiword_keywords():
    q = crowd.CrowdWisdomScraper.build_query(["rbi", "fuel prices"], 1000)
    assert q == '(rbi OR "fuel prices") min_faves:1000 -filter:replies'


def test_fetch_top_posts_uses_injected_fetcher_and_sorts():
    captured = {}

    def fetcher(query, limit):
        captured["query"], captured["limit"] = query, limit
        return list(reversed(TWEETS))  # worst-first; fetch must re-sort

    s = crowd.CrowdWisdomScraper(client=StubClient("{}"), fetcher=fetcher)
    posts = s.fetch_top_posts(["rbi"], min_likes=1000, limit=10)
    assert "min_faves:1000" in captured["query"]
    assert captured["limit"] == 10
    assert posts[0]["likeCount"] == 5000  # highest engagement first


def test_fetch_top_posts_no_key_no_fetcher_returns_empty():
    s = crowd.CrowdWisdomScraper(client=StubClient("{}"))
    assert s.fetch_top_posts(["rbi"]) == []  # no TWITTER_API_IO_KEY in tests


def test_extract_merges_measured_and_judged():
    s = crowd.CrowdWisdomScraper(client=StubClient(json.dumps(JUDGED)))
    gb = s.extract([t["text"] for t in TWEETS])
    assert gb["hook_patterns"] == JUDGED["hook_patterns"]          # judged
    assert gb["emotional_registers"] == ["outrage", "curiosity"]
    assert gb["avg_post_length"].endswith("chars")                 # measured
    assert gb["sample_count"] == 3


def test_extract_rejects_empty():
    with pytest.raises(ValueError):
        crowd.CrowdWisdomScraper(client=StubClient("{}")).extract(["", " "])


def test_refresh_requires_genome_a(temp_db):
    acct_id = memory.upsert_account(handle="me", topics=["rbi"], db_path=temp_db)
    s = crowd.CrowdWisdomScraper(client=StubClient("{}"), fetcher=lambda q, n: TWEETS)
    assert s.refresh(memory.get_account(acct_id, db_path=temp_db), db_path=temp_db) is None


def test_refresh_saves_new_version_with_genome_a_carried(temp_db):
    acct_id = memory.upsert_account(handle="me", topics=["rbi"], db_path=temp_db)
    memory.save_style_dna(acct_id, genome_a={"tone": "combative"}, blend=0.4,
                          sample_count=50, db_path=temp_db)
    s = crowd.CrowdWisdomScraper(client=StubClient(json.dumps(JUDGED)),
                                 fetcher=lambda q, n: TWEETS)
    gb = s.refresh(memory.get_account(acct_id, db_path=temp_db), db_path=temp_db)
    assert gb is not None
    saved = memory.get_style_dna(acct_id, db_path=temp_db)
    assert saved["version"] == 2
    assert saved["genome_a"] == {"tone": "combative"}     # carried forward
    assert saved["genome_b"]["hook_patterns"] == JUDGED["hook_patterns"]
    assert saved["blend"] == 0.4


def test_effective_genome_pure_a_without_b():
    a = {"tone": "combative", "things_to_avoid": ["formal language"]}
    assert crowd.effective_genome(a, None, 0.4) == a
    assert crowd.effective_genome(a, {"hook_patterns": ["x"]}, 0.0) == a


def test_effective_genome_folds_crowd_block_keeps_voice():
    a = {"tone": "combative", "sarcasm_level": "high"}
    b = {"hook_patterns": ["h1", "h2", "h3", "h4", "h5", "h6"],
         "structural_patterns": ["s1"], "emotional_registers": ["outrage"]}
    g = crowd.effective_genome(a, b, 0.4)
    assert g["tone"] == "combative" and g["sarcasm_level"] == "high"  # A untouched
    assert g["crowd_patterns"]["weight"] == 0.4
    assert g["crowd_patterns"]["hooks"] == ["h1", "h2", "h3", "h4", "h5"]  # capped at 5
    assert g["crowd_patterns"]["structures"] == ["s1"]


def test_generator_renders_crowd_patterns_and_emphasize():
    from pipeline.generator import _style_rules

    genome = {
        "tone": "combative",
        "learned_preferences": {"emphasize": ["lead with a number"]},
        "crowd_patterns": {"weight": 0.4, "hooks": ["stark number"],
                           "structures": ["one-liners"],
                           "emotional_registers": ["outrage"]},
    }
    rules = _style_rules(genome)
    assert "do MORE of it" in rules and "lead with a number" in rules
    assert "STRUCTURE only" in rules and "stark number" in rules
    # without the learned blocks, neither line appears
    assert "STRUCTURE only" not in _style_rules({"tone": "combative"})
