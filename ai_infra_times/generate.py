"""
AI Infra Times · Daily Edition Generator
Architecture: RSS feeds → keyword filter → Groq llama-3.3-70b → HTML template
Python stdlib only. No pip installs.
Run locally:  GROQ_API_KEY=xxx python generate.py
"""

import os
import json
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
import datetime
import sys
import time
import re

# ── CONFIG ────────────────────────────────────────────────────────────────────

GROQ_API_KEY  = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL    = "llama-3.3-70b-versatile"
GROQ_URL      = "https://api.groq.com/openai/v1/chat/completions"

TEMPLATE_PATH = "template.html"
OUTPUT_PATH   = "../docs/index.html"
ARCHIVE_DIR   = "../docs/archive"

VOLUME      = 1
LAUNCH_DATE = datetime.date(2026, 4, 12)

RSS_FEEDS = [
    "https://hnrss.org/frontpage",
    "https://rss.arxiv.org/rss/cs.AI",
    "https://rss.arxiv.org/rss/cs.AR",
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://venturebeat.com/category/ai/feed/",
    "https://www.theverge.com/rss/index.xml",
    "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "https://www.semianalysis.com/feed",
]

KEYWORDS = [
    "gpu", "chip", "inference", "nvidia", "amd", "intel", "groq", "cerebras",
    "sambanova", "tenstorrent", "datacenter", "data center", "compute", "llm",
    "large language model", "tsmc", "hbm", "bandwidth", "semiconductor",
    "ai infrastructure", "sovereign ai", "export control", "silicon", "foundry",
    "h100", "h200", "b200", "blackwell", "hopper", "wafer", "fab", "training",
    "deployment", "accelerator", "tpu", "npu", "fpga", "transformer",
    "hyperscaler", "cluster", "cooling", "power", "watt", "flop",
]

# ── STEP 1: FETCH RSS ─────────────────────────────────────────────────────────

