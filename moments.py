"""
moments.py — the marketing moments calendar (the PROACTIVE layer).

Everything else in the watch stack is reactive: news breaks, we score it. But
a big brand's content calendar is 60-80% PLANNED — moments marketing around
awareness days, holidays, shopping events, and sport seasons. A Nike-level
team knows Father's Day is coming three weeks out; until this module, Pulse
had no way to say so.

Each moment carries a date RULE (not a date), so the calendar is evergreen:

    ("fixed", month, day)                 e.g. Earth Day = Apr 22
    ("nth_weekday", month, weekday, n)    e.g. Mother's Day = 2nd Sunday of May
    ("last_weekday", month, weekday)      e.g. Earth Hour = last Saturday of March
    ("offset", inner_rule, days)          e.g. Black Friday = Thanksgiving + 1
    ("lookup", {year: (month, day)})      lunar/announced dates, per-year table

Weekday convention follows Python's date.weekday(): Monday=0 .. Sunday=6.

HONESTY NOTE on ("lookup", ...): lunar-calendar festivals (Diwali, Holi, Eid,
Raksha Bandhan) and announced events (IPL, Prime Day, fashion weeks) cannot be
computed; the tables below are best-effort for 2026-2028 and regional
observance can differ by a day. They surface 2-3 weeks ahead for PLANNING, so
±1 day is harmless — but verify the exact date before a date-specific post,
and extend/correct the tables yearly (they are data, not code). A year missing
from a lookup table simply resolves to None and is skipped — never guessed.

Entry fields:
    slug      stable id (also the dedup key per occurrence)
    name      display name
    kind      awareness | holiday | shopping | sport | culture | finance
    vertical  primary catalog vertical, or None = universal (every account
              sees it — NULL-vertical articles bypass vertical scoping)
    region    "india" | "us" | None = global/everyone
    lead_days how far ahead to surface it (planning window)
    blurb     one-line angle hint passed to the decision agent
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

# --------------------------------------------------------------------------- #
# Date rule engine
# --------------------------------------------------------------------------- #
def resolve(rule: tuple, year: int) -> Optional[date]:
    """Resolve a date rule for a given year. None = unknown for that year."""
    kind = rule[0]
    if kind == "fixed":
        _, month, day = rule
        return date(year, month, day)
    if kind == "nth_weekday":
        _, month, weekday, n = rule
        first = date(year, month, 1)
        delta = (weekday - first.weekday()) % 7
        d = first + timedelta(days=delta + 7 * (n - 1))
        return d if d.month == month else None
    if kind == "last_weekday":
        _, month, weekday = rule
        nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        last = nxt - timedelta(days=1)
        return last - timedelta(days=(last.weekday() - weekday) % 7)
    if kind == "offset":
        _, inner, days = rule
        base = resolve(inner, year)
        return base + timedelta(days=days) if base else None
    if kind == "lookup":
        md = rule[1].get(year)
        return date(year, *md) if md else None
    raise ValueError(f"Unknown rule kind: {kind!r}")


# --------------------------------------------------------------------------- #
# The calendar (data — edit freely, especially the lookup tables, yearly)
# --------------------------------------------------------------------------- #
_THANKSGIVING = ("nth_weekday", 11, 3, 4)          # 4th Thursday of November
_DIWALI = ("lookup", {2026: (11, 8), 2027: (10, 29), 2028: (10, 17)})

MOMENTS: list[dict] = [
    # ------------------------------------------------ global awareness days
    dict(slug="new-years-day", name="New Year's Day", kind="holiday",
         vertical=None, region=None, lead_days=14, rule=("fixed", 1, 1),
         blurb="Fresh starts, resolutions, year-ahead positioning."),
    dict(slug="valentines-day", name="Valentine's Day", kind="holiday",
         vertical=None, region=None, lead_days=18, rule=("fixed", 2, 14),
         blurb="Love/gifting angle — also strong anti-cliché counter-takes."),
    dict(slug="international-womens-day", name="International Women's Day",
         kind="awareness", vertical=None, region=None, lead_days=18,
         rule=("fixed", 3, 8),
         blurb="Substance over tokenism — real stories beat purple logos."),
    dict(slug="international-day-of-happiness", name="International Day of Happiness",
         kind="awareness", vertical=None, region=None, lead_days=10,
         rule=("fixed", 3, 20), blurb="Light, positive, community-prompt friendly."),
    dict(slug="world-water-day", name="World Water Day", kind="awareness",
         vertical=None, region=None, lead_days=10, rule=("fixed", 3, 22),
         blurb="Sustainability angle; credible only with a real practice to show."),
    dict(slug="april-fools", name="April Fools' Day", kind="culture",
         vertical=None, region=None, lead_days=18, rule=("fixed", 4, 1),
         blurb="The brand-stunt holiday — fake product reveals, playful trolling."),
    dict(slug="world-health-day", name="World Health Day", kind="awareness",
         vertical="wellness", region=None, lead_days=10, rule=("fixed", 4, 7),
         blurb="Health-first positioning; myth-busting formats work."),
    dict(slug="earth-day", name="Earth Day", kind="awareness",
         vertical=None, region=None, lead_days=18, rule=("fixed", 4, 22),
         blurb="Sustainability receipts or silence — greenwashing gets ratioed."),
    dict(slug="star-wars-day", name="Star Wars Day (May the 4th)", kind="culture",
         vertical=None, region="us", lead_days=10, rule=("fixed", 5, 4),
         blurb="Pun-driven pop-culture day; low effort, high share rate."),
    dict(slug="cinco-de-mayo", name="Cinco de Mayo", kind="holiday",
         vertical="lifestyle", region="us", lead_days=10, rule=("fixed", 5, 5),
         blurb="Food/festivity angle for US consumer brands."),
    dict(slug="mental-health-awareness-month", name="Mental Health Awareness Month (kickoff)",
         kind="awareness", vertical="wellness", region="us", lead_days=14,
         rule=("fixed", 5, 1),
         blurb="A month-long arc — plan a series, not a single post."),
    dict(slug="pride-month", name="Pride Month (kickoff)", kind="awareness",
         vertical=None, region=None, lead_days=18, rule=("fixed", 6, 1),
         blurb="Month-long arc; participation needs year-round credibility."),
    dict(slug="world-bicycle-day", name="World Bicycle Day", kind="awareness",
         vertical="sports", region=None, lead_days=7, rule=("fixed", 6, 3),
         blurb="Movement/commute/sustainability crossover."),
    dict(slug="world-environment-day", name="World Environment Day", kind="awareness",
         vertical=None, region=None, lead_days=12, rule=("fixed", 6, 5),
         blurb="Bigger than Earth Day in India; show practice, not platitude."),
    dict(slug="international-yoga-day", name="International Day of Yoga",
         kind="awareness", vertical="wellness", region=None, lead_days=14,
         rule=("fixed", 6, 21), blurb="Huge in India; wellness/movement brands own it."),
    dict(slug="world-music-day", name="World Music Day", kind="culture",
         vertical="entertainment", region=None, lead_days=7, rule=("fixed", 6, 21),
         blurb="Soundtrack-your-brand angle; playlists, artist collabs."),
    dict(slug="world-social-media-day", name="World Social Media Day", kind="awareness",
         vertical="marketing", region=None, lead_days=10, rule=("fixed", 6, 30),
         blurb="Meta-content day — behind-the-scenes of the brand's own social."),
    dict(slug="world-chocolate-day", name="World Chocolate Day", kind="culture",
         vertical="lifestyle", region=None, lead_days=7, rule=("fixed", 7, 7),
         blurb="Indulgence angle; food/treat brands and playful B2B alike."),
    dict(slug="world-emoji-day", name="World Emoji Day", kind="culture",
         vertical=None, region=None, lead_days=7, rule=("fixed", 7, 17),
         blurb="Tell-your-story-in-emoji formats; reliably high engagement."),
    dict(slug="international-self-care-day", name="International Self-Care Day",
         kind="awareness", vertical="wellness", region=None, lead_days=7,
         rule=("fixed", 7, 24), blurb="Routine/ritual content; UGC prompts."),
    dict(slug="international-friendship-day", name="International Friendship Day",
         kind="awareness", vertical=None, region=None, lead_days=7,
         rule=("fixed", 7, 30), blurb="Tag-a-friend mechanics, duo content."),
    dict(slug="world-photography-day", name="World Photography Day", kind="culture",
         vertical=None, region=None, lead_days=7, rule=("fixed", 8, 19),
         blurb="Visual-first day — archives, community photo prompts."),
    dict(slug="international-dog-day", name="International Dog Day", kind="culture",
         vertical="lifestyle", region=None, lead_days=7, rule=("fixed", 8, 26),
         blurb="Office dogs, pet UGC — the internet's easiest win."),
    dict(slug="programmers-day", name="Programmers' Day", kind="culture",
         vertical="tech", region=None, lead_days=7, rule=("fixed", 9, 13),
         blurb="Dev-humour day for tech/SaaS brands; ship a nerdy easter egg."),
    dict(slug="world-tourism-day", name="World Tourism Day", kind="awareness",
         vertical="lifestyle", region=None, lead_days=10, rule=("fixed", 9, 27),
         blurb="Travel/experience angle; local-gems content."),
    dict(slug="international-podcast-day", name="International Podcast Day",
         kind="awareness", vertical="marketing", region=None, lead_days=7,
         rule=("fixed", 9, 30), blurb="Repurpose audio content; founder-voice angle."),
    dict(slug="international-coffee-day", name="International Coffee Day",
         kind="culture", vertical="lifestyle", region=None, lead_days=7,
         rule=("fixed", 10, 1), blurb="Fuel-of-work angle; café collabs, morning rituals."),
    dict(slug="world-mental-health-day", name="World Mental Health Day",
         kind="awareness", vertical="wellness", region=None, lead_days=14,
         rule=("fixed", 10, 10), blurb="Handle with care — substance and resources, not slogans."),
    dict(slug="world-food-day", name="World Food Day", kind="awareness",
         vertical="lifestyle", region=None, lead_days=10, rule=("fixed", 10, 16),
         blurb="Food security/zero-waste angle for food & retail brands."),
    dict(slug="halloween", name="Halloween", kind="holiday",
         vertical=None, region="us", lead_days=21, rule=("fixed", 10, 31),
         blurb="Costume/spooky creative; product-in-disguise formats."),
    dict(slug="world-vegan-day", name="World Vegan Day", kind="awareness",
         vertical="wellness", region=None, lead_days=10, rule=("fixed", 11, 1),
         blurb="Plant-based angle; recipe/ingredient swaps."),
    dict(slug="world-kindness-day", name="World Kindness Day", kind="awareness",
         vertical=None, region=None, lead_days=7, rule=("fixed", 11, 13),
         blurb="Acts-of-kindness mechanics; community spotlights."),
    dict(slug="international-mens-day", name="International Men's Day",
         kind="awareness", vertical=None, region=None, lead_days=10,
         rule=("fixed", 11, 19), blurb="Men's health/mental-health framing lands best."),
    dict(slug="christmas-eve", name="Christmas Eve", kind="holiday",
         vertical=None, region=None, lead_days=10, rule=("fixed", 12, 24),
         blurb="Last-minute gifting; warmth over selling."),
    dict(slug="christmas", name="Christmas Day", kind="holiday",
         vertical=None, region=None, lead_days=28, rule=("fixed", 12, 25),
         blurb="The season is the campaign — plan the arc, not one post."),
    dict(slug="boxing-day", name="Boxing Day", kind="shopping",
         vertical="business", region=None, lead_days=10, rule=("fixed", 12, 26),
         blurb="Post-Christmas sales; clearance creative."),
    dict(slug="new-years-eve", name="New Year's Eve", kind="holiday",
         vertical=None, region=None, lead_days=14, rule=("fixed", 12, 31),
         blurb="Year-in-review formats; brand wrapped/recap content."),

    # --------------------------------------------------------- india moments
    dict(slug="republic-day-india", name="Republic Day", kind="holiday",
         vertical=None, region="india", lead_days=14, rule=("fixed", 1, 26),
         blurb="National pride; tricolour creative everywhere — differentiate."),
    dict(slug="budget-day-india", name="Union Budget Day", kind="finance",
         vertical="finance", region="india", lead_days=14, rule=("fixed", 2, 1),
         blurb="Explainers and instant reactions; B2B/finance brands' Super Bowl."),
    dict(slug="independence-day-india", name="Independence Day (India)", kind="holiday",
         vertical=None, region="india", lead_days=18, rule=("fixed", 8, 15),
         blurb="Freedom-themed storytelling; made-in-India angle."),
    dict(slug="teachers-day-india", name="Teachers' Day (India)", kind="awareness",
         vertical=None, region="india", lead_days=10, rule=("fixed", 9, 5),
         blurb="Mentor-gratitude content; education brands peak."),
    dict(slug="gandhi-jayanti", name="Gandhi Jayanti", kind="holiday",
         vertical=None, region="india", lead_days=10, rule=("fixed", 10, 2),
         blurb="Simplicity/sustainability values angle."),
    dict(slug="childrens-day-india", name="Children's Day (India)", kind="holiday",
         vertical=None, region="india", lead_days=10, rule=("fixed", 11, 14),
         blurb="Nostalgia formats — 'the kid in you' angle works for any brand."),
    dict(slug="itr-deadline-india", name="ITR Filing Deadline (India)", kind="finance",
         vertical="finance", region="india", lead_days=21, rule=("fixed", 7, 31),
         blurb="Deadline-panic content; fintech reminder/explainer peak."),
    dict(slug="friendship-day-india", name="Friendship Day (India)", kind="holiday",
         vertical=None, region="india", lead_days=10,
         rule=("nth_weekday", 8, 6, 1),
         blurb="India's bigger friendship moment (first Sunday of August)."),
    dict(slug="holi", name="Holi", kind="holiday",
         vertical=None, region="india", lead_days=18,
         rule=("lookup", {2026: (3, 4), 2027: (3, 22), 2028: (3, 11)}),
         blurb="Colour-splash creative; the most visual Indian festival."),
    dict(slug="eid-al-fitr", name="Eid al-Fitr", kind="holiday",
         vertical=None, region="india", lead_days=14,
         rule=("lookup", {2026: (3, 20), 2027: (3, 10), 2028: (2, 27)}),
         blurb="Festive generosity/togetherness; food & gifting angle."),
    dict(slug="ramadan-start", name="Ramadan begins", kind="holiday",
         vertical=None, region=None, lead_days=14,
         rule=("lookup", {2026: (2, 18), 2027: (2, 8), 2028: (1, 28)}),
         blurb="Month-long arc — iftar timing, community, restraint in tone."),
    dict(slug="raksha-bandhan", name="Raksha Bandhan", kind="holiday",
         vertical=None, region="india", lead_days=18,
         rule=("lookup", {2026: (8, 28), 2027: (8, 17), 2028: (8, 5)}),
         blurb="Sibling gifting peak; e-commerce's mid-year Diwali."),
    dict(slug="diwali", name="Diwali", kind="holiday",
         vertical=None, region="india", lead_days=28, rule=_DIWALI,
         blurb="India's biggest brand moment of the year — plan a full campaign arc."),
    dict(slug="dhanteras", name="Dhanteras", kind="shopping",
         vertical="business", region="india", lead_days=14,
         rule=("offset", _DIWALI, -2),
         blurb="The buying day — gold/big-ticket purchases; offers go live now."),

    # ------------------------------------------------------------ us moments
    dict(slug="st-patricks-day", name="St. Patrick's Day", kind="holiday",
         vertical="lifestyle", region="us", lead_days=10, rule=("fixed", 3, 17),
         blurb="Green-everything creative; F&B brands peak."),
    dict(slug="pi-day", name="Pi Day", kind="culture",
         vertical="tech", region="us", lead_days=7, rule=("fixed", 3, 14),
         blurb="Nerd-humour day; 3.14 promo mechanics."),
    dict(slug="national-pet-day", name="National Pet Day", kind="culture",
         vertical="lifestyle", region="us", lead_days=7, rule=("fixed", 4, 11),
         blurb="Pet UGC; guaranteed-soft engagement."),
    dict(slug="tax-day-us", name="Tax Day (US)", kind="finance",
         vertical="finance", region="us", lead_days=18, rule=("fixed", 4, 15),
         blurb="Deadline content; relief-treat promos after."),
    dict(slug="national-pizza-day", name="National Pizza Day", kind="culture",
         vertical="lifestyle", region="us", lead_days=7, rule=("fixed", 2, 9),
         blurb="Food-holiday fun; team-pineapple debates print engagement."),
    dict(slug="international-burger-day", name="International Burger Day",
         kind="culture", vertical="lifestyle", region=None, lead_days=7,
         rule=("fixed", 5, 28), blurb="F&B peak; build-your-own UGC prompts."),
    dict(slug="independence-day-us", name="Independence Day (US)", kind="holiday",
         vertical=None, region="us", lead_days=14, rule=("fixed", 7, 4),
         blurb="Summer/grilling/Americana; sale season."),
    dict(slug="back-to-school-us", name="Back-to-school season (US)", kind="shopping",
         vertical="lifestyle", region="us", lead_days=21, rule=("fixed", 8, 1),
         blurb="A 6-week shopping arc, not a day — gear, routines, fresh starts."),
    dict(slug="thanksgiving-us", name="Thanksgiving", kind="holiday",
         vertical=None, region="us", lead_days=21, rule=_THANKSGIVING,
         blurb="Gratitude content; the calm before the retail storm."),
    dict(slug="black-friday", name="Black Friday", kind="shopping",
         vertical="business", region=None, lead_days=28,
         rule=("offset", _THANKSGIVING, 1),
         blurb="The retail super-moment — offer strategy locks weeks ahead."),
    dict(slug="small-business-saturday", name="Small Business Saturday", kind="shopping",
         vertical="business", region="us", lead_days=14,
         rule=("offset", _THANKSGIVING, 2),
         blurb="Shop-local angle; the counter-narrative to Black Friday."),
    dict(slug="cyber-monday", name="Cyber Monday", kind="shopping",
         vertical="business", region=None, lead_days=21,
         rule=("offset", _THANKSGIVING, 4),
         blurb="Online-deals peak; e-commerce's biggest single day."),
    dict(slug="giving-tuesday", name="Giving Tuesday", kind="awareness",
         vertical=None, region=None, lead_days=14,
         rule=("offset", _THANKSGIVING, 5),
         blurb="Purpose reset after the sales blitz; donate/match mechanics."),
    dict(slug="singles-day", name="Singles' Day (11.11)", kind="shopping",
         vertical="business", region=None, lead_days=18, rule=("fixed", 11, 11),
         blurb="The world's biggest shopping day; self-gifting angle."),

    # --------------------------------------------------- family / rule-based
    dict(slug="mothers-day", name="Mother's Day", kind="holiday",
         vertical=None, region=None, lead_days=21,
         rule=("nth_weekday", 5, 6, 2),
         blurb="Top-3 gifting moment; emotional storytelling outperforms promo."),
    dict(slug="fathers-day", name="Father's Day", kind="holiday",
         vertical=None, region=None, lead_days=21,
         rule=("nth_weekday", 6, 6, 3),
         blurb="Gifting + dad-humour; underserved vs Mother's Day = opportunity."),
    dict(slug="met-gala", name="Met Gala", kind="culture",
         vertical="lifestyle", region="us", lead_days=10,
         rule=("nth_weekday", 5, 0, 1),
         blurb="Fashion's biggest night — real-time reaction content wins."),
    dict(slug="global-running-day", name="Global Running Day", kind="sport",
         vertical="sports", region=None, lead_days=10,
         rule=("nth_weekday", 6, 2, 1),
         blurb="Community-run mechanics; athletic brands' owned moment."),
    dict(slug="international-beer-day", name="International Beer Day", kind="culture",
         vertical="lifestyle", region=None, lead_days=7,
         rule=("nth_weekday", 8, 4, 1),
         blurb="Cheers-content; F&B and after-work-culture brands."),
    dict(slug="world-smile-day", name="World Smile Day", kind="awareness",
         vertical=None, region=None, lead_days=7,
         rule=("nth_weekday", 10, 4, 1),
         blurb="Feel-good filler with honest engagement mechanics."),
    dict(slug="earth-hour", name="Earth Hour", kind="awareness",
         vertical=None, region=None, lead_days=10,
         rule=("last_weekday", 3, 5),
         blurb="Lights-off moment — dark-mode creative, energy angle."),
    dict(slug="global-wellness-day", name="Global Wellness Day", kind="awareness",
         vertical="wellness", region=None, lead_days=10,
         rule=("nth_weekday", 6, 5, 2),
         blurb="Wellness brands' flagship day; routines and resets."),
    dict(slug="world-sleep-day", name="World Sleep Day (approx.)", kind="awareness",
         vertical="wellness", region=None, lead_days=10, rule=("fixed", 3, 13),
         blurb="Rest/recovery angle; date shifts slightly yearly — verify."),

    # ------------------------------------------------------------------ sport
    dict(slug="super-bowl", name="Super Bowl Sunday", kind="sport",
         vertical="sports", region="us", lead_days=28,
         rule=("nth_weekday", 2, 6, 1),
         blurb="Advertising's biggest stage — second-screen reaction content."),
    dict(slug="boston-marathon", name="Boston Marathon", kind="sport",
         vertical="sports", region="us", lead_days=14,
         rule=("nth_weekday", 4, 0, 3),
         blurb="Endurance storytelling; athletic brands' spring peak."),
    dict(slug="nyc-marathon", name="NYC Marathon", kind="sport",
         vertical="sports", region="us", lead_days=14,
         rule=("nth_weekday", 11, 6, 1),
         blurb="The people's race — runner-story content."),
    dict(slug="nfl-kickoff", name="NFL season kickoff (approx.)", kind="sport",
         vertical="sports", region="us", lead_days=14, rule=("fixed", 9, 5),
         blurb="Season-opener energy; exact date announced yearly — verify."),
    dict(slug="ipl-season", name="IPL season start (approx.)", kind="sport",
         vertical="sports", region="india", lead_days=21,
         rule=("lookup", {2026: (3, 26)}),
         blurb="India's 2-month attention monopoly — plan around match nights."),
    dict(slug="fifa-world-cup", name="FIFA World Cup kickoff", kind="sport",
         vertical="sports", region=None, lead_days=30,
         rule=("lookup", {2026: (6, 11)}),
         blurb="The global mega-moment; month-long content arc."),
    dict(slug="winter-olympics", name="Winter Olympics opening", kind="sport",
         vertical="sports", region=None, lead_days=21,
         rule=("lookup", {2026: (2, 6)}),
         blurb="Underdog/excellence storytelling; global audience."),
    dict(slug="summer-olympics", name="Summer Olympics opening", kind="sport",
         vertical="sports", region=None, lead_days=30,
         rule=("lookup", {2028: (7, 14)}),
         blurb="The biggest sports-marketing window of the cycle."),

    # ---------------------------------------------------- shopping / culture
    dict(slug="amazon-prime-day", name="Amazon Prime Day (approx.)", kind="shopping",
         vertical="business", region="us", lead_days=14, rule=("fixed", 7, 8),
         blurb="Mid-year deals spike; date announced ~June — verify."),
    dict(slug="flipkart-bbd", name="Flipkart Big Billion Days (approx.)",
         kind="shopping", vertical="business", region="india", lead_days=14,
         rule=("fixed", 9, 25),
         blurb="India's festive-sale opener; date announced ~Sept — verify."),
    dict(slug="nyfw-feb", name="New York Fashion Week — Feb (approx.)",
         kind="culture", vertical="lifestyle", region="us", lead_days=14,
         rule=("fixed", 2, 9),
         blurb="Trend-spotting week; style commentary peaks — verify dates."),
    dict(slug="nyfw-sep", name="New York Fashion Week — Sep (approx.)",
         kind="culture", vertical="lifestyle", region="us", lead_days=14,
         rule=("fixed", 9, 10),
         blurb="The bigger NYFW; fall collections — verify dates."),
    dict(slug="coachella", name="Coachella (approx.)", kind="culture",
         vertical="entertainment", region="us", lead_days=14,
         rule=("fixed", 4, 10),
         blurb="Festival-season opener; youth-culture aesthetics — verify dates."),
    dict(slug="easter", name="Easter Sunday", kind="holiday",
         vertical=None, region=None, lead_days=18,
         rule=("lookup", {2026: (4, 5), 2027: (3, 28), 2028: (4, 16)}),
         blurb="Spring/renewal creative; egg-hunt mechanics."),
    dict(slug="chinese-new-year", name="Chinese New Year", kind="holiday",
         vertical=None, region=None, lead_days=18,
         rule=("lookup", {2026: (2, 17), 2027: (2, 6), 2028: (1, 26)}),
         blurb="Zodiac-themed creative; massive APAC commerce moment."),
]


def upcoming(today: date, horizon_days: Optional[int] = None) -> list[dict]:
    """Moments whose planning window is open: 0 <= days_out <= lead_days
    (or <= horizon_days when given). Checks this year and next so a December
    run still sees January moments. Returns [{**moment, "date", "days_out"}]
    sorted soonest-first."""
    out = []
    for m in MOMENTS:
        for year in (today.year, today.year + 1):
            d = resolve(m["rule"], year)
            if not d:
                continue
            days_out = (d - today).days
            window = horizon_days if horizon_days is not None else m["lead_days"]
            if 0 <= days_out <= window:
                out.append({**m, "date": d, "days_out": days_out})
                break  # one occurrence per moment
    return sorted(out, key=lambda m: m["days_out"])


if __name__ == "__main__":
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date()
    print(f"{len(MOMENTS)} moments in the calendar. In window today ({today}):\n")
    for m in upcoming(today):
        print(f"  {m['date']}  ({m['days_out']:>2}d)  {m['name']}  [{m['kind']}]")
