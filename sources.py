"""
sources.py — the RSS source catalog.

Feeds organized by VERTICAL -> REGION. Each entry is (name, url). The scorer is
niche-agnostic, so the only thing that decides what gets covered is which feeds
you pull plus each account's niche. Use feeds_for(...) to select.

NOTE ON FEED URLS: news outlets rotate RSS endpoints periodically. These were
chosen from current, well-known endpoints, but expect a few to drift over time.
The monitor skips dead/empty feeds gracefully and logs them — run
`python check_feeds.py` to see which are live and prune the rest.
"""

from __future__ import annotations

SOURCES: dict[str, dict[str, list[tuple[str, str]]]] = {
    # ----------------------------------------------------------- POLITICS
    "politics": {
        "india": [
            ("The Hindu — National", "https://www.thehindu.com/news/national/feeder/default.rss"),
            ("The Hindu — Opinion", "https://www.thehindu.com/opinion/feeder/default.rss"),
            ("Indian Express — India", "https://indianexpress.com/section/india/feed/"),
            ("Indian Express — Political Pulse", "https://indianexpress.com/section/political-pulse/feed/"),
            ("NDTV — India", "https://feeds.feedburner.com/ndtvnews-india-news"),
            ("Hindustan Times — India", "https://www.hindustantimes.com/rss/india-news/rssfeed.xml"),
            ("Times of India — India", "https://timesofindia.indiatimes.com/rssfeeds/-2128936835.cms"),
            ("Times of India — Top Stories", "https://timesofindia.indiatimes.com/rssfeedstopstories.cms"),
            ("Scroll.in", "https://scroll.in/feeds/all.rss"),
            # Wire services — primary sources for Indian political news
            ("ANI News", "https://aninews.in/feed/"),
            ("The Wire", "https://thewire.in/feed/"),
            ("The Print", "https://theprint.in/feed/"),
            ("Newslaundry", "https://www.newslaundry.com/feed"),
            ("The Quint", "https://www.thequint.com/tech/rss"),
            # Government primary sources
            ("PIB — All Releases", "https://pib.gov.in/allReleaseMain.aspx?ModId=6&Lang=1&Regid=3"),
            ("PIB — PMO", "https://pib.gov.in/rss/ministryrss.aspx?ministry=2"),
            ("PIB — Finance Ministry", "https://pib.gov.in/rss/ministryrss.aspx?ministry=7"),
            # Fact-check outlets (critical for political commentary)
            ("Alt News", "https://www.altnews.in/feed/"),
            ("Boom Live", "https://www.boomlive.in/feed"),
        ],
        "us": [
            ("Politico — Politics", "https://rss.politico.com/politics-news.xml"),
            ("Politico — Congress", "https://rss.politico.com/congress.xml"),
            ("Politico — Playbook", "https://rss.politico.com/playbook.xml"),
            ("The Hill", "https://thehill.com/news/feed/"),
            ("NPR — Politics", "https://feeds.npr.org/1014/rss.xml"),
            ("NYT — Politics", "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml"),
            ("Washington Post — Politics", "https://feeds.washingtonpost.com/rss/politics"),
            ("FiveThirtyEight", "https://fivethirtyeight.com/all/feed"),
            ("Guardian — US Politics", "https://www.theguardian.com/us-news/us-politics/rss"),
            ("NBC News — Politics", "https://feeds.nbcnews.com/nbcnews/public/politics"),
        ],
    },
    # ------------------------------------------------------------ FINANCE
    "finance": {
        "india": [
            ("Mint — Markets", "https://www.livemint.com/rss/markets"),
            ("Mint — Economy", "https://www.livemint.com/rss/economy"),
            ("Mint — Companies", "https://www.livemint.com/rss/companies"),
            ("Moneycontrol — Latest", "https://www.moneycontrol.com/rss/latestnews.xml"),
            ("Moneycontrol — Markets", "https://www.moneycontrol.com/rss/marketsnews.xml"),
            ("Moneycontrol — Economy", "https://www.moneycontrol.com/rss/economy.xml"),
            ("Economic Times — Top", "https://economictimes.indiatimes.com/rssfeedstopstories.cms"),
            ("Economic Times — Markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
            ("Business Standard — Markets", "https://www.business-standard.com/rss/markets-106.rss"),
        ],
        "us": [
            ("CNBC — Top News", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"),
            ("CNBC — Finance", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664"),
            ("MarketWatch — Top Stories", "https://feeds.marketwatch.com/marketwatch/topstories/"),
            ("MarketWatch — Real-time", "https://feeds.marketwatch.com/marketwatch/realtimeheadlines/"),
            ("NYT — Business", "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml"),
            ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
            ("NPR — Business", "https://feeds.npr.org/1006/rss.xml"),
        ],
        "global": [
            ("The Economist — Finance & Economics", "https://www.economist.com/finance-and-economics/rss.xml"),
            ("Financial Times — Home", "https://www.ft.com/rss/home"),
        ],
    },
    # ------------------------------------------------------------- SPORTS
    "sports": {
        "india": [
            ("Times of India — Sports", "https://timesofindia.indiatimes.com/rssfeeds/4719148.cms"),
            ("Times of India — Cricket", "https://timesofindia.indiatimes.com/rssfeeds/54829575.cms"),
            ("NDTV Sports — Cricket", "https://feeds.feedburner.com/ndtvsports-cricket"),
            ("The Hindu — Sport", "https://www.thehindu.com/sport/feeder/default.rss"),
            ("Hindustan Times — Cricket", "https://www.hindustantimes.com/rss/cricket/rssfeed.xml"),
            ("Indian Express — Sports", "https://indianexpress.com/section/sports/feed/"),
            ("ESPNcricinfo", "https://www.espncricinfo.com/rss/content/story/feeds/0.xml"),
        ],
        "us": [
            ("ESPN — Top", "https://www.espn.com/espn/rss/news"),
            ("ESPN — NFL", "https://www.espn.com/espn/rss/nfl/news"),
            ("ESPN — NBA", "https://www.espn.com/espn/rss/nba/news"),
            ("NYT — Sports", "https://rss.nytimes.com/services/xml/rss/nyt/Sports.xml"),
            ("Yahoo Sports", "https://sports.yahoo.com/rss/"),
        ],
        "global": [
            ("BBC Sport", "https://feeds.bbci.co.uk/sport/rss.xml"),
            ("Sky Sports", "https://www.skysports.com/rss/12040"),
        ],
    },
    # -------------------------------------------------------- ENTERTAINMENT
    "entertainment": {
        "india": [
            ("The Hindu — Entertainment", "https://www.thehindu.com/entertainment/feeder/default.rss"),
            ("Indian Express — Entertainment", "https://indianexpress.com/section/entertainment/feed/"),
            ("Times of India — Entertainment", "https://timesofindia.indiatimes.com/rssfeeds/1081479906.cms"),
            ("NDTV — Movies", "https://feeds.feedburner.com/ndtvmovies-latest"),
            ("Hindustan Times — Entertainment", "https://www.hindustantimes.com/rss/entertainment/rssfeed.xml"),
            ("Bollywood Life", "https://www.bollywoodlife.com/feed/"),
        ],
        "us": [
            ("Variety", "https://variety.com/feed/"),
            ("The Hollywood Reporter", "https://www.hollywoodreporter.com/feed/"),
            ("Deadline", "https://deadline.com/feed/"),
            ("Rolling Stone", "https://www.rollingstone.com/feed/"),
            ("Billboard", "https://www.billboard.com/feed/"),
            ("NYT — Movies", "https://rss.nytimes.com/services/xml/rss/nyt/Movies.xml"),
            ("E! Online", "https://www.eonline.com/syndication/feeds/rssfeeds/topstories.xml"),
        ],
        "global": [
            ("BBC — Entertainment & Arts", "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml"),
        ],
    },
    # ----------------------------------------------------------- BUSINESS
    # General business / startup / company news. The default lane for most
    # brands: what's happening in their world that they can comment on.
    "business": {
        "india": [
            ("YourStory", "https://yourstory.com/feed"),
            ("Inc42", "https://inc42.com/feed/"),
            ("Business Standard — Companies", "https://www.business-standard.com/rss/companies-101.rss"),
            ("Livemint — Companies", "https://www.livemint.com/rss/companies"),
        ],
        "us": [
            ("Inc.com", "https://www.inc.com/rss"),
            ("Entrepreneur", "https://www.entrepreneur.com/latest.rss"),
            ("Fast Company", "https://www.fastcompany.com/latest/rss"),
            ("CNBC — Business", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10001147"),
        ],
        "global": [
            ("Harvard Business Review", "https://hbr.org/feed"),
        ],
    },
    # --------------------------------------------------------------- TECH
    # Product / startup / dev signal — the lane for SaaS founders and tech
    # brands. Includes Hacker News + Product Hunt, the two best keyless feeds
    # for "what's launching / what's hot" right now.
    "tech": {
        "us": [
            ("TechCrunch", "https://techcrunch.com/feed/"),
            ("The Verge", "https://www.theverge.com/rss/index.xml"),
            ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
            ("VentureBeat", "https://venturebeat.com/feed/"),
            ("Engadget", "https://www.engadget.com/rss.xml"),
        ],
        "global": [
            ("Hacker News — Front Page", "https://hnrss.org/frontpage"),
            ("Product Hunt", "https://www.producthunt.com/feed"),
        ],
    },
    # ---------------------------------------------------------- MARKETING
    # The brand's professional conversation: what marketers/social teams are
    # talking about. Lets a brand ride a marketing-industry moment (a platform
    # change, a viral campaign, an algorithm shift) — its true native news.
    # Also the CRAFT lane: which campaigns are winning (Ad Age / The Drum) —
    # creative inspiration the generator can reference.
    "marketing": {
        "india": [
            ("ET BrandEquity", "https://brandequity.economictimes.indiatimes.com/rss/topstories"),
        ],
        "global": [
            ("Social Media Today", "https://www.socialmediatoday.com/feeds/news/"),
            ("Marketing Dive", "https://www.marketingdive.com/feeds/news/"),
            ("Search Engine Journal", "https://www.searchenginejournal.com/feed/"),
            ("Adweek", "https://www.adweek.com/feed/"),
            ("Ad Age", "https://adage.com/rss.xml"),
            ("The Drum", "https://www.thedrum.com/rss.xml"),
            ("Marketing Brew", "https://www.marketingbrew.com/feed"),
            ("HubSpot — Marketing", "https://blog.hubspot.com/marketing/rss.xml"),
            ("Content Marketing Institute", "https://contentmarketinginstitute.com/feed/"),
        ],
    },
    # ------------------------------------------------------------ CULTURE
    # Internet/youth culture — memes, drops, aesthetics, fandoms. This is the
    # lane brands actually ride (vs hard news, which brand-safety suppresses):
    # a meme format peaking, a collab dropping, a fandom moment. Distinct from
    # "lifestyle" (consumer-industry news) on purpose.
    "culture": {
        "india": [
            ("Homegrown", "https://homegrown.co.in/feed"),
        ],
        "us": [
            ("Know Your Meme", "https://knowyourmeme.com/newsfeed.rss"),
            ("Polygon", "https://www.polygon.com/rss/index.xml"),
            ("IGN", "https://feeds.feedburner.com/ign/all"),
            ("BuzzFeed", "https://www.buzzfeed.com/index.xml"),
            ("Highsnobiety", "https://www.highsnobiety.com/feed/"),
            ("Dazed", "https://www.dazeddigital.com/rss"),
        ],
    },
    # --------------------------------------------------------- LIFESTYLE
    # Consumer culture / trend-spotting for D2C, retail, fashion, food brands.
    # This is where a brand catches a cultural wave it can safely surf (vs.
    # hard news, which the brand-safety multiplier suppresses for brands).
    "lifestyle": {
        "us": [
            ("Mashable", "https://mashable.com/feeds/rss/all"),
            ("Hypebeast", "https://hypebeast.com/feed"),
            ("Glossy", "https://www.glossy.co/feed/"),
            ("Retail Dive", "https://www.retaildive.com/feeds/news/"),
            ("Vox", "https://www.vox.com/rss/index.xml"),
        ],
    },
    # ----------------------------------------------------------- WELLNESS
    # Health, fitness, nutrition, wellness — for fitness/wellness brands and
    # creators. Mostly evergreen-adjacent, science-vs-myth fodder.
    "wellness": {
        "us": [
            ("Well+Good", "https://www.wellandgood.com/feed/"),
            ("mindbodygreen", "https://www.mindbodygreen.com/rss"),
            ("Healthline — Health News", "https://www.healthline.com/rss/health-news"),
            ("Self", "https://www.self.com/feed/rss"),
        ],
    },
}

VERTICALS = tuple(SOURCES.keys())
REGIONS = ("india", "us", "global")


# --------------------------------------------------------------------------- #
# Source weights — a small multiplier on the signal composite (0.8-1.0).
# Wire services and national outlets carry full weight; aggregators and
# social-derived items slightly less. Cheap insurance against drafting a hot
# take off a junk source. Unknown sources default to 1.0 (never punished for
# being unrecognized — the same honesty rule as everywhere else).
# --------------------------------------------------------------------------- #
SOURCE_KIND_WEIGHTS: dict[str, float] = {
    "reddit": 0.9,            # a thread is a lead, not a report
    "reddit_search": 0.9,
    "trends": 0.9,            # a query spike, not a story
    "wikipedia": 0.9,         # edit storm = something happened, details unverified
    "yt_search": 0.95,        # discovered video — not a verified outlet
    "gnews": 1.0,             # Google-curated from real outlets (source_name carries the outlet)
    "telegram_channel": 1.0,  # primary source: politician/party speaking directly
}

DOMAIN_WEIGHTS: dict[str, float] = {
    "finance.yahoo.com": 0.85,   # aggregator
    "news.yahoo.com": 0.85,
}

WEIGHT_FLOOR = 0.8


def source_weight_for(article: dict) -> float:
    """0.8-1.0 multiplier for an article based on where it came from."""
    w = SOURCE_KIND_WEIGHTS.get((article.get("source") or "").lower(), 1.0)
    url = article.get("url") or ""
    for domain, dw in DOMAIN_WEIGHTS.items():
        if domain in url:
            w = min(w, dw)
    return max(WEIGHT_FLOOR, w)


def feeds_for(
    verticals: list[str] | None = None,
    regions: list[str] | None = None,
) -> list[dict]:
    """
    Flatten the catalog into feed specs the monitor can consume.

    Each spec: {"url", "name", "vertical", "region"}.
    verticals=None -> all verticals. regions=None -> all regions.

        feeds_for(["politics"], ["india", "us"])  # IN + US politics only
        feeds_for(["finance", "sports"])           # those two, all regions
        feeds_for()                                # everything
    """
    verticals = verticals or list(SOURCES.keys())
    out: list[dict] = []
    seen: set[str] = set()
    for v in verticals:
        if v not in SOURCES:
            raise ValueError(f"Unknown vertical '{v}'. Known: {VERTICALS}")
        region_map = SOURCES[v]
        wanted = regions or list(region_map.keys())
        for r in wanted:
            for name, url in region_map.get(r, []):
                if url in seen:
                    continue
                seen.add(url)
                out.append({"url": url, "name": name, "vertical": v, "region": r})
    return out


if __name__ == "__main__":
    print(f"{'VERTICAL':<14}{'REGION':<10}{'FEEDS':>6}")
    total = 0
    for v in SOURCES:
        for r, feeds in SOURCES[v].items():
            print(f"{v:<14}{r:<10}{len(feeds):>6}")
            total += len(feeds)
    print(f"{'-'*30}\n{'TOTAL':<24}{total:>6} feeds")
