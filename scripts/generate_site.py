import argparse
import html
import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
SITE_DIR = ROOT / "site"
CLAUDE_WEEKLY_TAROT_PATH = ROOT / "data" / "claude_weekly_tarot.json"
TRANSCRIPT_ANALYSIS_PATH = ROOT / "data" / "transcript_analysis.json"
VIDEO_ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([\w-]{11})")
ANALYSES: Dict[str, Dict] = {}
SERVICE_ACCOUNT_DEFAULT = ROOT / "secrets" / "google-service-account.json"
PIPELINE_SOURCE_LABEL = ""
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


def to_int(value: Any) -> int:
    try:
        return int(float(str(value).replace(",", "").strip() or 0))
    except (TypeError, ValueError):
        return 0


def rows_to_records(values: List[List[Any]]) -> List[Dict[str, Any]]:
    if not values:
        return []
    headers = [str(cell).strip() for cell in values[0]]
    records = []
    for row in values[1:]:
        if not any(str(cell).strip() for cell in row):
            continue
        records.append({header: (row[i] if i < len(row) else "") for i, header in enumerate(headers) if header})
    return records


def load_pipeline_from_sheet():
    """Rebuild (raw_rows, classified_rows, ideas) from the pipeline's Google Sheet.

    Used when the local output/*.json files are missing (deploy-only workflow, local dashboard rebuilds).
    Prefers the `<tab>_latest` tabs the pipeline overwrites each run; falls back to the newest run_date
    in the history tabs.
    """
    import gspread
    from google.oauth2.service_account import Credentials

    service_account_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE") or str(SERVICE_ACCOUNT_DEFAULT)
    if not Path(service_account_file).exists() and SERVICE_ACCOUNT_DEFAULT.exists():
        service_account_file = str(SERVICE_ACCOUNT_DEFAULT)
    spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "").strip()
    if not spreadsheet_id or not Path(service_account_file).exists():
        raise FileNotFoundError("sheet source needs GOOGLE_SHEETS_SPREADSHEET_ID and a service account file")
    credentials = Credentials.from_service_account_file(
        service_account_file,
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly", "https://www.googleapis.com/auth/drive.readonly"],
    )
    spreadsheet = gspread.authorize(credentials).open_by_key(spreadsheet_id)
    titles = {ws.title: ws for ws in spreadsheet.worksheets()}

    def records(base: str) -> List[Dict[str, Any]]:
        latest = titles.get(f"{base}_latest")
        if latest is not None:
            rows = rows_to_records(latest.get_all_values())
            if rows:
                return rows
        history = titles.get(base)
        if history is None:
            return []
        rows = rows_to_records(history.get_all_values())
        newest = max((str(row.get("run_date", "")) for row in rows), default="")
        return [row for row in rows if str(row.get("run_date", "")) == newest]

    raw_sheet = os.getenv("GOOGLE_SHEETS_RAW_SHEET", "raw_posts")
    classified_sheet = os.getenv("GOOGLE_SHEETS_CLASSIFIED_SHEET", "classified_topics")
    ideas_sheet = os.getenv("GOOGLE_SHEETS_IDEAS_SHEET", "weekly_ideas")

    raw_rows = records(raw_sheet)
    for row in raw_rows:
        row["views"] = to_int(row.get("views"))
        row["likes"] = to_int(row.get("likes"))
    raw_by_url = {row.get("url"): row for row in raw_rows}

    classified_rows = []
    for row in records(classified_sheet):
        raw = raw_by_url.get(row.get("url"), {})
        post = {
            "platform": row.get("platform") or raw.get("platform", ""),
            "keyword": raw.get("keyword", ""),
            "title": row.get("title") or raw.get("title", ""),
            "url": row.get("url", ""),
            "views": raw.get("views", 0),
            "likes": raw.get("likes", 0),
            "author": raw.get("author", ""),
            "published_at": raw.get("published_at", ""),
        }
        classification = {
            "is_educational": bool(str(raw.get("exclude_reason", "")).strip()),
            "major_topic": row.get("major_topic", ""),
            "sub_topic": row.get("sub_topic", ""),
            "content_angle": row.get("content_angle", ""),
            "target_emotion": row.get("target_emotion", ""),
            "confidence": row.get("confidence", ""),
            "exclude_reason": raw.get("exclude_reason", ""),
        }
        classified_rows.append({"run_date": row.get("run_date", ""), "post": post, "classification": classification})

    ideas = []
    for row in records(ideas_sheet):
        urls = [u.strip() for u in re.split(r"[\s,]+", str(row.get("source_urls", ""))) if u.strip().startswith("http")]
        ideas.append({**row, "source_urls": urls})

    run_date = raw_rows[0].get("run_date", "") if raw_rows else ""
    return raw_rows, classified_rows, ideas, f"Google Sheet {raw_sheet}_latest (run {run_date})"