def fetch_feed(url: str, cutoff: datetime.datetime) -> list:
    """Fetch one RSS/Atom feed, return items newer than cutoff."""
    headers = {"User-Agent": "AI-Infra-Times/1.0 (RSS reader; +https://github.com/MRG15/AI_infra_MRG)"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
    except Exception as e:
        print(f"    ⚠  Could not fetch {url}: {e}")
        return []

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        print(f"    ⚠  XML parse error {url}: {e}")
        return []

    # Support both RSS <item> and Atom <entry>
    nodes = root.findall(".//item")
    if not nodes:
        ns = "http://www.w3.org/2005/Atom"
        nodes = root.findall(f".//{{{ns}}}entry") or root.findall(".//entry")

    items = []
    for node in nodes:
        title   = _text(node, ["title"])
        summary = _text(node, ["description", "summary", "content"])
        link    = _text(node, ["link"])
        pub     = _text(node, ["pubDate", "published", "updated", "dc:date"])

        pub_dt = parse_date(pub)
        if pub_dt and pub_dt < cutoff:
            continue

        if title:
            items.append({
                "title":   clean_text(title),
                "summary": clean_text(summary)[:400],
                "url":     link.strip() if link else "",
                "date":    pub_dt.strftime("%-d %b %Y") if pub_dt else "recent",
                "source":  source_name(url),
            })

    return items

def _text(node: ET.Element, tags: list) -> str:
    """Try multiple tag names (with/without namespace) and return first match."""
    ns_list = ["", "http://www.w3.org/2005/Atom", "http://purl.org/dc/elements/1.1/"]
    for tag in tags:
        for ns in ns_list:
            el = node.find(f"{{{ns}}}{tag}" if ns else tag)
            if el is not None and el.text:
                return el.text.strip()
    return ""

def parse_date(s: str) -> datetime.datetime:
    if not s:
        return None
    s = s.strip()
    s = re.sub(r'\s+[A-Z]{2,4}$', '', s)   # strip trailing tz names like GMT
    fmts = [
        "%a, %d %b %Y %H:%M:%S",
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]
    for fmt in fmts:
        try:
            dt = datetime.datetime.strptime(s, fmt)
            return dt.replace(tzinfo=None)
        except ValueError:
            continue
    return None

def clean_text(s: str) -> str:
    s = re.sub(r'<[^>]+>', ' ', s)
    s = re.sub(r'&amp;',  '&',  s)
    s = re.sub(r'&lt;',   '<',  s)
    s = re.sub(r'&gt;',   '>',  s)
    s = re.sub(r'&quot;', '"',  s)
    s = re.sub(r'&#\d+;', '',   s)
    s = re.sub(r'\s+',    ' ',  s)
    return s.strip()

def source_name(url: str) -> str:
    mapping = {
        "hnrss.org":        "Hacker News",
        "arxiv.org":        "arXiv",
        "techcrunch.com":   "TechCrunch",
        "venturebeat.com":  "VentureBeat",
        "theverge.com":     "The Verge",
        "arstechnica.com":  "Ars Technica",
        "semianalysis.com": "SemiAnalysis",
    }
    for domain, name in mapping.items():
        if domain in url:
            return name
    return re.sub(r'^www\.', '', url.split("/")[2]) if "/" in url else url

# ── STEP 2: FILTER ────────────────────────────────────────────────────────────

def is_relevant(item: dict) -> bool:
    text = (item["title"] + " " + item["summary"]).lower()
    return any(kw in text for kw in KEYWORDS)

def fetch_all(hours: int = 72) -> list:
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
    all_items = []
    for url in RSS_FEEDS:
        items = fetch_feed(url, cutoff)
        print(f"    {source_name(url):20s} → {len(items)} items")
        all_items.extend(items)
    return all_items

# ── STEP 3: GROQ ──────────────────────────────────────────────────────────────

def build_prompt(items: list) -> str:
    today     = datetime.date.today()
    issue     = (today - LAUNCH_DATE).days + 1
    today_str = today.strftime("%-d %B %Y")

    lines = []
    for i, item in enumerate(items[:80], 1):
        lines.append(f"{i}. [{item['source']} · {item['date']}] {item['title']}")
        if item["summary"]:
            lines.append(f"   {item['summary'][:220]}")

    feed_block = "\n".join(lines)

    return f"""You are the editor of AI Infra Times, a daily intelligence briefing on AI GPU and infrastructure.

Below are real RSS headlines fetched in the last 72 hours. Select the 10 most breakthrough-worthy stories and return them in the exact JSON schema below.

TODAY: {today_str}  |  Vol. {VOLUME}, Issue {issue}

RSS HEADLINES:
{feed_block}

SELECTION — weight heavily:
- New chip architectures, tape-outs, benchmark breakthroughs
- Export controls, AI Acts, regulatory moves with real teeth
- Supply chain shifts: fab deals, HBM constraints, cooling
- Sovereign AI infrastructure deals >$200M
- Inference optimisation with measured throughput/latency numbers
- Research shipped into production

Weight lightly: funding <$100M, keynote-only announcements, rebrands

RETURN ONLY valid JSON — no markdown fences, no backticks, no text outside the object:

{{
  "edition_date": "{today_str}",
  "edition_title": "Today's Edition",
  "volume": {VOLUME},
  "issue": {issue},
  "stories": [
    {{
      "id": 1,
      "headline": "Headline in sentence case, specific and factual",
      "category": "Silicon",
      "source": "Publication name",
      "synopsis": [
        "What happened — core fact with a specific number or name.",
        "Who is involved: companies, countries, people.",
        "Key numbers: scale, cost, timeline, performance delta.",
        "Why this matters in the AI infrastructure race.",
        "What to watch next — the forward-looking signal."
      ],
      "explanation": "2-3 sentences using a simple everyday analogy. Zero jargon. Like explaining to a smart non-technical friend at dinner.",
      "visual": {{
        "type": "bar_chart",
        "title": "Chart title with unit",
        "data": {{ "items": [{{"label": "A", "value": 100, "unit": "TB/s"}}] }}
      }}
    }}
  ]
}}

RULES:
- category must be exactly one of: Silicon, Infrastructure, Cloud, Investment, Policy, Breakthrough
- visual.type must be exactly one of: bar_chart, timeline, flow, market_share
- bar_chart:    data.items    = [{{label, value, unit}}]
- timeline:     data.events   = [{{date, title, type: "past"|"now"|"future"}}]
- flow:         data.steps    = [{{title, desc}}]
- market_share: data.segments = [{{name, pct}}]  — pct values must sum to 100
- Every story must have a visual
- Return exactly 10 stories
- Headline must lead with the news, not just the company name
- Synopsis line 1 must contain at least one specific number, name, or date
- explanation must not use: significant, important, crucial, key, leverage, paradigm"""

def call_groq(api_key: str, items: list, retries: int = 3) -> dict:
    prompt  = build_prompt(items)
    payload = {
        "model":           GROQ_MODEL,
        "messages":        [{"role": "user", "content": prompt}],
        "temperature":     0.3,
        "max_tokens":      8192,
        "response_format": {"type": "json_object"},
    }
    data = json.dumps(payload).encode("utf-8")

    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                GROQ_URL, data=data,
                headers={
                    "Content-Type":  "application/json",
                    "Authorization": f"Bearer {api_key}",
                    "User-Agent":    "AI-Infra-Times/1.0",
                }
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            raw = body["choices"][0]["message"]["content"]
            if not raw.strip():
                raise RuntimeError("Empty response from Groq")
            return parse_json(raw)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode()
            print(f"    Attempt {attempt} — HTTP {e.code}: {err_body[:200]}")
            if attempt < retries:
                time.sleep(5 * attempt)
        except Exception as e:
            print(f"    Attempt {attempt} — {e}")
            if attempt < retries:
                time.sleep(5 * attempt)

    raise RuntimeError(f"Groq API failed after {retries} attempts")

def parse_json(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    s, e = raw.find("{"), raw.rfind("}")
    if s == -1 or e == -1:
        raise ValueError(f"No JSON found. Raw snippet: {raw[:300]}")
    return json.loads(raw[s:e+1])

# ── VALIDATE ──────────────────────────────────────────────────────────────────

def validate(edition: dict) -> dict:
    valid_cats = {"Silicon", "Infrastructure", "Cloud", "Investment", "Policy", "Breakthrough"}
    valid_vis  = {"bar_chart", "timeline", "flow", "market_share"}
    for s in edition.get("stories", []):
        if s.get("category") not in valid_cats:
            s["category"] = "Silicon"
        if "visual" in s and s["visual"].get("type") not in valid_vis:
            s["visual"]["type"] = "bar_chart"
        if not isinstance(s.get("synopsis"), list):
            s["synopsis"] = [s.get("synopsis", ""), "", "", "", ""]
        while len(s["synopsis"]) < 5:
            s["synopsis"].append("")
    edition["stories"] = edition.get("stories", [])[:10]
    return edition

# ── STEP 4: OUTPUT ────────────────────────────────────────────────────────────

def inject(edition: dict) -> str:
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        tmpl = f.read()
    if "{{EDITION_DATA}}" not in tmpl:
        raise ValueError("Template missing {{EDITION_DATA}} placeholder")
    return tmpl.replace("{{EDITION_DATA}}", json.dumps(edition, ensure_ascii=False, indent=2))

def write_outputs(html: str, edition: dict):
    today = datetime.date.today().strftime("%Y-%m-%d")

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"    index.html  → {OUTPUT_PATH}")

    os.makedirs(ARCHIVE_DIR, exist_ok=True)

    json_path = os.path.join(ARCHIVE_DIR, f"{today}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(edition, f, ensure_ascii=False, indent=2)
    print(f"    archive     → {json_path}")

    html_path = os.path.join(ARCHIVE_DIR, f"{today}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"    html copy   → {html_path}")

    build_archive_index()

def build_archive_index():
    cat_colors = {
        "Silicon": "#1a4f72", "Infrastructure": "#2d6a3f", "Cloud": "#5a3475",
        "Investment": "#7a3520", "Policy": "#4a4215", "Breakthrough": "#b5610a",
    }
    entries = []
    for jf in sorted(os.listdir(ARCHIVE_DIR), reverse=True):
        if not jf.endswith(".json"):
            continue
        date_str = jf[:-5]
        try:
            with open(os.path.join(ARCHIVE_DIR, jf), encoding="utf-8") as f:
                ed = json.load(f)
            d     = datetime.date.fromisoformat(date_str)
            nice  = d.strftime("%-d %B %Y")
            vol   = ed.get("volume", 1)
            issue = ed.get("issue", "?")
            top3  = ed.get("stories", [])[:3]
        except Exception:
            continue

        hlines = "".join(
            f'<div style="display:flex;gap:8px;align-items:baseline;margin-bottom:4px;">'
            f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:9px;color:{cat_colors.get(s.get("category","Silicon"),"#555")};text-transform:uppercase;white-space:nowrap;">{s.get("category","")}</span>'
            f'<span style="font-size:13px;color:#3a3530;">{s.get("headline","")[:100]}</span></div>'
            for s in top3
        )
        entries.append(
            f'<a href="archive/{date_str}.html" style="display:block;text-decoration:none;color:inherit;border-bottom:1px solid #d8d0c8;padding:20px 0;">'
            f'<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px;">'
            f'<span style="font-family:\'Playfair Display\',serif;font-size:20px;font-weight:700;color:#1a1714;">{nice}</span>'
            f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:9px;color:#8a8278;text-transform:uppercase;">Vol.{vol} · Issue {issue}</span>'
            f'</div>{hlines}</a>'
        )

    body = "\n".join(entries) if entries else "<p style='color:#8a8278;font-style:italic'>No editions yet.</p>"
    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Archive · AI Infra Times</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
body{{margin:0;background:#f5f0e8;font-family:Georgia,serif}}
.mast{{border-bottom:3px double #3a3530;padding:16px 0 12px;text-align:center}}
.mast-top{{display:flex;justify-content:space-between;align-items:center;max-width:760px;margin:0 auto;padding:0 24px 10px}}
.wrap{{max-width:760px;margin:0 auto;padding:32px 24px 64px}}
h1{{font-family:'Playfair Display',serif;font-size:52px;font-weight:700;margin:4px 0;color:#1a1714;letter-spacing:-.01em}}
h2{{font-family:'Playfair Display',serif;font-size:28px;font-weight:700;color:#1a1714;margin:0 0 24px;border-bottom:1px solid #c8c0b8;padding-bottom:12px}}
.meta{{font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:.18em;text-transform:uppercase;color:#8a8278}}
.back{{font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:.12em;text-transform:uppercase;color:#8a8278;text-decoration:none;border:1px solid #c8c0b8;padding:4px 10px}}
</style></head><body>
<header class="mast">
  <div class="mast-top"><span class="meta">Archive</span><a class="back" href="../index.html">← Today's Edition</a></div>
  <p class="meta" style="margin:0 0 6px">Intelligence on silicon, infrastructure &amp; the compute race</p>
  <h1>AI Infra Times</h1>
</header>
<main class="wrap"><h2>All Editions</h2>{body}</main>
</body></html>"""

    out = os.path.join(os.path.dirname(ARCHIVE_DIR), "archive.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"    archive.html rebuilt")

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    if not GROQ_API_KEY:
        print("ERROR: GROQ_API_KEY environment variable not set.")
        print("  Local:  export GROQ_API_KEY=gsk_... && python generate.py")
        print("  CI:     add GROQ_API_KEY to repo Settings → Secrets → Actions")
        sys.exit(1)

    today = datetime.date.today()
    issue = (today - LAUNCH_DATE).days + 1
    print(f"\nAI Infra Times Generator · {today}  (Vol.{VOLUME} · Issue {issue})")
    print(f"  Model:    {GROQ_MODEL}")
    print(f"  Template: {TEMPLATE_PATH}")
    print(f"  Output:   {OUTPUT_PATH}\n")

    print("[ 1/5 ] Fetching RSS feeds (last 72 hours)...")
    all_items = fetch_all(hours=72)
    print(f"        {len(all_items)} total items across all feeds\n")

    print("[ 2/5 ] Filtering for AI infra relevance...")
    relevant = [i for i in all_items if is_relevant(i)]
    print(f"        {len(relevant)} relevant items")
    if len(relevant) < 5:
        print("        ⚠  < 5 relevant items — relaxing filter, using all items")
        relevant = all_items
    if not relevant:
        print("ERROR: No items found from any feed. Check network.")
        sys.exit(1)

    print(f"\n[ 3/5 ] Calling Groq API ({GROQ_MODEL}) with {min(len(relevant), 80)} items...")
    edition = call_groq(GROQ_API_KEY, relevant)
    print(f"        {len(edition.get('stories', []))} stories returned")

    print("\n[ 4/5 ] Validating edition data...")
    edition = validate(edition)

    print("\n[ 5/5 ] Writing output files...")
    html = inject(edition)
    write_outputs(html, edition)

    print("\n✓ Done. Edition ready:")
    for i, s in enumerate(edition["stories"], 1):
        print(f"  {i:02d}. [{s.get('category','?'):14s}] {s.get('headline','')[:75]}")

if __name__ == "__main__":
    main()
