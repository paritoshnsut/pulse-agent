"""
run_pipeline.py — the spine, wired for real use across verticals.

  python run_pipeline.py

Chains the two modules over your chosen verticals:
  1. NewsMonitor.run()   -> pull RSS for the selected verticals/regions, dedup, store (tagged)
  2. DecisionAgent.run() -> score every unprocessed article for your account
Then prints the FIRE/WARM shortlist, grouped by vertical.

Needs ANTHROPIC_API_KEY in .env (scoring is a live Claude call). RSS needs no key.

ONE-VOICE CAVEAT: this scores everything against a single account/niche. A single
persona that credibly reacts to sports AND politics AND finance AND entertainment
is unusual — the scorer's "does THIS account have a distinctive take" judgment
works best within one lane. If you want genuinely separate lanes, run one account
per vertical (the schema already supports multiple accounts; you'd make the
articles.processed flag per-account when you get there). For now, set a broad
niche, or narrow VERTICALS to the lane you're posting in today.
"""

import logging

from pipeline import memory
from pipeline.context import ContextRetriever
from pipeline.decision import DecisionAgent
from pipeline.generator import ContentGenerator
from pipeline.monitor import NewsMonitor
from sources import feeds_for
from style.voice import effective_for
from style.scorer import PersonaConsistencyScorer

logging.basicConfig(level=logging.INFO, format="%(name)s | %(levelname)s | %(message)s")

# --- What to cover. Edit freely. ---
VERTICALS = ["politics", "finance", "sports", "entertainment"]
REGIONS = ["india", "us"]            # add "global" for BBC/FT/Economist etc.

# --- Your single account. Set the niche to match what you actually post about. ---
ACCOUNT = {
    "handle": "me",
    "niche": "data-backed Indian + US political and economic commentary, skeptical of spin",
    "topics": ["indian politics", "us politics", "economic policy", "markets"],
}

# How many of the top signals to actually draft per run. Format is chosen per
# signal by the decision agent; DRAFT_FORMAT is only the fallback.
DRAFT_TOP_N = 5
DRAFT_FORMAT = "hot_take"


def main() -> None:
    memory.init_db()

    acct_id = memory.upsert_account(
        handle=ACCOUNT["handle"], niche=ACCOUNT["niche"], topics=ACCOUNT["topics"]
    )
    account = memory.get_account(acct_id)

    feeds = feeds_for(VERTICALS, REGIONS)
    print(f"\nPulling {len(feeds)} feeds across {VERTICALS} ({REGIONS})\n")

    ingest = NewsMonitor(rss_feeds=feeds).run()
    print(f"\nIngested: {ingest['new']} new, {ingest['duplicate']} duplicate\n")

    tally = DecisionAgent().run(account)
    print(f"\nScored -> {tally}\n")

    # Draft the top signals in voice, gated by persona consistency (rule #9).
    genome_row = memory.get_style_dna(acct_id)
    if not genome_row:
        print("No Style DNA yet — run `python -m style.dna` on your posts to enable drafting.")
    else:
        genome = effective_for(acct_id)
        gen, scorer = ContentGenerator(), PersonaConsistencyScorer()
        retriever = ContextRetriever()
        shortlist = (memory.get_signals_by_tier("FIRE")
                     + memory.get_signals_by_tier("WARM"))[:DRAFT_TOP_N]
        print(f"================ DRAFTS ({len(shortlist)}) ================\n")
        for s in shortlist:
            draft = gen.generate_checked(
                s, genome, fmt=s.get("format") or DRAFT_FORMAT, scorer=scorer,
                account_id=acct_id, persist=True,
                context=retriever.context_for(s, account),
            )
            tag = f"{s.get('vertical') or '-'}/{s.get('region') or '-'}"
            flag = " ⚠️ REVIEW" if draft["needs_review"] else ""
            score = f"{draft['persona_score']:.0f}" if draft["persona_score"] is not None else "—"
            print(f"[{s['score']:.1f} {tag}] persona={score}{flag}")
            print(f"  {s['title']}")
            if draft["empty"]:
                print(f"  (no draft: {draft['note']})\n")
            else:
                print(f"  \"{draft['content']}\"\n")
    print("Drafts saved. Approve/edit/reject them to feed the learning loop.")


if __name__ == "__main__":
    main()
