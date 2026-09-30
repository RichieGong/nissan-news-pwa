"""
fetch_news.py — the backend, version 3.

What changed vs v2, and why:
  v2 merged every result from 200 searches and kept the newest 60. Because
  financial outlets publish stock-ticker stories constantly, those crowded
  out the actual automotive news. v3 adds a RELEVANCE filter, so a headline
  only survives if it talks about vehicles, supply chains, or trade policy.

How it works:
  Google News search supports a source filter, exactly like typing
  "auto tariff" source:"Reuters" into Google News yourself. We run one
  search per (topic phrase, outlet) pair and combine the results.

How to run:
  python fetch_news.py     (then refresh index.html in your browser)

Paywalls:
  This script only collects headlines, dates, and links — that part is free.
  It never fetches full article text. NYT, WSJ, WP, Economist, Bloomberg and
  FT keep their articles behind paywalls; this app links out to each story
  and lets the company decide how to read it.
"""

import html
import json
import re
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

# ---- Approved outlets (as Google News knows their names) --------------------
# Names that return zero results are reported at the end so we can fix them.
SOURCES = [
    "Reuters", "Associated Press", "BBC", "NPR",
    "The New York Times", "The Wall Street Journal", "The Washington Post",
    "The Economist", "Bloomberg", "The Christian Science Monitor",
    "Automotive News", "WardsAuto", "Motor1", "Car and Driver",
    "InsideEVs", "Green Car Reports", "CNBC", "Yahoo Finance",
    "Investopedia", "MarketWatch", "Financial Times",
    "FreightWaves", "The Loadstar", "Journal of Commerce", "Supply Chain 24/7",
]

# ---- Search phrases per app tag (built from the company's keyword list) -----
TAG_PHRASES = {
    "Tariffs":   ["auto tariff", "car import duty"],
    "Trade":     ["auto exports imports", "auto trade market"],
    "Parts":     ["auto parts supply chain", "auto parts shortage inventory"],
    "EV & Tech": ["EV battery tariff", "AI automotive industry"],
}

# ---- Relevance filter (this is what v2 was missing) -------------------------
# A headline must contain at least one CORE term to be kept. CORE terms are
# unmistakably about vehicles, parts, or trade policy. Without this, results
# from CNBC/MarketWatch fill the feed with unrelated stock-market news.
#
# These are matched on WORD boundaries, not as loose substrings. Plain
# substring matching produced false hits: "ford" matched inside "Fairford"
# (an RAF base), and "ice" inside "choice".
CORE_TERMS = [
    # vehicles & makers
    "automaker", "automakers", "automotive", "auto industry", "auto sector",
    "auto market", "vehicle", "vehicles", "car", "cars", "carmaker",
    "suv", "truck", "trucks", "pickup", "sedan", "crossover", "carmakers",
    "nissan", "toyota", "honda", "ford", "tesla", "bmw", "mercedes",
    "volkswagen", "audi", "hyundai", "kia", "mazda", "subaru", "stellantis",
    "rivian", "polestar", "general motors", "lamborghini", "porsche", "jaguar",
    # electrification
    "ev", "evs", "electric vehicle", "electric vehicles", "electric car",
    "battery", "batteries", "bev", "phev", "charger", "charging",
    # parts, supply chain, production
    "supply chain", "supplier", "suppliers", "auto parts", "car parts",
    "component", "components", "semiconductor", "semiconductors", "chip",
    "chips", "shortage", "inventory", "freight", "shipping", "container",
    "logistics", "tier 1", "recall", "recalls", "plant", "factory",
    "assembly", "production", "manufacturing", "dealership", "dealerships",
    "oem", "aftermarket", "microchip", "foundry",
    # trade policy
    "tariff", "tariffs", "duty", "duties", "import", "imports", "export",
    "exports", "trade", "trade deal", "sanction", "sanctions", "quota",
    "usmca", "section 232", "subsidy", "subsidies", "trade war", "customs",
]

# A single weak hit (say, "cars" in a general inflation story) is not enough
# on its own. A headline qualifies if it has 2+ core terms, or at least one
# of these unmistakable ones.
STRONG_TERMS = [
    "nissan", "toyota", "honda", "ford", "tesla", "bmw", "mercedes",
    "volkswagen", "audi", "hyundai", "kia", "mazda", "subaru", "stellantis",
    "rivian", "polestar", "general motors",
    "automaker", "automakers", "automotive", "auto industry", "auto sector",
    "auto parts", "car parts", "carmaker", "carmakers", "usmca", "section 232",
    "tariff", "tariffs", "trade war", "supply chain", "semiconductor",
    "semiconductors", "battery", "batteries", "electric vehicle",
    "electric vehicles", "evs", "assembly plant", "oem",
    # multi-word trade-policy phrases. A story can be squarely about trade
    # policy without naming a brand — e.g. "UK tries to stop Trump's diesel
    # export ban" mentions no automaker but matters just as much.
    "export ban", "import ban", "trade deal", "free trade", "diesel ban",
    "fuel economy", "emissions rule", "emissions rules", "diesel",
]

