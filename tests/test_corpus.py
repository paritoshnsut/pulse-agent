"""Voice corpus tests: persistent samples, engagement-weighted selection,
deeper Genome A (v2 mechanics + judged depth), human-gated suggestions."""

import json

from conftest import StubClient, patch_settings
from pipeline import memory
from style import corpus as corpus_mod
from style import dna
from style.corpus import CorpusManager, parse_own_lines, select_training_set


# ------------------------------------------------------------- line parsing
def test_parse_own_lines_with_engagement_suffix():
    items = parse_own_lines(
        "plain tweet here\n"
        "tweet with analytics | 230 41 12\n"
        "likes only | 99\n"
        "\n   \n")
    assert len(items) == 3
    assert items[0]["likes"] is None
    assert items[1] == {"content": "tweet with analytics", "kind": "own",
                        "likes": 230, "retweets": 41, "replies": 12}
    assert items[2]["likes"] == 99 and items[2]["retweets"] == 0


# ------------------------------------------------------------ corpus storage
def test_add_own_dedupes_and_counts(temp_db):
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    mgr = CorpusManager(db_path=temp_db)
    r = mgr.add(acct, "tweet one\ntweet two | 50", kind="own")
    assert r["added"] == 2 and r["corpus"]["own"] == 2
    r = mgr.add(acct, "tweet one\ntweet three", kind="own")
    assert r["added"] == 1 and r["duplicates"] == 1
    assert r["corpus"]["own"] == 3


def test_add_inspiration_is_one_piece(temp_db):
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    long_piece = "Para one of an editorial.\n\nPara two.\n\nPara three."
    r = CorpusManager(db_path=temp_db).add(acct, long_piece, kind="inspiration")
    assert r["added"] == 1 and r["corpus"]["inspiration"] == 1
    samples = memory.get_voice_samples(acct, kind="inspiration", db_path=temp_db)
    assert "Para three" in samples[0]["content"]


# ------------------------------------------------------- training selection
def test_selection_keeps_proven_winners_when_over_cap():
    samples = [{"content": f"old {i}", "added_at": f"2026-01-0{i+1}", "likes": None}
               for i in range(5)]
    samples += [{"content": "viral", "added_at": "2026-01-01",
                 "likes": 900, "retweets": 100, "replies": 5}]
    chosen = select_training_set(samples, cap=3)
    texts = [s["content"] for s in chosen]
    assert "viral" in texts          # engagement beats recency
    assert "old 4" in texts and "old 3" in texts  # rest filled by recency
    assert len(chosen) == 3


# --------------------------------------------------------- deeper mechanics
def test_sentence_stats_and_punctuation():
    posts = ["Short. Very short. This sentence has a few more words in it.",
             "One — with an em-dash... and trailing thought"]
    st = dna.sentence_stats(posts)
    assert st["avg_words_per_sentence"] > 0
    assert 0 < st["short_sentence_rate"] <= 1
    p = dna.punctuation_profile(posts)
    assert p["em_dash_rate"] == 0.5 and p["ellipsis_rate"] == 0.5


def test_opener_profile_and_data_rate():
    posts = ["7.2% growth. sounds great.", "but look closer at the base",
             "Why is nobody asking this?\nbecause it's awkward"]
    op = dna.opener_profile(posts)
    assert op["starts_with_number"] == 0.33
    assert op["starts_with_conjunction"] == 0.33
    assert op["starts_with_question"] == 0.33
    assert dna.data_rate(posts) == 0.33


JUDGED_V2 = {
    "sentence_length": "short, punchy", "sarcasm_level": "high",
    "tone": "combative", "signature_phrases": ["let that sink in"],
    "topics_preferred": ["economic policy"], "things_to_avoid": ["formal language"],
    "emotional_palette": ["dry outrage", "amused contempt"],
    "sentiment_baseline": "skeptical-negative",
    "rhetorical_devices": ["irony", "contrast pairs"],
    "argument_structure": "opens with the number, lands on a jab",
    "register": "colloquial with hindi code-switching",
    "influences": {"admired_patterns": ["long build, sharp turn"],
                   "themes": ["institutional decay"]},
}


def test_extract_v2_merges_depth_and_influences():
    ex = dna.StyleDNAExtractor(client=StubClient(json.dumps(JUDGED_V2)))
    genome = ex.extract(["7.2% growth? look at the base effect.",
                         "rates held again — savers lose. let that sink in"],
                        inspiration=["An admired editorial about institutions."])
    assert genome["mechanics"]["data_rate"] == 0.5
    assert genome["emotional_palette"] == ["dry outrage", "amused contempt"]
    assert genome["argument_structure"].startswith("opens with the number")
    assert genome["influences"]["admired_patterns"] == ["long build, sharp turn"]
    # measured still wins over anything judged
    assert genome["avg_post_length"].endswith("chars")