def load_pipeline_data(source: str):
    """source: auto | local | sheet. Returns (raw_rows, classified_rows, ideas, label)."""
    have_local = any(OUTPUT_DIR.glob("raw_posts_*.json"))
    if source == "local" or (source == "auto" and have_local):
        raw_path = latest_json("raw_posts")
        classified_path = latest_json("classified_topics")
        ideas_path = latest_json("weekly_ideas")
        return (
            load_json(raw_path),
            load_json(classified_path),
            load_json(ideas_path),
            f"{raw_path.name}, {classified_path.name}, {ideas_path.name}",
        )
    return load_pipeline_from_sheet()


def load_transcript_analyses() -> Dict[str, Dict]:
    if not TRANSCRIPT_ANALYSIS_PATH.exists():
        return {}
    try:
        data = load_json(TRANSCRIPT_ANALYSIS_PATH)
    except Exception:
        return {}
    videos = data.get("videos") if isinstance(data, dict) else None
    return videos if isinstance(videos, dict) else {}


def video_id_from_url(url: Any) -> str:
    match = VIDEO_ID_RE.search(str(url or ""))
    return match.group(1) if match else ""


def analysis_for(url: Any) -> Dict:
    return ANALYSES.get(video_id_from_url(url)) or {}


SELECTION_LABELS = {"pick_a_card": "픽어카드", "single_spread": "단일 스프레드", "none": "카드 선택 없음", "other": "기타"}


def render_analysis_toggle(url: Any) -> str:
    entry = analysis_for(url)
    if not entry:
        return ""
    status = entry.get("status")
    if status != "ok" or not entry.get("analysis"):
        label = {"no_transcript": "자막 없음", "no_llm": "자막만 수집", "llm_error": "분석 실패", "blocked": "자막 차단"}.get(status, status or "")
        return f'<span class="tag muted">{esc(label)}</span>' if label else ""
    a = entry["analysis"]
    selection = a.get("card_selection") or {}
    method = SELECTION_LABELS.get(selection.get("method"), selection.get("method") or "")
    count = selection.get("card_count")
    selection_text = " · ".join(part for part in [method, f"{count}장" if count else "", selection.get("staging") or ""] if part)
    tags = "".join(f'<span class="tag">{esc(tag)}</span>' for tag in a.get("tone_tags") or [])
    structure = " → ".join(esc(step) for step in a.get("reading_structure") or [])
    phrases = ", ".join(esc(p) for p in a.get("recurring_phrases") or [])
    transcript = entry.get("transcript") or {}
    meta = f"{'자동' if transcript.get('generated') else '수동'} 자막 {transcript.get('chars', 0):,}자 · {esc(entry.get('model', ''))}"

    def row(label: str, value: str) -> str:
        return f"<div class=\"a-row\"><span>{label}</span><div>{value}</div></div>" if value else ""

    return f"""
    <details class="analysis">
      <summary>리딩 분석 {tags}</summary>
      <div class="a-body">
        {row("오프닝 훅", esc(a.get("opening_hook")))}
        {row("카드 선택", esc(selection_text))}
        {row("진행 구조", structure)}
        {row("톤", esc(a.get("tone")))}
        {row("반복 표현", phrases)}
        {row("참여 유도", esc(a.get("audience_engagement")))}
        {row("CTA", esc(a.get("cta")))}
        {row("편지 컨셉 적용", f'<strong>{esc(a.get("letter_concept_takeaway"))}</strong>')}
        <div class="a-meta">{meta}</div>
      </div>
    </details>
    """