# Secondary terms: never qualify a story on their own, but they raise the
# score so that, for equal relevance, the more informative one ranks first.
SECONDARY_TERMS = [
    "layoff", "layoffs", "bankruptcy", "cost", "costs", "price", "prices",
    "pricing", "profit", "margin", "market", "demand", "supply", "crisis",
    "opportunity", "trend", "trends", "forecast", "earnings", "strike",
    "union", "labor", "uaw", "policy", "regulation", "regulator", "ban",
    "barrier", "deal", "deals", "output", "inflation", "jobs", "investment",
    "production", "plant", "factory", "recession", "growth", "warning",
]

MAX_PER_TAG = 25   # keeps one loud topic from eating the whole feed

# Only pull the last month. NOTE: Google News accepts '1h','1d','7d','14d',
# '30d','1y' — it does NOT understand '1m' or '3m', and it fails silently by
# returning an empty feed rather than an error. Use days, never months.
RECENT_DAYS = "30d"

# ---- Rate limiting ----------------------------------------------------------
# Google starts returning HTTP 503 if you ask for too much too fast, and it
# does NOT always recover on its own. We crawl politely in small batches with
# a pause between them, and retry anything that fails.
BATCH_SIZE = 4          # requests in flight at once
BATCH_PAUSE = 1.5       # seconds to wait between batches
MAX_RETRIES = 3         # retries per failed request

# ---- Helpers ----------------------------------------------------------------


def local_tag(tag):
    """Strip XML namespaces (e.g. '{http://...}item' -> 'item')."""
    return tag.split("}")[-1]


def strip_html(raw):
    """Google's description is HTML, not text. Reduce it to readable text."""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def clean_title(raw):
    """Google News appends the outlet to the title: 'Headline - Reuters'."""
    raw = strip_html(raw)
    for sep in (" - ", " — ", " – "):
        if sep in raw:
            return raw.rsplit(sep, 1)[0].strip()
    return raw.strip()


def term_hits(title, terms):
    """Count terms present in the title, matching on WORD boundaries.

    Word boundaries matter: a naive substring test makes "ford" match inside
    "Fairford" and "ice" inside "choice", which drags in stories about RAF
    bases and marketing polls.
    """
    hits = 0
    for t in terms:
        if re.search(rf"\b{re.escape(t)}\b", title):
            hits += 1
    return hits


def score(title):
    """Return a relevance score. 0 means 'not relevant, drop it'."""
    t = title.lower()
    core = term_hits(t, CORE_TERMS)
    if not core:
        return 0
    strong = term_hits(t, STRONG_TERMS)
    # One weak hit alone ("cars" in a story about eggs and rent) isn't enough.
    if not strong and core < 2:
        return 0
    secondary = term_hits(t, SECONDARY_TERMS)
    # Core hits matter most, but cap them so one keyword-stuffed headline
    # can't outrank a genuinely informative one.
    return min(core, 4) * 2 + min(secondary, 3)


def fetch_rss(phrase, source):
    """Fetch one feed, retrying if Google is rate-limiting us (HTTP 503)."""
    q = f'{phrase} source:"{source}" when:{RECENT_DAYS}'
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({
        "q": q, "hl": "en-US", "gl": "US", "ceid": "US:en",
    })
    last = None
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as resp:
                return resp.read()
        except Exception as e:
            last = e
            time.sleep(4 * (attempt + 1))  # back off: 4s, 8s, 12s
    raise last


def canonical_source(name):
    """Map the outlet name Google returns back to the company's approved list.

    Google's `source:` filter is fuzzy — searching source:"Automotive News"
    can return CarBuzz or AgroLatam instead. We only keep a story if the
    outlet Google actually credits is on the approved list.
    """
    if not name:
        return None
    n = name.strip().lower()
    # Google often returns a domain-ish form: "Motor1.com", "bloomberg.com"
    n = re.sub(r"^www\.", "", n)
    bare = re.sub(r"\.(com|co\.uk|org|net|co\.nz)$", "", n)
    for approved in SOURCES:
        a = approved.lower()
        if n == a or bare == a:
            return approved
        # e.g. approved "Motor1" vs returned "motor1.com"
        if bare.replace(" ", "") == a.replace(" ", ""):
            return approved
    return None