def test_style_rules_render_v2_fields():
    from pipeline.generator import _style_rules
    genome = {"tone": "combative",
              "mechanics": {"avg_words_per_sentence": 7.5, "short_sentence_rate": 0.4,
                            "em_dash_rate": 0.3, "data_rate": 0.6,
                            "starts_lowercase": 0.5, "starts_with_number": 0.1},
              "emotional_palette": ["dry outrage"],
              "sentiment_baseline": "skeptical",
              "rhetorical_devices": ["irony"],
              "argument_structure": "number first, jab last",
              "register": "colloquial",
              "influences": {"admired_patterns": ["sharp turn"]}}
    rules = _style_rules(genome)
    assert "7.5 words/sentence" in rules and "opens lowercase" in rules
    assert "dry outrage" in rules and "number first, jab last" in rules
    assert "borrow the move" in rules and "sharp turn" in rules


# ----------------------------------------------------------------- retrain
def test_retrain_uses_corpus_and_preserves_genome_b(temp_db):
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    memory.save_style_dna(acct, genome_a={"tone": "old"},
                          genome_b={"hook_patterns": ["x"]}, blend=0.3,
                          db_path=temp_db)
    mgr = CorpusManager(client=StubClient(json.dumps(JUDGED_V2)), db_path=temp_db)
    try:
        mgr.retrain(acct)
        assert False, "should require >=5 own samples"
    except ValueError:
        pass
    mgr.add(acct, "\n".join(f"my tweet number {i} about econ?" for i in range(8)))
    mgr.add(acct, "An admired editorial.", kind="inspiration")
    out = mgr.retrain(acct)
    assert out["trained_on"] == 8 and out["inspiration_used"] == 1
    saved = memory.get_style_dna(acct, db_path=temp_db)
    assert saved["version"] == 2
    assert saved["genome_a"]["sarcasm_level"] == "high"
    assert saved["genome_a"]["mechanics"]["data_rate"] is not None
    assert saved["genome_b"] == {"hook_patterns": ["x"]}   # carried forward
    assert saved["blend"] == 0.3


# -------------------------------------------------------------- suggestions
def _interested_account(db):
    acct = memory.upsert_account(handle="me", topics=["rbi policy", "inflation"],
                                 db_path=db)
    return memory.get_account(acct, db_path=db)


def test_suggest_files_matching_articles_capped(temp_db, monkeypatch):
    import config as config_mod
    patch_settings(monkeypatch, corpus_mod, corpus_suggest_max=2)
    account = _interested_account(temp_db)
    for i in range(4):
        memory.insert_article({
            "source": "rss", "source_name": "Mint", "url": f"https://t/s{i}",
            "title": f"RBI inflation outlook piece {i}",
            "published_at": memory._now()}, db_path=temp_db)
    memory.insert_article({"source": "rss", "url": "https://t/cricket",
                           "title": "Cricket final tonight",
                           "published_at": memory._now()}, db_path=temp_db)
    mgr = CorpusManager(db_path=temp_db)
    assert mgr.suggest(account) == 2                      # capped
    assert mgr.suggest(account) == 2                      # next 2, no re-files
    assert mgr.suggest(account) == 0                      # exhausted
    pending = memory.get_corpus_suggestions(account["id"], db_path=temp_db)
    assert len(pending) == 4
    assert all("rbi" in p["reason"] or "inflation" in p["reason"] for p in pending)


def test_accept_adds_inspiration_reject_just_closes(temp_db):
    account = _interested_account(temp_db)
    memory.insert_article({"source": "rss", "url": "https://t/s1",
                           "title": "RBI inflation deep dive",
                           "description": "a long editorial",
                           "published_at": memory._now()}, db_path=temp_db)
    mgr = CorpusManager(db_path=temp_db)
    mgr.suggest(account)
    s1 = memory.get_corpus_suggestions(account["id"], db_path=temp_db)[0]
    mgr.accept_suggestion(s1["id"], account["id"])
    assert memory.count_voice_samples(account["id"], db_path=temp_db)["inspiration"] == 1
    samples = memory.get_voice_samples(account["id"], kind="inspiration", db_path=temp_db)
    assert "RBI inflation deep dive" in samples[0]["content"]
    assert samples[0]["origin"].startswith("article:")
    assert memory.get_corpus_suggestions(account["id"], db_path=temp_db) == []
    # rejecting an unknown id raises; rejecting valid one closes silently
    try:
        mgr.accept_suggestion(999, account["id"])
        assert False
    except ValueError:
        pass