def render_reading_patterns(urls: List[Any]) -> str:
    entries = [analysis_for(url) for url in urls]
    analyses = [entry["analysis"] for entry in entries if entry.get("status") == "ok" and entry.get("analysis")]
    known = sum(1 for entry in entries if entry)
    if not analyses:
        if known:
            return f'<p class="small">리딩 분석: 자막을 받은 영상 {known}개 중 분석 완료 0개 (LLM 키 설정 필요: OPENAI_API_KEY 또는 ANTHROPIC_API_KEY).</p>'
        return ""
    methods = Counter()
    tones = Counter()
    counts = []
    hooks = []
    takeaways = []
    for a in analyses:
        selection = a.get("card_selection") or {}
        methods[SELECTION_LABELS.get(selection.get("method"), selection.get("method") or "기타")] += 1
        if isinstance(selection.get("card_count"), (int, float)) and selection.get("card_count"):
            counts.append(float(selection["card_count"]))
        for tag in a.get("tone_tags") or []:
            tones[tag] += 1
        if a.get("opening_hook"):
            hooks.append(a["opening_hook"])
        if a.get("letter_concept_takeaway"):
            takeaways.append(a["letter_concept_takeaway"])
    total = len(analyses)
    method_text = " · ".join(f"{esc(label)} {count}개 ({count * 100 // total}%)" for label, count in methods.most_common(3))
    avg_cards = f"{sum(counts) / len(counts):.1f}장" if counts else "-"
    tone_text = "".join(f'<span class="tag">{esc(tag)} {count}</span>' for tag, count in tones.most_common(6))
    hook_items = "".join(f"<li>{esc(hook)}</li>" for hook in hooks[:5])
    takeaway_items = "".join(f"<li>{esc(item)}</li>" for item in takeaways[:4])
    return f"""
    <div class="callout patterns">
      <h3>이번 주 리딩 패턴 <small>(자막 분석 {total}개 영상)</small></h3>
      <div class="p-grid">
        <div><span>카드 선택 방식</span><div>{method_text}</div></div>
        <div><span>평균 카드 수</span><div>{avg_cards}</div></div>
        <div><span>톤 분포</span><div>{tone_text or '-'}</div></div>
      </div>
      {f'<details><summary>자주 쓰는 오프닝 훅 보기</summary><ul>{hook_items}</ul></details>' if hook_items else ''}
      {f'<details><summary>편지 컨셉 적용 포인트</summary><ul>{takeaway_items}</ul></details>' if takeaway_items else ''}
    </div>
    """


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
              <td><a href="{esc(post.get("url"))}" target="_blank" rel="noreferrer">{esc(post.get("title"))}</a>{render_analysis_toggle(post.get("url"))}</td>
              <td>{esc(classification.get("major_topic"))}</td>
              <td>{esc(classification.get("sub_topic"))}</td>
              <td>{esc(post.get("views"))}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def load_claude_weekly_tarot() -> Dict:
    if not CLAUDE_WEEKLY_TAROT_PATH.exists():
        return {}
    try:
        return load_json(CLAUDE_WEEKLY_TAROT_PATH)
    except Exception as error:
        return {"error": str(error)}


def fmt_num(value: Any) -> str:
    if value is None or value == "":
        return "-"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return esc(value)


def render_source_links(urls: List[str], limit: int = 3) -> str:
    return " ".join(
        f'<a href="{esc(url)}" target="_blank" rel="noreferrer">source</a>' for url in (urls or [])[:limit]
    )


