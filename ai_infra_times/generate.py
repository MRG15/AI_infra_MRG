"""
AI Infra Times · Daily Edition Generator
Calls Groq compound-beta (with web search) → injects JSON into HTML template → writes index.html
Run locally:  GROQ_API_KEY=your_key python generate.py
Run via CI:   GitHub Actions sets GROQ_API_KEY from repo secrets
"""

import os
import json
import urllib.request
import urllib.error
import datetime
import sys
import re

# ── CONFIG ────────────────────────────────────────────────────────────────────

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL   = "llama-3.3-70b-versatile"
GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"

TEMPLATE_PATH  = "template.html"      # relative to this script
OUTPUT_PATH    = "../docs/index.html" # GitHub Pages serves from repo-root /docs

VOLUME  = 1   # increment manually when you want to reset issue count
# Issue number = days since Vol.1 launch date
LAUNCH_DATE = datetime.date(2026, 4, 12)

# ── PROMPT ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a senior AI infrastructure analyst and editor of AI Infra Times, a daily intelligence briefing.

Search the web thoroughly for the 10 most significant AI GPU and infrastructure developments from the past 3 weeks.

Selection criteria (strictly apply this weighting):
  HIGH WEIGHT:
  - New chip architectures, tape-outs, or benchmark breakthroughs
  - Regulatory moves with real teeth (export controls, AI Acts, RBI/SEBI AI circulars)
  - Supply chain shifts: new fab deals, memory supply constraints, cooling infrastructure
  - Sovereign AI infrastructure deals above $200M
  - Research papers that have shipped into production deployments
  - Inference optimisation breakthroughs with measured throughput/latency numbers

  LOW WEIGHT (deprioritise unless strategically pivotal):
  - Funding rounds under $100M unless the strategic angle is exceptional
  - Conference keynote announcements without shipped hardware or code
  - Product rebrands or marketing repositioning
  - Stories already covered in the previous 2 weeks

Today's date: {today}

Return ONLY a valid JSON object. No markdown fences, no backticks, no explanatory text before or after. The entire response must be parseable by json.loads().

Schema:
{{
  "edition_date": "{today_long}",
  "edition_title": "Today's Edition",
  "volume": {volume},
  "issue": {issue},
  "stories": [
    {{
      "id": 1,
      "headline": "Headline in sentence case, specific and factual",
      "category": "Silicon",
      "source": "Publication or organisation name",
      "synopsis": [
        "What happened — the single core fact, with a specific number or name if possible.",
        "Who is involved: companies, countries, people.",
        "Key numbers: scale, cost, timeline, performance delta.",
        "Why this matters in the context of the broader AI infrastructure race.",
        "What to watch next — the forward-looking signal."
      ],
      "explanation": "2-3 sentences using a concrete everyday analogy (factory, highway, kitchen, sports team, electricity grid) to explain what really happened and why it matters. Zero jargon. Written as if explaining to a smart non-technical friend at dinner.",
      "visual": {{
        "type": "bar_chart",
        "title": "Concise chart title with unit",
        "data": {{ "items": [{{"label": "Product A", "value": 100, "unit": "TB/s"}}] }}
      }}
    }}
  ]
}}

Rules:
- "category" must be exactly one of: Silicon, Infrastructure, Cloud, Investment, Policy, Breakthrough
- "visual.type" must be exactly one of: bar_chart, timeline, flow, market_share
- For bar_chart:     data.items  = [{{"label": str, "value": number, "unit": str}}]
- For timeline:      data.events = [{{"date": str, "title": str, "type": "past"|"now"|"future"}}]
- For flow:          data.steps  = [{{"title": str, "desc": str}}]
- For market_share:  data.segments = [{{"name": str, "pct": number}}]  — pct values must sum to exactly 100
- Every story must have a visual. Pick the most insightful type for that story's data.
- Headline must not start with a company name alone; lead with the news.
- Synopsis line 1 must contain at least one specific number, name, or date.
- explanation must not use the words "significant", "important", "crucial", "key", "leverage", or "paradigm".
- Return exactly 10 stories.
"""

# ── HELPERS ───────────────────────────────────────────────────────────────────

def build_prompt():
    today      = datetime.date.today()
    issue      = (today - LAUNCH_DATE).days + 1
    today_str  = today.strftime("%-d %B %Y")   # e.g. "12 April 2026"
    return SYSTEM_PROMPT.format(
        today      = today_str,
        today_long = today_str,
        volume     = VOLUME,
        issue      = issue,
    )

def call_groq(api_key: str) -> dict:
    prompt  = build_prompt()
    payload = {
        "model":    GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature":    0.3,
        "max_tokens":     8192,
        "response_format": {"type": "json_object"},
    }
    data = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(
        GROQ_URL,
        data    = data,
        headers = {
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent":    "AI-Infra-Times/1.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        raise RuntimeError(f"Groq API error {e.code}: {error_body}")

    raw = body.get("choices", [{}])[0].get("message", {}).get("content", "")

    if not raw.strip():
        raise RuntimeError("Empty response from Groq API")

    return parse_json(raw)

def parse_json(raw: str) -> dict:
    """Extract and parse JSON even if there's surrounding text."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Fallback: extract between first { and last }
    s = raw.find("{")
    e = raw.rfind("}")
    if s == -1 or e == -1:
        raise ValueError(f"No JSON object found in response. Raw: {raw[:500]}")
    return json.loads(raw[s:e+1])

