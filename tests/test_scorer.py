"""Persona consistency scorer tests — mechanical checks exact; Claude stubbed."""

import json

from conftest import StubClient
from style import scorer as scorer_mod
from style.scorer import PersonaConsistencyScorer, mechanical_checks

GENOME = {
    "avg_post_length": "180 chars", "emoji_usage": "none",
    "hashtag_style": "2-3, lowercase, at end", "sarcasm_level": "high",
}


def _scorer(payload):
    return PersonaConsistencyScorer(client=StubClient(payload))


# ---------------------------------------------------------------- mechanical
def test_mechanical_emoji_violation_detected():
    m = mechanical_checks("big news 🔥", GENOME)
    assert m["emoji_ok"] is False


def test_mechanical_emoji_ok_when_clean():
    m = mechanical_checks("big news, no emoji here", GENOME)
    assert m["emoji_ok"] is True


def test_mechanical_hashtag_case_violation():
    # uppercase tag violates a lowercase voice
    m = mechanical_checks("text #GDP", GENOME)
    assert m["hashtag_ok"] is False


def test_mechanical_hashtag_count_violation():
    # 4 tags exceeds the "2-3" cap (regex picks up 2 as the cap)
    m = mechanical_checks("t #a #b #c #d", GENOME)
    assert m["hashtag_ok"] is False


def test_mechanical_hashtag_ok_when_compliant():
    m = mechanical_checks("text #gdp #economy", GENOME)
    assert m["hashtag_ok"] is True


def test_mechanical_no_tags_voice():
    g = {"hashtag_style": "rarely uses hashtags"}
    assert mechanical_checks("clean text", g)["hashtag_ok"] is True
    assert mechanical_checks("text #nope", g)["hashtag_ok"] is False


def test_mechanical_length_ratio():
    m = mechanical_checks("x" * 90, GENOME)  # target 180 -> ratio 0.5
    assert m["length_ratio"] == 0.5


# ----------------------------------------------------------------- scoring
def test_score_composite_is_mean_of_axes():
    payload = json.dumps({
        "vocabulary": 80, "sentence_rhythm": 70, "tone": 90,
        "stance_consistency": 60, "emotional_register": 100,
        "weakest_axis": "stance_consistency", "weakest_axis_feedback": "fix stance",
    })
    out = _scorer(payload).score("some draft #gdp", GENOME)
    # mean(80,70,90,60,100) = 80.0
    assert out["composite"] == 80.0
    assert out["axes"]["tone"] == 90.0
    assert out["weakest_axis"] == "stance_consistency"
    assert "mechanical" in out


def test_score_clamps_out_of_range():
    payload = json.dumps({"vocabulary": 150, "sentence_rhythm": -20, "tone": 50,
                          "stance_consistency": 50, "emotional_register": 50})
    out = _scorer(payload).score("draft", GENOME)
    assert out["axes"]["vocabulary"] == 100.0   # clamped down
    assert out["axes"]["sentence_rhythm"] == 0.0  # clamped up


def test_score_garbage_json_fails_safe_to_review():
    out = _scorer("not json").score("draft", GENOME)
    assert out["composite"] == 0.0
    assert all(v == 0.0 for v in out["axes"].values())


def test_band_thresholds():
    assert PersonaConsistencyScorer.band(85) == "pass"
    assert PersonaConsistencyScorer.band(70) == "pass"
    assert PersonaConsistencyScorer.band(69) == "regenerate"
    assert PersonaConsistencyScorer.band(60) == "regenerate"
    assert PersonaConsistencyScorer.band(59) == "flag_for_review"