def render_claude_legacy_items(data: Dict) -> str:
    """Schema v1: a hand-written {summary, items[]} file."""
    items = data.get("items", [])
    cards = []
    for item in items[:16]:
        cards.append(
            f"""
            <article class="card">
              <div class="meta">{esc(item.get("platform"))} · {esc(item.get("major_topic"))}</div>
              <h3>{esc(item.get("title"))}</h3>
              <p class="hook">{esc(item.get("signal"))}</p>
              <p>{esc(item.get("summary"))}</p>
              <div class="links">{render_source_links(item.get("source_urls", []))}</div>
            </article>
            """
        )
    return f"""
    <section id="claude-crawl">
      <h2>Claude 주간 크롤링</h2>
      <p>{esc(data.get("summary", "Claude에서 가져온 주간 타로 크롤링 요약입니다."))}</p>
      <div class="grid">{''.join(cards) if cards else '<p>No items</p>'}</div>
    </section>
    """


def render_claude_findings(summary: Dict) -> str:
    findings = summary.get("findings") or []
    recommendation = summary.get("top_recommendation") or ""
    rows = summary.get("rows") or []
    blocks = []
    if findings:
        items = "".join(f"<li>{esc(text)}</li>" for text in findings)
        blocks.append(f'<div class="callout"><h3>이번 주 3대 발견</h3><ol>{items}</ol></div>')
    if recommendation:
        blocks.append(f'<div class="callout accent"><h3>이번 주 1순위 추천</h3><p>{esc(recommendation)}</p></div>')
    if rows:
        table_rows = "".join(
            f"<tr><th>{esc(row.get('label'))}</th><td>{esc(row.get('value'))}</td></tr>" for row in rows[:40]
        )
        blocks.append(
            f"""
            <details class="summary-table">
              <summary>summary 탭 전체 보기 ({len(rows)}행)</summary>
              <table><tbody>{table_rows}</tbody></table>
            </details>
            """
        )
    return "".join(blocks)


def render_claude_ideas(ideas: List[Dict]) -> str:
    cards = []
    for idea in ideas[:8]:
        score = idea.get("priority_score")
        score_text = f"{score:g}/10" if isinstance(score, (int, float)) else ""
        cards.append(
            f"""
            <article class="card idea">
              <div class="meta">{esc(idea.get("major_topic"))} · {esc(idea.get("sub_topic"))} {f'· <span class="score">{esc(score_text)}</span>' if score_text else ''}</div>
              <h3>{esc(idea.get("idea_title"))}</h3>
              <p class="hook">{esc(idea.get("hook"))}</p>
              <p>{esc(idea.get("summary"))}</p>
              <div class="meta small">{esc(idea.get("recommended_format"))}</div>
              <div class="links">{render_source_links(idea.get("source_urls", []))}</div>
            </article>
            """
        )
    return "".join(cards) if cards else "<p>No ideas</p>"


def render_keyword_scoreboard(stats: List[Dict], has_metrics: bool) -> str:
    if not stats:
        return "<p>No keyword data</p>"
    maximum = max((item.get("included") or 0) for item in stats) or 1
    rows = []
    for item in stats:
        included = item.get("included") or 0
        width = int(included / maximum * 100)
        views = f" · {fmt_num(item.get('views'))} views" if has_metrics else ""
        rows.append(
            f"""
            <div class="bar-row">
              <span>{esc(item.get("keyword"))}</span>
              <div class="bar"><i style="width:{width}%"></i></div>
              <strong title="포함 {included} / 제외 {item.get('excluded') or 0}">{included}<small>/{item.get("collected") or 0}{esc(views)}</small></strong>
            </div>
            """
        )
    return "".join(rows)


def render_claude_raw_table(rows: List[Dict], has_metrics: bool, limit: int = 40) -> str:
    included = [row for row in rows if not row.get("exclude_reason")]
    if has_metrics:
        included.sort(key=lambda row: row.get("views") or 0, reverse=True)
    body = []
    for row in included[:limit]:
        title = row.get("title") or row.get("url")
        body.append(
            f"""
            <tr>
              <td>{esc(row.get("keyword"))}</td>
              <td><a href="{esc(row.get("url"))}" target="_blank" rel="noreferrer">{esc(title)}</a>{render_analysis_toggle(row.get("url"))}</td>
              <td>{esc(row.get("author"))}</td>
              <td>{fmt_num(row.get("views"))}</td>
              <td>{fmt_num(row.get("likes"))}</td>
              <td>{esc(row.get("published_at"))[:10]}</td>
            </tr>
            """
        )
    excluded_count = len(rows) - len(included)
    note = f"<p class=\"small\">강의·배우기 류 등 제외 {excluded_count}건은 표에서 숨김. 조회수/좋아요가 비어 있으면 그 주는 WebSearch 폴백 수집입니다.</p>" if rows else ""
    return f"""
    {note}
    <table>
      <thead><tr><th>Keyword</th><th>Title</th><th>Channel</th><th>Views</th><th>Likes</th><th>Published</th></tr></thead>
      <tbody>{''.join(body) if body else '<tr><td colspan="6">No rows</td></tr>'}</tbody>
    </table>
    """