def validate_edition(edition: dict) -> dict:
    """Light validation and normalisation — never crash, just fix."""
    stories = edition.get("stories", [])
    valid_cats  = {"Silicon","Infrastructure","Cloud","Investment","Policy","Breakthrough"}
    valid_vis   = {"bar_chart","timeline","flow","market_share"}

    for s in stories:
        if s.get("category") not in valid_cats:
            s["category"] = "Silicon"
        if "visual" in s and s["visual"].get("type") not in valid_vis:
            s["visual"]["type"] = "bar_chart"
        # Ensure synopsis is always a list of 5
        if not isinstance(s.get("synopsis"), list):
            s["synopsis"] = [s.get("synopsis",""), "", "", "", ""]
        while len(s["synopsis"]) < 5:
            s["synopsis"].append("")

    edition["stories"] = stories[:10]  # cap at 10
    return edition

def inject_into_template(edition: dict, template_path: str) -> str:
    with open(template_path, "r", encoding="utf-8") as f:
        tmpl = f.read()
    json_str = json.dumps(edition, ensure_ascii=False, indent=2)
    if "{{EDITION_DATA}}" not in tmpl:
        raise ValueError("Template missing {{EDITION_DATA}} placeholder")
    return tmpl.replace("{{EDITION_DATA}}", json_str)

def write_output(html: str, output_path: str):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

