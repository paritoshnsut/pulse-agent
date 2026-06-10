"""Context retriever tests — all layers are pure Python + SQLite, no model."""

import json

from conftest import StubClient
from pipeline import context, memory
from pipeline.context import ContextRetriever, extract_keywords


# ------------------------------------------------------------- keywords
def test_extract_keywords_drops_stopwords_and_news_noise():
    kws = extract_keywords("RBI says it will hold rates after inflation report")
    assert "rbi" in kws and "rates" in kws and "inflation" in kws
    assert "says" not in kws and "after" not in kws and "will" not in kws


def test_extract_keywords_dedupes_caps_and_orders():
    kws = extract_keywords("budget budget deficit", "deficit fiscal slippage "
                           "one two three four five six seven eight nine ten")
    assert kws[0] == "budget" and kws[1] == "deficit"
    assert len(kws) == len(set(kws)) <= context.MAX_KEYWORDS


def test_extract_keywords_handles_none_and_empty():
    assert extract_keywords(None, "", "the a an") == []


# ----------------------------------------------------------- memory reads
def _seed_memory(db):
    acct_id = memory.upsert_account(handle="me", db_path=db)
    memory.seed_event("rbi-rate-policy", "RBI holds repo rate at 6.5%",
                      source_url="https://t/old1", event_date="2026-05-01T00:00:00+00:00",
                      db_path=db)
    memory.seed_event("rbi-rate-policy", "RBI flags sticky food inflation",
                      source_url="https://t/old2", event_date="2026-05-20T00:00:00+00:00",
                      db_path=db)
    memory.seed_event("cricket-worldcup", "India wins by 7 wickets",
                      source_url="https://t/cricket", db_path=db)
    memory.log_stance(acct_id, "rbi-rate-policy",
                      "thinks rate holds quietly punish savers", db_path=db)
    memory.insert_article({"source": "rss", "url": "https://t/rel",
                           "title": "Inflation hits 14-month high",
                           "published_at": "2026-06-01T00:00:00+00:00"}, db_path=db)
    return acct_id


def test_find_events_matches_keywords_newest_first(temp_db):
    _seed_memory(temp_db)
    events = memory.find_events(["rbi"], db_path=temp_db)
    assert [e["summary"] for e in events] == [
        "RBI flags sticky food inflation", "RBI holds repo rate at 6.5%"]
    assert memory.find_events(["quantum"], db_path=temp_db) == []
    assert memory.find_events([], db_path=temp_db) == []


def test_seed_event_dedupes_by_url(temp_db):
    a = memory.seed_event("t", "summary one", source_url="https://t/x", db_path=temp_db)
    b = memory.seed_event("t", "summary again", source_url="https://t/x", db_path=temp_db)
    assert a == b
    assert len(memory.find_events(["summary"], db_path=temp_db)) == 1


def test_find_stances_scoped_to_account(temp_db):
    acct_id = _seed_memory(temp_db)
    other = memory.upsert_account(handle="other", db_path=temp_db)
    assert len(memory.find_stances(acct_id, ["rbi"], db_path=temp_db)) == 1
    assert memory.find_stances(other, ["rbi"], db_path=temp_db) == []


def test_find_related_articles_excludes_self(temp_db):
    _seed_memory(temp_db)
    art_id = memory.find_related_articles(["inflation"], db_path=temp_db)[0]["id"]
    assert memory.find_related_articles(
        ["inflation"], exclude_article_id=art_id, db_path=temp_db) == []


# ---------------------------------------------------------------- retrieve
def test_retrieve_composes_layers(temp_db):
    acct_id = _seed_memory(temp_db)
    signal = {"title": "RBI holds rates again as inflation stays hot",
              "topic": "rbi-rate-policy", "angle": "savers lose again"}
    ctx = ContextRetriever(db_path=temp_db).retrieve(signal, {"id": acct_id})
    assert len(ctx["historical_events"]) == 2
    assert ctx["your_stances"][0]["stance"].startswith("thinks rate holds")
    assert ctx["related_coverage"][0]["title"] == "Inflation hits 14-month high"
    # narrative thread is the same events oldest-first
    assert ctx["narrative_thread"][0]["summary"] == "RBI holds repo rate at 6.5%"
    assert ctx["competitor_gap"] is None
    # cricket event never leaks into an RBI story
    assert all("wickets" not in e["summary"] for e in ctx["historical_events"])


def test_retrieve_excludes_own_url_from_history(temp_db):
    acct_id = _seed_memory(temp_db)
    signal = {"title": "RBI holds repo rate", "url": "https://t/old2"}
    ctx = ContextRetriever(db_path=temp_db).retrieve(signal, {"id": acct_id})
    assert all(e["source_url"] != "https://t/old2" for e in ctx["historical_events"])


def test_render_empty_memory_is_none(temp_db):
    acct_id = memory.upsert_account(handle="me", db_path=temp_db)
    r = ContextRetriever(db_path=temp_db)
    assert r.context_for({"title": "Totally novel story"}, {"id": acct_id}) is None


def test_render_includes_sections_and_arc(temp_db):
    acct_id = _seed_memory(temp_db)
    signal = {"title": "RBI holds rates again as inflation stays hot",
              "topic": "rbi-rate-policy"}
    text = ContextRetriever(db_path=temp_db).context_for(signal, {"id": acct_id})
    assert "Past events on this topic" in text
    assert "Positions YOU have already taken" in text
    assert "Related coverage already seen" in text
    assert "Narrative arc: 2 related events" in text
    assert "2026-05-01" in text and "punish savers" in text


# ---------------------------------------------- generator + decision wiring
def test_generator_injects_memory_block():
    from pipeline.generator import ContentGenerator

    stub = StubClient(json.dumps({"text": "post", "hashtags": [], "note": ""}))
    gen = ContentGenerator(client=stub)
    gen.generate({"title": "t"}, {}, "hot_take", context="Past events:\n  - thing")
    prompt = stub.messages.calls[0]["messages"][0]["content"]
    assert "YOUR MEMORY" in prompt and "- thing" in prompt
    assert "NEVER invent memory" in prompt
    stub2 = StubClient(json.dumps({"text": "post", "hashtags": [], "note": ""}))
    ContentGenerator(client=stub2).generate({"title": "t"}, {}, "hot_take")
    assert "YOUR MEMORY" not in stub2.messages.calls[0]["messages"][0]["content"]


def test_decision_run_seeds_timeline_for_fire(temp_db):
    from pipeline.decision import DecisionAgent

    acct_id = memory.upsert_account(handle="me", db_path=temp_db)
    memory.insert_article({
        "source": "rss", "url": "https://t/fresh", "title": "RBI shock rate cut",
        "published_at": memory._now(),
    }, db_path=temp_db)
    payload = json.dumps({"relevance": 10, "reaction_potential": 10,
                          "angle": "a", "topic": "rbi-rate-policy", "reasoning": "r"})
    agent = DecisionAgent(client=StubClient(payload))
    agent.run(memory.get_account(acct_id, db_path=temp_db), db_path=temp_db)
    events = memory.find_events(["rbi"], db_path=temp_db)
    assert len(events) == 1
    assert events[0]["topic"] == "rbi-rate-policy"
    assert events[0]["source_url"] == "https://t/fresh"
    # and the signal row carries the topic for the updater's hint later
    sig = memory.get_signals_by_tier("FIRE", db_path=temp_db)[0]
    assert sig["topic"] == "rbi-rate-policy"