def render_claude_classification(rows: List[Dict]) -> str:
    if not rows:
        return ""
    body = []
    for row in rows[:12]:
        confidence = row.get("confidence")
        confidence_text = f"{confidence:g}" if isinstance(confidence, (int, float)) else esc(confidence)
        body.append(
            f"""
            <tr>
              <td><strong>{esc(row.get("major_topic"))}</strong><br><span class="small">{esc(row.get("sub_topic"))}</span></td>
              <td>{esc(row.get("content_angle"))}</td>
              <td>{esc(row.get("target_emotion"))}</td>
              <td>{confidence_text}</td>
            </tr>
            """
        )
    return f"""
    <h3 class="sub">주제 분류 <small>(topic_classification)</small></h3>
    <table class="classification">
      <thead><tr><th>대주제 / 소주제</th><th>콘텐츠 앵글</th><th>타깃 감정</th><th>확신도</th></tr></thead>
      <tbody>{''.join(body)}</tbody>
    </table>
    """


def render_claude_archive(archive: List[Dict]) -> str:
    if not archive:
        return ""
    items = "".join(
        f'<li><a href="{esc(item.get("url"))}" target="_blank" rel="noreferrer">{esc(item.get("title"))}</a></li>'
        for item in archive[:12]
    )
    return f'<details class="archive"><summary>지난 주차 시트 ({len(archive)})</summary><ul>{items}</ul></details>'