def save_archive(edition: dict, html: str):
    """Save JSON + HTML for each edition, then rebuild archive.html index."""
    today    = datetime.date.today().strftime("%Y-%m-%d")
    arch_dir = "../docs/archive"
    os.makedirs(arch_dir, exist_ok=True)

    # Save JSON
    json_path = os.path.join(arch_dir, f"{today}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(edition, f, ensure_ascii=False, indent=2)
    print(f"  JSON saved  → {json_path}")

    # Save dated HTML (so each edition is permanently linkable)
    html_path = os.path.join(arch_dir, f"{today}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  HTML saved  → {html_path}")

    # Rebuild archive index page
    build_archive_index(arch_dir)

def build_archive_index(arch_dir: str):
    """Generate docs/archive.html listing every past edition."""
    entries = []
    for jf in sorted(os.listdir(arch_dir), reverse=True):
        if not jf.endswith(".json"):
            continue
        date_str = jf[:-5]          # "2026-04-12"
        json_path = os.path.join(arch_dir, jf)
        try:
            with open(json_path, encoding="utf-8") as f:
                ed = json.load(f)
            vol    = ed.get("volume", 1)
            issue  = ed.get("issue", "?")
            stories = ed.get("stories", [])
            top3   = stories[:3]
        except Exception:
            vol, issue, top3 = 1, "?", []

        # Format date nicely
        try:
            d = datetime.date.fromisoformat(date_str)
            nice_date = d.strftime("%-d %B %Y")
        except Exception:
            nice_date = date_str

        cat_colors = {
            "Silicon": "#1a4f72", "Infrastructure": "#2d6a3f", "Cloud": "#5a3475",
            "Investment": "#7a3520", "Policy": "#4a4215", "Breakthrough": "#b5610a",
        }
        headlines_html = ""
        for s in top3:
            cat   = s.get("category", "Silicon")
            color = cat_colors.get(cat, "#555")
            hl    = s.get("headline", "")[:100]
            headlines_html += (
                f'<div style="display:flex;gap:8px;align-items:baseline;margin-bottom:4px;">'
                f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:9px;'
                f'letter-spacing:.08em;color:{color};text-transform:uppercase;white-space:nowrap;">{cat}</span>'
                f'<span style="font-size:13px;color:#3a3530;">{hl}</span>'
                f'</div>'
            )

        html_file = f"{date_str}.html"
        entries.append(
            f'<a href="archive/{html_file}" style="display:block;text-decoration:none;color:inherit;'
            f'border-bottom:1px solid #d8d0c8;padding:20px 0;">'
            f'<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px;">'
            f'<span style="font-family:\'Playfair Display\',serif;font-size:20px;font-weight:700;color:#1a1714;">{nice_date}</span>'
            f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:9px;letter-spacing:.1em;'
            f'color:#8a8278;text-transform:uppercase;">Vol. {vol} · Issue {issue}</span>'
            f'</div>'
            f'{headlines_html}'
            f'</a>'
        )

    entries_html = "\n".join(entries) if entries else "<p style='color:#8a8278;font-style:italic;'>No editions yet.</p>"

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Archive · AI Infra Times</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  body {{ margin:0; background:#f5f0e8; font-family: Georgia, serif; min-height:100vh; }}
  .masthead {{ border-bottom: 3px double #3a3530; padding: 16px 0 12px; text-align:center; background:#f5f0e8; }}
  .masthead-top {{ display:flex; justify-content:space-between; align-items:center; max-width:760px; margin:0 auto; padding:0 24px 10px; }}
  .masthead-meta {{ font-family:'JetBrains Mono',monospace; font-size:10px; letter-spacing:.12em; text-transform:uppercase; color:#8a8278; }}
  .masthead-title {{ font-family:'Playfair Display',serif; font-size:52px; font-weight:700; margin:4px 0; color:#1a1714; letter-spacing:-.01em; }}
  .masthead-tagline {{ font-family:'JetBrains Mono',monospace; font-size:9px; letter-spacing:.18em; text-transform:uppercase; color:#8a8278; margin:0 0 6px; }}
  .page-wrap {{ max-width:760px; margin:0 auto; padding:32px 24px 64px; }}
  h2 {{ font-family:'Playfair Display',serif; font-size:28px; font-weight:700; color:#1a1714; margin:0 0 24px; border-bottom:1px solid #c8c0b8; padding-bottom:12px; }}
  a:hover span {{ text-decoration:underline; }}
</style>
</head>
<body>
<header class="masthead">
  <div class="masthead-top">
    <span class="masthead-meta">Archive</span>
    <a href="../index.html" style="font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:.12em;text-transform:uppercase;color:#8a8278;text-decoration:none;border:1px solid #c8c0b8;padding:4px 10px;">← Today's Edition</a>
  </div>
  <p class="masthead-tagline">Intelligence on silicon, infrastructure & the compute race</p>
  <h1 class="masthead-title">AI Infra Times</h1>
</header>
<main class="page-wrap">
  <h2>All Editions</h2>
  {entries_html}
</main>
</body>
</html>"""

    out = os.path.join(os.path.dirname(arch_dir), "archive.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"  Archive index → {out}")

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    api_key = GROQ_API_KEY
    if not api_key:
        print("ERROR: GROQ_API_KEY environment variable not set.")
        print("  Local run:   export GROQ_API_KEY=your_key && python generate.py")
        print("  GitHub CI:   add GROQ_API_KEY to repo Settings → Secrets → Actions")
        sys.exit(1)

    print(f"AI Infra Times Generator · {datetime.date.today()}")
    print(f"  Model:    {GROQ_MODEL}")
    print(f"  Template: {TEMPLATE_PATH}")
    print(f"  Output:   {OUTPUT_PATH}")
    print()

    print("[ 1/4 ] Calling Groq API (llama-3.3-70b-versatile)...")
    edition = call_groq(api_key)
    print(f"        Got {len(edition.get('stories',[]))} stories")

    print("[ 2/4 ] Validating and normalising edition data...")
    edition = validate_edition(edition)

    print("[ 3/4 ] Injecting into HTML template...")
    html = inject_into_template(edition, TEMPLATE_PATH)

    print("[ 4/4 ] Writing output files...")
    write_output(html, OUTPUT_PATH)
    print(f"        HTML written → {OUTPUT_PATH}")
    save_archive(edition, html)

    print()
    print("Done. Edition ready.")
    for i, s in enumerate(edition["stories"], 1):
        print(f"  {i:02d}. [{s.get('category','?'):14s}] {s.get('headline','')[:80]}")

if __name__ == "__main__":
    main()
