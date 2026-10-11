import html
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
SITE_DIR = ROOT / "site"
KST = timezone(timedelta(hours=9))


def latest_json(prefix: str) -> Path:
    files = sorted(OUTPUT_DIR.glob(f"{prefix}_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"No output file found for {prefix}")
    return files[0]


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def count_by(rows: List[Dict], key: str) -> Counter:
    return Counter(row.get(key) or "미분류" for row in rows)


def render_idea_cards(ideas: List[Dict]) -> str:
    cards = []
    for idea in ideas[:20]:
        source_links = []
        for url in idea.get("source_urls", [])[:3]:
            source_links.append(f'<a href="{esc(url)}" target="_blank" rel="noreferrer">source</a>')
        cards.append(
            f"""
            <article class="card idea">
              <div class="meta">{esc(idea.get("major_topic"))} · {esc(idea.get("sub_topic"))}</div>
              <h3>{esc(idea.get("idea_title"))}</h3>
              <p class="hook">{esc(idea.get("hook"))}</p>
              <p>{esc(idea.get("summary"))}</p>
              <div class="links">{' '.join(source_links)}</div>
            </article>
            """
        )
    return "\n".join(cards)


def render_topic_table(classified_rows: List[Dict]) -> str:
    rows = []
    for item in classified_rows[:80]:
        post = item.get("post", {})
        classification = item.get("classification", {})
        if classification.get("is_educational"):
            continue
        rows.append(
            f"""
            <tr>
              <td>{esc(post.get("platform"))}</td>
              <td><a href="{esc(post.get("url"))}" target="_blank" rel="noreferrer">{esc(post.get("title"))}</a></td>
              <td>{esc(classification.get("major_topic"))}</td>
              <td>{esc(classification.get("sub_topic"))}</td>
              <td>{esc(post.get("views"))}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def render_distribution(counter: Counter) -> str:
    if not counter:
        return "<p>No data</p>"
    maximum = max(counter.values())
    items = []
    for label, count in counter.most_common(12):
        width = int((count / maximum) * 100)
        items.append(
            f"""
            <div class="bar-row">
              <span>{esc(label)}</span>
              <div class="bar"><i style="width:{width}%"></i></div>
              <strong>{count}</strong>
            </div>
            """
        )
    return "\n".join(items)


def main() -> None:
    raw_path = latest_json("raw_posts")
    classified_path = latest_json("classified_topics")
    ideas_path = latest_json("weekly_ideas")

    raw_rows = load_json(raw_path)
    classified_rows = load_json(classified_path)
    ideas = load_json(ideas_path)

    major_counter = Counter()
    sub_counter = Counter()
    for item in classified_rows:
        classification = item.get("classification", {})
        if classification.get("is_educational"):
            continue
        major_counter[classification.get("major_topic") or "미분류"] += 1
        sub_counter[classification.get("sub_topic") or "미분류"] += 1

    generated_at = datetime.now(tz=KST).strftime("%Y-%m-%d %H:%M KST")
    run_date = raw_rows[0].get("run_date") if raw_rows else ""

    html_body = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Tarot Research MVP</title>
  <style>
    :root {{
      --bg: #fbf7ef;
      --ink: #271b13;
      --muted: #7f6a5b;
      --line: #eadccb;
      --card: #fffdf8;
      --accent: #b45f30;
      --accent-2: #274f45;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: ui-serif, Georgia, "Times New Roman", serif;
      background:
        radial-gradient(circle at top left, #ffe5bd 0, transparent 34rem),
        linear-gradient(135deg, #fbf7ef, #f2eadf);
      color: var(--ink);
    }}
    main {{ width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 48px 0; }}
    header {{ display: grid; gap: 12px; margin-bottom: 28px; }}
    h1 {{ font-size: clamp(2.4rem, 6vw, 5.4rem); line-height: .9; margin: 0; letter-spacing: -.06em; }}
    h2 {{ font-size: 1.4rem; margin: 0 0 16px; }}
    h3 {{ font-size: 1.2rem; margin: 8px 0 10px; }}
    p {{ color: var(--muted); line-height: 1.6; }}
    .stats {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin: 24px 0; }}
    .stat, .card, section {{
      background: color-mix(in srgb, var(--card) 92%, white);
      border: 1px solid var(--line);
      border-radius: 22px;
      box-shadow: 0 18px 60px rgba(62, 39, 22, .08);
    }}
    .stat {{ padding: 18px; }}
    .stat strong {{ display: block; font-size: 2rem; }}
    section {{ padding: 22px; margin: 18px 0; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }}
    .card {{ padding: 18px; }}
    .meta {{ color: var(--accent); font-size: .9rem; font-weight: 700; }}
    .hook {{ color: var(--accent-2); font-weight: 700; }}
    .links a {{ color: var(--accent); margin-right: 10px; }}
    .bar-row {{ display: grid; grid-template-columns: 120px 1fr 44px; gap: 10px; align-items: center; margin: 10px 0; }}
    .bar {{ height: 12px; background: #f2e3d2; border-radius: 999px; overflow: hidden; }}
    .bar i {{ display: block; height: 100%; background: linear-gradient(90deg, var(--accent), #d89858); }}
    table {{ width: 100%; border-collapse: collapse; font-family: ui-sans-serif, system-ui, sans-serif; font-size: .9rem; }}
    td, th {{ border-bottom: 1px solid var(--line); padding: 10px; text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); }}
    td a {{ color: var(--ink); }}
    footer {{ margin-top: 24px; color: var(--muted); }}
    @media (max-width: 760px) {{
      .stats, .grid {{ grid-template-columns: 1fr; }}
      .bar-row {{ grid-template-columns: 90px 1fr 36px; }}
      table {{ font-size: .78rem; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div class="meta">Generated {esc(generated_at)} · Run date {esc(run_date)}</div>
      <h1>Tarot Research MVP</h1>
      <p>주간 타로 제너럴 리딩 콘텐츠 리서치 결과입니다. 원본 데이터는 Google Sheets에 기록되고, 이 페이지는 최신 실행 결과를 요약합니다.</p>
    </header>

    <div class="stats">
      <div class="stat"><span>Raw posts</span><strong>{len(raw_rows)}</strong></div>
      <div class="stat"><span>Classified</span><strong>{len(classified_rows)}</strong></div>
      <div class="stat"><span>Ideas</span><strong>{len(ideas)}</strong></div>
    </div>

    <section>
      <h2>추천 콘텐츠 아이디어</h2>
      <div class="grid">{render_idea_cards(ideas)}</div>
    </section>

    <section>
      <h2>대주제 분포</h2>
      {render_distribution(major_counter)}
    </section>

    <section>
      <h2>소주제 분포</h2>
      {render_distribution(sub_counter)}
    </section>

    <section>
      <h2>최근 분류 콘텐츠</h2>
      <table>
        <thead><tr><th>Platform</th><th>Title</th><th>Major</th><th>Sub</th><th>Views</th></tr></thead>
        <tbody>{render_topic_table(classified_rows)}</tbody>
      </table>
    </section>

    <footer>Source files: {esc(raw_path.name)}, {esc(classified_path.name)}, {esc(ideas_path.name)}</footer>
  </main>
</body>
</html>
"""

    SITE_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "index.html").write_text(html_body, encoding="utf-8")


if __name__ == "__main__":
    main()