def render_claude_section(data: Dict) -> str:
    if not data:
        return """
        <section id="claude-crawl">
          <h2>Claude 주간 크롤링</h2>
          <p>아직 연결된 Claude 주간 타로 크롤링 결과가 없습니다. <code>python scripts/fetch_claude_crawl.py</code>로 구글 드라이브의 최신 주간 시트를 가져오거나, 전달받은 xlsx를 <code>--xlsx</code>로 변환하면 이 섹션에 표시됩니다.</p>
        </section>
        """
    if data.get("error"):
        return f"""
        <section id="claude-crawl">
          <h2>Claude 주간 크롤링</h2>
          <p>Claude 결과 파일을 읽지 못했습니다: {esc(data.get("error"))}</p>
        </section>
        """
    if data.get("schema_version", 1) < 2:
        return render_claude_legacy_items(data)

    source = data.get("source") or {}
    stats = data.get("stats") or {}
    collection = data.get("collection") or {}
    has_metrics = bool(collection.get("has_view_metrics"))
    source_types = ", ".join(collection.get("source_types") or []) or "unknown"
    sheet_link = (
        f'<a href="{esc(source.get("url"))}" target="_blank" rel="noreferrer">{esc(source.get("title"))}</a>'
        if source.get("url")
        else esc(source.get("title"))
    )
    folder_link = (
        f' · <a href="{esc(source.get("folder_url"))}" target="_blank" rel="noreferrer">Drive 폴더</a>'
        if source.get("folder_url")
        else ""
    )
    mode_badge = (
        '<span class="badge ok">YouTube API 수집</span>'
        if has_metrics
        else '<span class="badge warn">WebSearch 폴백 수집 · 조회수 없음</span>'
    )

    return f"""
    <section id="claude-crawl" class="claude">
      <div class="section-head">
        <div>
          <h2>Claude 주간 크롤링 <span class="pill">레타 · 월요일 루틴</span></h2>
          <p class="small">Run date {esc(data.get("run_date") or "-")} · 소스 {sheet_link}{folder_link} · source_type: {esc(source_types)}</p>
        </div>
        {mode_badge}
      </div>

      <div class="stats compact">
        <div class="stat"><span>수집</span><strong>{stats.get("collected", 0)}</strong></div>
        <div class="stat"><span>분석 포함</span><strong>{stats.get("included", 0)}</strong></div>
        <div class="stat"><span>제외</span><strong>{stats.get("excluded", 0)}</strong></div>
        <div class="stat"><span>아이디어</span><strong>{stats.get("ideas", 0)}</strong></div>
      </div>

      {render_claude_findings(data.get("summary") or {})}

      <h3 class="sub">편지 컨셉 콘텐츠 아이디어</h3>
      <div class="grid">{render_claude_ideas(data.get("content_ideas") or [])}</div>

      {render_claude_classification(data.get("topic_classification") or [])}

      <h3 class="sub">키워드 성적표 <small>(분석 포함 / 수집)</small></h3>
      {render_keyword_scoreboard(data.get("keyword_stats") or [], has_metrics)}

      {render_reading_patterns([row.get("url") for row in data.get("raw_crawl") or [] if not row.get("exclude_reason")])}

      <h3 class="sub">raw_crawl</h3>
      {render_claude_raw_table(data.get("raw_crawl") or [], has_metrics)}

      {render_claude_archive(data.get("archive") or [])}
    </section>
    """


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build site/index.html from the latest research data.")
    parser.add_argument(
        "--pipeline-source",
        choices=["auto", "local", "sheet"],
        default=os.getenv("PIPELINE_SOURCE", "auto"),
        help="Where the pipeline data comes from: local output/*.json, the Google Sheet *_latest tabs, or auto (local if present).",
    )
    return parser.parse_args()


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    args = parse_args()
    raw_rows, classified_rows, ideas, pipeline_label = load_pipeline_data(args.pipeline_source)
    claude_weekly_tarot = load_claude_weekly_tarot()
    ANALYSES.clear()
    ANALYSES.update(load_transcript_analyses())

    major_counter = Counter()
    sub_counter = Counter()
    for item in classified_rows:
        classification = item.get("classification", {})
        if classification.get("is_educational"):
            continue
        major_counter[classification.get("major_topic") or "미분류"] += 1
        sub_counter[classification.get("sub_topic") or "미분류"] += 1

    generated_at = datetime.now(tz=KST).strftime("%Y-%m-%d %H:%M KST")
    claude_source_note = (
        f", {CLAUDE_WEEKLY_TAROT_PATH.name} (fetched {esc(str(claude_weekly_tarot.get('generated_at', ''))[:16])})"
        if claude_weekly_tarot and not claude_weekly_tarot.get("error")
        else ""
    )
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
    .small {{ font-size: .85rem; }}
    .section-head {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap; }}
    .section-head h2 {{ margin-bottom: 4px; }}
    .section-head p {{ margin: 0; }}
    .pill {{ display: inline-block; font-size: .7rem; font-weight: 700; letter-spacing: .02em; padding: 3px 9px; border-radius: 999px; background: #efe3f6; color: #6b3d8f; vertical-align: middle; margin-left: 6px; font-family: ui-sans-serif, system-ui, sans-serif; }}
    .badge {{ font-size: .78rem; font-weight: 700; padding: 6px 12px; border-radius: 999px; white-space: nowrap; font-family: ui-sans-serif, system-ui, sans-serif; }}
    .badge.ok {{ background: #e2f1ea; color: var(--accent-2); }}
    .badge.warn {{ background: #fbe9d8; color: var(--accent); }}
    .stats.compact {{ grid-template-columns: repeat(4, minmax(0, 1fr)); margin: 18px 0; }}
    .stats.compact .stat strong {{ font-size: 1.6rem; }}
    .callout {{ border-left: 4px solid #8b5aa8; background: #f7f0fb; border-radius: 14px; padding: 14px 18px; margin: 14px 0; }}
    .callout.accent {{ border-left-color: var(--accent); background: #fdf1e6; }}
    .callout h3 {{ margin: 0 0 8px; font-size: 1rem; }}
    .callout ol {{ margin: 0; padding-left: 20px; color: var(--ink); line-height: 1.6; }}
    .callout p {{ margin: 0; color: var(--ink); }}
    .sub {{ margin: 26px 0 12px; font-size: 1.05rem; }}
    .sub small {{ color: var(--muted); font-weight: 400; }}
    .score {{ color: #6b3d8f; }}
    .bar-row strong small {{ color: var(--muted); font-weight: 400; font-size: .75rem; }}
    .claude .bar-row {{ grid-template-columns: 140px 1fr auto; }}
    details {{ margin: 14px 0; }}
    details summary {{ cursor: pointer; color: var(--accent); font-family: ui-sans-serif, system-ui, sans-serif; font-size: .9rem; }}
    .summary-table th {{ width: 160px; color: var(--muted); font-weight: 600; }}
    .classification td:first-child {{ width: 160px; }}
    .classification td:nth-child(2) {{ color: var(--muted); }}
    .archive ul {{ margin: 8px 0 0; padding-left: 18px; font-family: ui-sans-serif, system-ui, sans-serif; font-size: .9rem; }}
    .tag {{ display: inline-block; font-size: .72rem; font-weight: 700; padding: 2px 8px; border-radius: 999px; background: #efe3f6; color: #6b3d8f; margin-left: 4px; font-family: ui-sans-serif, system-ui, sans-serif; vertical-align: middle; }}
    .tag.muted {{ background: #eee6dc; color: var(--muted); }}
    details.analysis {{ margin: 6px 0 0; }}
    details.analysis summary {{ font-size: .8rem; }}
    .a-body {{ margin-top: 8px; padding: 10px 12px; background: #f7f0fb; border-radius: 12px; font-family: ui-sans-serif, system-ui, sans-serif; font-size: .82rem; line-height: 1.5; }}
    .a-row {{ display: grid; grid-template-columns: 84px 1fr; gap: 8px; margin: 4px 0; }}
    .a-row > span {{ color: #6b3d8f; font-weight: 700; }}
    .a-meta {{ margin-top: 8px; color: var(--muted); font-size: .72rem; }}
    .patterns {{ border-left-color: var(--accent-2); background: #eef5f1; }}
    .p-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; font-family: ui-sans-serif, system-ui, sans-serif; font-size: .88rem; }}
    .p-grid > div > span {{ display: block; color: var(--muted); font-size: .75rem; margin-bottom: 4px; }}
    .patterns details {{ margin: 10px 0 0; }}
    .patterns ul {{ margin: 6px 0 0; padding-left: 18px; font-family: ui-sans-serif, system-ui, sans-serif; font-size: .85rem; color: var(--ink); }}
    @media (max-width: 760px) {{
      .stats, .grid {{ grid-template-columns: 1fr; }}
      .stats.compact {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .claude .bar-row {{ grid-template-columns: 100px 1fr auto; }}
      .p-grid {{ grid-template-columns: 1fr; }}
      .a-row {{ grid-template-columns: 1fr; }}
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
      <p>주간 타로 제너럴 리딩 콘텐츠 리서치 결과입니다. 원본 데이터는 Google Sheets에 기록되고, 이 페이지는 최신 파이프라인 실행 결과와 <a href="#claude-crawl">Claude 주간 크롤링 루틴</a> 결과를 함께 요약합니다.</p>
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

    {render_claude_section(claude_weekly_tarot)}

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
      {render_reading_patterns([item.get("post", {}).get("url") for item in classified_rows if not item.get("classification", {}).get("is_educational")])}
      <table>
        <thead><tr><th>Platform</th><th>Title</th><th>Major</th><th>Sub</th><th>Views</th></tr></thead>
        <tbody>{render_topic_table(classified_rows)}</tbody>
      </table>
    </section>

    <footer>Pipeline source: {esc(pipeline_label)}{claude_source_note}</footer>
  </main>
</body>
</html>
"""

    SITE_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "index.html").write_text(html_body, encoding="utf-8")


if __name__ == "__main__":
    main()