def parse_feed(feed_xml, tag, phrase):
    root = ET.fromstring(feed_xml)
    items = []
    for elem in root.iter():
        if local_tag(elem.tag) != "item":
            continue
        title = clean_title(elem.findtext("title", ""))
        if not title:
            continue

        rank = score(title)
        if rank == 0:
            continue  # off-topic for this app

        link = elem.findtext("link", "")
        time_raw = elem.findtext("pubDate", "")
        try:
            dt = parsedate_to_datetime(time_raw)
        except Exception:
            continue  # skip items with unreadable dates

        outlet = canonical_source(elem.findtext("source"))
        if outlet is None:
            continue  # not actually one of the company's approved outlets

        items.append({
            "time": dt.isoformat(),
            "source": outlet,
            "tag": tag,
            "title": title,
            "url": link,
            "score": rank,
            "phrase": phrase,
        })
    return items


def stable_id(text):
    """Same headline always gets the same id (unlike Python's hash())."""
    import hashlib
    return int(hashlib.md5(text.encode("utf-8")).hexdigest()[:8], 16)


def main():
    pairs = [
        (tag, phrase, source)
        for tag, phrases in TAG_PHRASES.items()
        for phrase in phrases
        for source in SOURCES
    ]

    seen, stories = set(), []
    from_source, failed = {}, []

    def work(item):
        i, (tag, phrase, source) = item
        try:
            raw = fetch_rss(phrase, source)
        except Exception as e:
            return i, tag, phrase, source, None, f"search failed: {e}"
        return i, tag, phrase, source, parse_feed(raw, tag, phrase), None

    # Crawl in small batches with a pause between them. Hammering all 200
    # searches at once makes Google return HTTP 503 and silently drop whole
    # topics (this is exactly what emptied the "Tariffs" tag once).
    for start in range(0, len(pairs), BATCH_SIZE):
        batch = list(enumerate(pairs, 1))[start:start + BATCH_SIZE]
        results = [work(item) for item in batch]

        for i, tag, phrase, source, items, err in results:
            if err:
                failed.append(source)
                print(f"  [{i}/{len(pairs)}] {source} · \"{phrase}\" -> {err}")
                continue
            kept = 0
            for s in items:
                key = s["title"].lower()
                if key in seen:   # same headline may match several searches
                    continue
                seen.add(key)
                stories.append(s)
                from_source[source] = from_source.get(source, 0) + 1
                kept += 1
            print(f"  [{i}/{len(pairs)}] {source} · \"{phrase}\" -> "
                  f"{kept} on-topic ({len(stories)} total)")

        if start + BATCH_SIZE < len(pairs):
            time.sleep(BATCH_PAUSE)

    # Balance the feed: keep the best MAX_PER_TAG from each tag.
    by_tag = {}
    for s in stories:
        by_tag.setdefault(s["tag"], []).append(s)

    final = []
    for tag, group in by_tag.items():
        # newest first within a tag, relevance breaks ties
        group.sort(key=lambda s: (s["time"], s["score"]), reverse=True)
        final.extend(group[:MAX_PER_TAG])

    # Overall order: newest first across the whole feed.
    final.sort(key=lambda s: s["time"], reverse=True)

    for s in final:
        s["id"] = stable_id(s["title"])
        s.pop("score", None)
        s.pop("phrase", None)

    out = Path(__file__).resolve().parent.parent / "news.js"
    js = "window.NEWS = " + json.dumps(final, ensure_ascii=False).replace("<", "\\u003c") + ";\n"
    out.write_text(js, encoding="utf-8")

    # Per-outlet summary: who produced usable stories, who produced none.
    kept_by_source = {}
    for s in final:
        kept_by_source[s["source"]] = kept_by_source.get(s["source"], 0) + 1

    print(f"\nWrote {len(final)} on-topic stories to {out}\n")
    print("Stories per tag:")
    for tag in TAG_PHRASES:
        n = sum(1 for s in final if s["tag"] == tag)
        flag = "   <-- EMPTY" if n == 0 else ""
        print(f"  {tag:12} {n}{flag}")

    print("\nPer-outlet results (outlets that matched nothing are marked):")
    for source in SOURCES:
        n = kept_by_source.get(source, 0)
        flag = "" if n else "   <-- zero results, name may need fixing"
        print(f"  {source}: {n}{flag}")

    if failed:
        print(f"\nWARNING: {len(failed)} searches failed (Google rate limiting). "
              "Wait a few minutes and run this again for a fuller feed.")


if __name__ == "__main__":
    main()
