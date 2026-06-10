"""
check_feeds.py — probe every feed in the catalog and report which are live.

    python check_feeds.py                 # all feeds
    python check_feeds.py politics finance # only these verticals

Needs network. Feed URLs drift; run this occasionally and prune dead ones from
sources.py. The pipeline itself tolerates dead feeds (skips + logs), so this is
hygiene, not a hard requirement.
"""

import sys

from pipeline.monitor import NewsMonitor
from sources import feeds_for

STATUS_MARK = {"ok": "OK  ", "empty": "EMPTY", "error": "DEAD"}


def main() -> None:
    verticals = sys.argv[1:] or None
    feeds = feeds_for(verticals)
    report = NewsMonitor(rss_feeds=feeds).health_check()

    ok = sum(1 for r in report if r["status"] == "ok")
    print(f"\nProbed {len(report)} feeds — {ok} live\n")
    print(f"{'STATUS':<6}{'ENTRIES':>8}  {'VERTICAL':<14}{'REGION':<8}NAME")
    print("-" * 72)
    for r in sorted(report, key=lambda x: (x["vertical"] or "", x["region"] or "", x["name"] or "")):
        mark = STATUS_MARK.get(r["status"], r["status"])
        print(f"{mark:<6}{r['entries']:>8}  {r['vertical'] or '-':<14}"
              f"{r['region'] or '-':<8}{r['name'] or r['url']}")

    dead = [r for r in report if r["status"] != "ok"]
    if dead:
        print(f"\n{len(dead)} feed(s) not returning entries — consider pruning from sources.py:")
        for r in dead:
            print(f"  [{r['status']}] {r['name']}: {r['url']}")


if __name__ == "__main__":
    main()
