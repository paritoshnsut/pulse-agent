"""Style DNA extractor tests — the deterministic half is asserted exactly."""

import json

import pytest

from conftest import StubClient
from style import dna


def test_avg_length():
    assert dna.avg_length(["abcd", "ab"]) == 3
    assert dna.avg_length([]) == 0


def test_emoji_rate_and_band():
    assert dna.emoji_rate(["hi \U0001F525", "plain"]) == 0.5
    assert dna.emoji_band(0.0) == "none"
    assert dna.emoji_band(0.1) == "rare"
    assert dna.emoji_band(0.5) == "frequent"


def test_caps_rate():
    # "BJP" is ALL-CAPS (len>=2); single "X" is not counted.
    assert dna.caps_rate(["BJP did X", "normal text"]) == 0.5
    assert dna.caps_rate(["all lower here"]) == 0.0


def test_question_rate():
    assert dna.question_rate(["really?", "no"]) == 0.5


def test_hinglish_ratio():
    # tokens: kya yaar nahi hello world there -> 3/6 in seed lexicon
    assert dna.hinglish_ratio(["kya yaar nahi", "hello world there"]) == 0.5
    assert dna.hinglish_ratio(["purely english sentence here"]) == 0.0


def test_hashtag_profile_and_descriptor():
    prof = dna.hashtag_profile(["end tags #modi #bjp", "no tags here"])
    assert prof["avg_count"] == 2.0
    assert prof["case"] == "lowercase"
    assert prof["position"] == "end"
    assert dna.hashtag_descriptor(prof) == "~2.0, lowercase, at end"
    assert dna.hashtag_descriptor({"avg_count": 0}) == "rarely uses hashtags"


def test_ngram_candidates_finds_repeated_signature():
    posts = [
        "let that sink in folks, the numbers don't lie",
        "again, let that sink in — nobody is reacting",
    ]
    cands = dna.ngram_candidates(posts, min_doc_freq=2)
    assert "let that sink in" in cands
    # the shorter sub-phrase should be trimmed in favor of the longer one
    assert "that sink in" not in cands


def test_measure_keys_present():
    m = dna.measure(["A short post.", "Another one here?"])
    for key in (
        "avg_post_length", "emoji_usage", "caps_for_emphasis",
        "uses_rhetorical_questions", "hinglish_mix", "hashtag_style",
        "_ngram_candidates",
    ):
        assert key in m


def test_merge_measured_wins_over_judged():
    measured = dna.measure(["short one", "two words"])
    judged = {
        "sentence_length": "short, punchy",
        "sarcasm_level": "high",
        "tone": "combative",
        "signature_phrases": ["your move"],
        "topics_preferred": ["economy"],
        "things_to_avoid": ["formal language"],
        "avg_post_length": "9999 chars",  # should be IGNORED in favor of measured
    }
    genome = dna.StyleDNAExtractor(client=StubClient("{}")).merge(measured, judged)
    assert genome["avg_post_length"] == measured["avg_post_length"]  # measured wins
    assert genome["avg_post_length"] != "9999 chars"
    assert genome["sarcasm_level"] == "high"                         # judged fills
    assert genome["signature_phrases"] == ["your move"]


def test_extract_end_to_end_with_stub():
    payload = json.dumps({
        "sentence_length": "short, punchy, fragments ok",
        "sarcasm_level": "high",
        "tone": "combative",
        "signature_phrases": ["let that sink in"],
        "topics_preferred": ["economic policy"],
        "things_to_avoid": ["formal language", "passive voice"],
    })
    posts = [
        "RBI holds rates. let that sink in",
        "GDP base effect again. let that sink in",
        "Where's the line item? show me",
    ]
    genome = dna.StyleDNAExtractor(client=StubClient(payload)).extract(posts)
    assert genome["sarcasm_level"] == "high"
    assert genome["uses_rhetorical_questions"] is True   # measured from "?" usage
    assert genome["signature_phrases"] == ["let that sink in"]
    assert genome["avg_post_length"].endswith("chars")


def test_extract_rejects_empty():
    with pytest.raises(ValueError):
        dna.StyleDNAExtractor(client=StubClient("{}")).extract(["", "   "])


def test_extract_and_save_persists(temp_db):
    from pipeline import memory
    acct_id = memory.upsert_account(handle="me", db_path=temp_db)
    payload = json.dumps({"sarcasm_level": "high", "signature_phrases": [],
                          "topics_preferred": [], "things_to_avoid": []})
    ex = dna.StyleDNAExtractor(client=StubClient(payload))
    ex.extract_and_save(acct_id, ["one post here", "another post?"], db_path=temp_db)
    saved = memory.get_style_dna(acct_id, db_path=temp_db)
    assert saved is not None
    assert saved["sample_count"] == 2
    assert saved["genome_a"]["sarcasm_level"] == "high"
