"""
presets.py — starter packs for onboarding any kind of account.

Pulse began as a political-commentary tool; the engine is domain-agnostic, but
a brand or creator shouldn't have to invent a niche string and a topic list
from scratch. Each preset prefills the account `kind`, a niche template,
suggested topics, default verticals, and a starter watch list (subreddits /
trends geos) appropriate to that world. The web onboarding offers these as a
dropdown; everything stays fully editable.

These are CONVENIENCE defaults, not constraints — pick one, tweak, go.
"""

from __future__ import annotations

# Each preset: kind + niche template + topics + verticals + starter watch refs.
PRESETS: dict[str, dict] = {
    "political_commentator": {
        "label": "Political / news commentator",
        "kind": "commentator",
        "niche": "sharp, data-backed political commentary, skeptical of spin",
        "topics": ["politics", "policy", "economy", "elections"],
        "verticals": ["politics"],
        "watch": [("subreddit", "politics"), ("trends_geo", "US")],
    },
    "saas_founder": {
        "label": "SaaS founder / B2B",
        "kind": "brand",
        "niche": "B2B SaaS founder sharing build-in-public lessons, product "
                 "updates, and sharp takes on our category",
        "topics": ["saas", "startups", "product", "b2b marketing", "our category"],
        "verticals": ["business"],
        "watch": [("subreddit", "SaaS"), ("subreddit", "startups")],
    },
    "dtc_ecommerce": {
        "label": "D2C / e-commerce brand",
        "kind": "brand",
        "niche": "direct-to-consumer brand with a distinct point of view on our "
                 "category, customers, and product drops",
        "topics": ["our product category", "customer stories", "launches", "lifestyle"],
        "verticals": ["business"],
        "watch": [("subreddit", "ecommerce")],
    },
    "creator": {
        "label": "Creator / personal brand",
        "kind": "creator",
        "niche": "creator building an audience around a clear niche, mixing "
                 "personal story, how-to value, and strong opinions",
        "topics": ["my niche", "audience growth", "behind the scenes", "lessons"],
        "verticals": [],
        "watch": [],
    },
    "finance_creator": {
        "label": "Finance / markets",
        "kind": "creator",
        "niche": "markets & personal-finance commentary — clear, contrarian, "
                 "data-led, allergic to hype",
        "topics": ["markets", "investing", "personal finance", "macro"],
        "verticals": ["finance"],
        "watch": [("subreddit", "investing"), ("subreddit", "stocks")],
    },
    "fitness_wellness": {
        "label": "Fitness / wellness brand",
        "kind": "brand",
        "niche": "fitness & wellness brand sharing science-backed advice, myth-"
                 "busting, and our product where it genuinely helps",
        "topics": ["training", "nutrition", "recovery", "wellness myths"],
        "verticals": [],
        "watch": [("subreddit", "fitness")],
    },
    "local_business": {
        "label": "Local business",
        "kind": "brand",
        "niche": "local business building community presence — offers, behind-"
                 "the-scenes, neighbourhood stories, customer love",
        "topics": ["our offerings", "community", "customer stories", "local events"],
        "verticals": [],
        "watch": [],
    },
    "agency": {
        "label": "Agency (managing client brands)",
        "kind": "brand",
        "niche": "set per client — create one account per brand you manage and "
                 "train each on that client's voice",
        "topics": [],
        "verticals": [],
        "watch": [],
    },
}


def list_presets() -> list[dict]:
    """Lightweight list for the onboarding dropdown."""
    return [{"id": pid, "label": p["label"], "kind": p["kind"],
             "niche": p["niche"], "topics": p["topics"], "verticals": p["verticals"]}
            for pid, p in PRESETS.items()]
