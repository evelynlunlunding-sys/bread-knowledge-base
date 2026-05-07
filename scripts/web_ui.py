"""
web_ui.py — Simple browser-based knowledge base viewer

A lightweight Flask-free static site generator that:
  - Converts all markdown files to HTML
  - Builds a navigation tree (country → bread)
  - Embeds a simple search UI
  - Serves locally via Python's built-in HTTP server

Usage:
    python scripts/web_ui.py          # generate + serve at http://localhost:8000
    python scripts/web_ui.py --build  # generate only
"""

import re
import sys
import shutil
import http.server
import socketserver
from pathlib import Path

# Minimal markdown→HTML conversion (no extra deps beyond stdlib)
try:
    import markdown
    HAS_MARKDOWN = True
except ImportError:
    HAS_MARKDOWN = False

ROOT = Path(__file__).parent.parent
KB_DIR = ROOT / "knowledge_base"
SITE_DIR = ROOT / "docs"

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} — Bread Knowledge Base</title>
  <style>
    :root {{
      --bg: #fdf8f0; --surface: #fff; --text: #2c2416;
      --accent: #c07a2a; --sidebar-bg: #3b2a1a; --sidebar-text: #f5e6d0;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: 'Georgia', serif; background: var(--bg); color: var(--text); display: flex; min-height: 100vh; }}
    #sidebar {{ width: 260px; min-height: 100vh; background: var(--sidebar-bg); color: var(--sidebar-text); padding: 24px 16px; position: fixed; overflow-y: auto; }}
    #sidebar h1 {{ font-size: 1.1rem; margin-bottom: 4px; color: var(--accent); }}
    #sidebar .tagline {{ font-size: 0.75rem; opacity: 0.7; margin-bottom: 20px; }}
    #sidebar input {{ width: 100%; padding: 6px 8px; border-radius: 4px; border: none; font-size: 0.85rem; margin-bottom: 16px; }}
    #sidebar details summary {{ cursor: pointer; font-weight: bold; padding: 4px 0; color: var(--accent); font-size: 0.9rem; }}
    #sidebar ul {{ list-style: none; padding-left: 12px; margin-top: 4px; }}
    #sidebar ul li a {{ color: var(--sidebar-text); text-decoration: none; font-size: 0.85rem; line-height: 1.9; opacity: 0.85; }}
    #sidebar ul li a:hover {{ color: var(--accent); opacity: 1; }}
    #main {{ margin-left: 260px; flex: 1; padding: 40px 60px; max-width: 900px; }}
    #main h1 {{ font-size: 2rem; color: var(--text); border-bottom: 2px solid var(--accent); padding-bottom: 8px; margin-bottom: 24px; }}
    #main h2 {{ font-size: 1.4rem; margin-top: 32px; margin-bottom: 12px; color: var(--accent); }}
    #main h3 {{ font-size: 1.1rem; margin-top: 20px; margin-bottom: 8px; }}
    #main p {{ line-height: 1.8; margin-bottom: 12px; }}
    #main table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
    #main th {{ background: var(--accent); color: white; padding: 8px 12px; text-align: left; }}
    #main td {{ padding: 7px 12px; border-bottom: 1px solid #e8d5b0; }}
    #main tr:nth-child(even) td {{ background: #faf4e8; }}
    #main ul, #main ol {{ padding-left: 24px; margin-bottom: 12px; line-height: 1.9; }}
    #main img {{ max-width: 100%; border-radius: 6px; margin: 12px 0; box-shadow: 0 2px 8px rgba(0,0,0,0.15); }}
    #main code {{ background: #f0e8d5; padding: 2px 6px; border-radius: 3px; font-family: monospace; font-size: 0.9em; }}
    #main pre {{ background: #f0e8d5; padding: 16px; border-radius: 6px; overflow-x: auto; margin: 12px 0; }}
    #main blockquote {{ border-left: 3px solid var(--accent); padding-left: 16px; color: #5a4030; margin: 12px 0; }}
    .tag {{ display: inline-block; background: var(--accent); color: white; padding: 2px 8px; border-radius: 12px; font-size: 0.75rem; margin: 2px; }}
    .frontmatter {{ background: #faf0d8; border: 1px solid #e0c890; border-radius: 6px; padding: 12px 16px; margin-bottom: 24px; font-size: 0.85rem; }}
    a {{ color: var(--accent); }}
    @media (max-width: 768px) {{ #sidebar {{ display: none; }} #main {{ margin-left: 0; padding: 24px 20px; }} }}
  </style>
</head>
<body>
  <nav id="sidebar">
    <h1>🍞 Bread KB</h1>
    <p class="tagline">Global Bread Knowledge Base</p>
    <input type="text" id="search" placeholder="Search breads…" oninput="filterNav(this.value)">
    <div id="nav">{nav_html}</div>
  </nav>
  <main id="main">
    {content_html}
  </main>
  <script>
    function filterNav(q) {{
      q = q.toLowerCase();
      document.querySelectorAll('#nav li').forEach(li => {{
        li.style.display = li.textContent.toLowerCase().includes(q) ? '' : 'none';
      }});
      document.querySelectorAll('#nav details').forEach(d => {{
        const visible = [...d.querySelectorAll('li')].some(li => li.style.display !== 'none');
        d.style.display = visible || !q ? '' : 'none';
      }});
    }}
  </script>
</body>
</html>
"""

INDEX_CONTENT = """\
<h1>🌍 Global Bread Knowledge Base</h1>
<p>A comprehensive, LLM-powered encyclopedia of breads from around the world.</p>
<h2>Browse by Country</h2>
{country_list}
<h2>About This Project</h2>
<p>This knowledge base is automatically built and maintained by an LLM pipeline that ingests
articles, recipes, and academic papers, then synthesizes them into structured markdown entries.</p>
"""


def _md_to_html(text: str) -> str:
    if HAS_MARKDOWN:
        # Remove wiki-style [[links]] → plain text so they don't break parser
        text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
        return markdown.markdown(
            text,
            extensions=["tables", "fenced_code", "nl2br", "sane_lists"],
        )
    # Fallback: basic conversion
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"^# (.+)$", r"<h1>\1</h1>", text, flags=re.MULTILINE)
    text = re.sub(r"^## (.+)$", r"<h2>\1</h2>", text, flags=re.MULTILINE)
    text = re.sub(r"^### (.+)$", r"<h3>\1</h3>", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"\n\n+", "</p><p>", text)
    return f"<p>{text}</p>"


def _build_nav(kb_dir: Path) -> str:
    html = []
    for country_dir in sorted(kb_dir.iterdir()):
        if not country_dir.is_dir():
            continue
        breads = sorted(country_dir.glob("*.md"))
        if not breads:
            continue
        html.append(f'<details open><summary>🏳 {country_dir.name}</summary><ul>')
        for md in breads:
            name = md.stem.replace("_", " ").title()
            href = f"{country_dir.name}/{md.stem}.html"
            html.append(f'<li><a href="../{href}">{name}</a></li>')
        html.append("</ul></details>")
    return "\n".join(html)


def _strip_frontmatter(text: str) -> tuple[dict, str]:
    fm = {}
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    fm[k.strip()] = v.strip()
            return fm, parts[2].strip()
    return fm, text


def build_site() -> None:
    SITE_DIR.mkdir(exist_ok=True)
    nav_html = _build_nav(KB_DIR)

    # Index page
    country_items = "".join(
        f'<li><a href="{d.name}/index.html">{d.name}</a> — '
        f'{len(list(d.glob("*.md")))} bread(s)</li>'
        for d in sorted(KB_DIR.iterdir()) if d.is_dir()
    )
    index_content = INDEX_CONTENT.format(country_list=f"<ul>{country_items}</ul>")
    (SITE_DIR / "index.html").write_text(
        HTML_TEMPLATE.format(title="Home", nav_html=nav_html, content_html=index_content),
        encoding="utf-8"
    )

    # Country and bread pages
    for country_dir in sorted(KB_DIR.iterdir()):
        if not country_dir.is_dir():
            continue
        site_country = SITE_DIR / country_dir.name
        site_country.mkdir(exist_ok=True)

        breads_html = "<ul>" + "".join(
            f'<li><a href="{md.stem}.html">{md.stem.replace("_"," ").title()}</a></li>'
            for md in sorted(country_dir.glob("*.md"))
        ) + "</ul>"
        country_index = f"<h1>{country_dir.name}</h1>\n<h2>Breads</h2>\n{breads_html}"
        (site_country / "index.html").write_text(
            HTML_TEMPLATE.format(title=country_dir.name, nav_html=nav_html, content_html=country_index),
            encoding="utf-8"
        )

        for md_file in sorted(country_dir.glob("*.md")):
            raw = md_file.read_text(encoding="utf-8")
            fm, body = _strip_frontmatter(raw)
            title = fm.get("title", md_file.stem.replace("_", " ").title())
            tags = [t.strip(" []") for t in fm.get("tags", "").split(",") if t.strip()]
            tag_html = " ".join(f'<span class="tag">{t}</span>' for t in tags)
            fm_html = (
                f'<div class="frontmatter">'
                f'<strong>Country:</strong> {fm.get("country", "")} &nbsp;|&nbsp; '
                f'<strong>Updated:</strong> {fm.get("last_updated", "")} &nbsp;|&nbsp; '
                f'{tag_html}'
                f'</div>'
            ) if fm else ""
            content = fm_html + _md_to_html(body)
            (site_country / f"{md_file.stem}.html").write_text(
                HTML_TEMPLATE.format(title=title, nav_html=nav_html, content_html=content),
                encoding="utf-8"
            )

    print(f"Site built in {SITE_DIR}/")


def serve(port: int = 8000) -> None:
    import os
    os.chdir(SITE_DIR)
    handler = http.server.SimpleHTTPRequestHandler
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"Serving at http://localhost:{port}")
        print("Press Ctrl+C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    build_site()
    if "--build" not in sys.argv:
        serve()
