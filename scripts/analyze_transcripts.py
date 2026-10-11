"""Fetch YouTube auto-captions for this week's tarot videos and analyze how each reader runs the reading.

Sources of video URLs:
  * the latest pipeline output (output/raw_posts_*.json + classified_topics_*.json, non-educational rows)
  * the Claude weekly crawl (data/claude_weekly_tarot.json, rows without exclude_reason)

For each new video the script
  1. downloads the Korean transcript (manual captions first, then auto-generated) with youtube-transcript-api
     (no API key needed), and
  2. asks the configured LLM (OpenAI or Claude, see llm_client.py) for a fixed-schema analysis: opening hook, card-selection staging,
     reading structure, tone, recurring phrases, engagement, CTA, and a takeaway for Leta's letter concept.

Results are cached in data/transcript_analysis.json keyed by video id, so a video is only analyzed once.
Commit that file after a local run: GitHub Actions runners are often blocked from downloading captions,
so the committed cache is what keeps the dashboard populated.

Agent mode (no API key: a Claude session does the analysis itself):
    python scripts/analyze_transcripts.py --no-llm              # 1) download captions into the cache
    python scripts/analyze_transcripts.py --list-pending        # 2) write output/transcripts/<id>.txt + print the list
    python scripts/analyze_transcripts.py --apply analyses.json # 3) merge {video_id: analysis} written by the session

Usage:
    python scripts/analyze_transcripts.py                 # analyze new videos (default limit 60)
    python scripts/analyze_transcripts.py --limit 10
    python scripts/analyze_transcripts.py --no-llm        # transcripts only, skip OpenAI
    python scripts/analyze_transcripts.py --retry-errors  # retry videos that previously failed
    python scripts/analyze_transcripts.py --video dQw4w9WgXcQ   # one specific video id/url
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from llm_client import active_model, active_provider, call_llm_json  # noqa: E402


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
CLAUDE_CRAWL_PATH = ROOT / "data" / "claude_weekly_tarot.json"
CACHE_PATH = ROOT / "data" / "transcript_analysis.json"
PENDING_DIR = ROOT / "output" / "transcripts"
KST = timezone(timedelta(hours=9))

MAX_TRANSCRIPT_CHARS = 14000
LANGUAGES = ["ko", "ko-KR"]
VIDEO_ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([\w-]{11})")

ANALYSIS_KEYS = [
    "opening_hook",
    "card_selection",
    "reading_structure",
    "tone",
    "tone_tags",
    "recurring_phrases",
    "audience_engagement",
    "cta",
    "letter_concept_takeaway",
]

SYSTEM_PROMPT = (
    "당신은 한국어 유튜브 타로 리딩 영상의 자막을 읽고, 그 리더가 리딩을 '어떻게' 진행하는지 분석하는 콘텐츠 분석가다. "
    "운세 내용 자체가 아니라 진행 방식·연출·말투·구조를 분석한다. 반드시 아래 키를 가진 JSON 객체만 반환한다.\n"
    "- opening_hook: 첫 30초의 훅을 한 문장으로 (string)\n"
    "- card_selection: {\"method\": \"pick_a_card\"|\"single_spread\"|\"none\"|\"other\", \"card_count\": 숫자 또는 null, \"staging\": 카드 선택 연출 설명 한 문장}\n"
    "- reading_structure: 영상 진행 순서를 3~6개 단계로 (string 배열, 각 10자 내외)\n"
    "- tone: 말투와 톤을 한 문장으로 (string)\n"
    "- tone_tags: 다음 중 최대 3개 (string 배열): 위로, 팩폭, 현실조언, 긍정, 신비, 친근, 설명, 자극\n"
    "- recurring_phrases: 반복해서 쓰는 표현 최대 3개 (string 배열)\n"
    "- audience_engagement: 댓글·좋아요·참여를 유도하는 방식 한 문장 (string)\n"
    "- cta: 마무리에서 하는 행동 유도 한 문장 (string)\n"
    "- letter_concept_takeaway: 타로 상담가 레타의 '타로에게 보내는 편지' 컨셉(편지봉투 선택 연출, 위로 톤)에 적용하거나 차별화할 점 1~2문장 (string)\n"
    "자막이 부족해서 판단할 수 없는 항목은 빈 문자열, 빈 배열 또는 null로 둔다."
)


def log(message: str) -> None:
    print(f"[analyze_transcripts] {message}", file=sys.stderr)


def now_iso() -> str:
    return datetime.now(tz=KST).isoformat(timespec="seconds")


def video_id_from_url(url: str) -> Optional[str]:
    if not url:
        return None
    if re.fullmatch(r"[\w-]{11}", url):
        return url
    match = VIDEO_ID_RE.search(url)
    return match.group(1) if match else None


# --------------------------------------------------------------------------- targets


def latest_json(prefix: str) -> Optional[Path]:
    files = sorted(OUTPUT_DIR.glob(f"{prefix}_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    return files[0] if files else None


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def collect_targets() -> List[Dict[str, Any]]:
    """Return {video_id, url, title, keyword, source} for every included YouTube video we know about."""
    targets: Dict[str, Dict[str, Any]] = {}

    classified_path = latest_json("classified_topics")
    if classified_path:
        for item in load_json(classified_path):
            post = item.get("post", {})
            classification = item.get("classification", {})
            if classification.get("is_educational"):
                continue
            if (post.get("platform") or "").lower() != "youtube":
                continue
            video_id = video_id_from_url(post.get("url", ""))
            if video_id and video_id not in targets:
                targets[video_id] = {
                    "video_id": video_id,
                    "url": post.get("url"),
                    "title": post.get("title"),
                    "keyword": post.get("keyword"),
                    "source": "pipeline",
                }

    if CLAUDE_CRAWL_PATH.exists():
        try:
            crawl = load_json(CLAUDE_CRAWL_PATH)
        except Exception as error:  # noqa: BLE001
            log(f"could not read {CLAUDE_CRAWL_PATH.name}: {error}")
            crawl = {}
        for row in crawl.get("raw_crawl", []) if isinstance(crawl, dict) else []:
            if row.get("exclude_reason"):
                continue
            video_id = video_id_from_url(row.get("url", ""))
            if video_id and video_id not in targets:
                targets[video_id] = {
                    "video_id": video_id,
                    "url": row.get("url"),
                    "title": row.get("title"),
                    "keyword": row.get("keyword"),
                    "source": "claude",
                }

    return list(targets.values())


# --------------------------------------------------------------------------- transcript


class TranscriptBlocked(RuntimeError):
    """YouTube refused the request (datacenter IP, rate limit). Stop trying for this run."""


def fetch_transcript(video_id: str) -> Dict[str, Any]:
    from youtube_transcript_api import YouTubeTranscriptApi

    api = YouTubeTranscriptApi()
    try:
        transcript_list = api.list(video_id)
        transcript = None
        for finder in (transcript_list.find_manually_created_transcript, transcript_list.find_generated_transcript):
            try:
                transcript = finder(LANGUAGES)
                break
            except Exception:  # noqa: BLE001 - try the next finder
                continue
        if transcript is None:
            raise LookupError("no korean transcript")
        fetched = transcript.fetch()
        text = " ".join(snippet.text.strip() for snippet in fetched if snippet.text and snippet.text.strip())
        text = re.sub(r"\[(음악|박수|웃음)\]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return {
            "lang": transcript.language_code,
            "generated": bool(transcript.is_generated),
            "chars": len(text),
            "excerpt": text[:240],
            "text": text,
        }
    except Exception as error:  # noqa: BLE001
        name = type(error).__name__
        if name in {"RequestBlocked", "IpBlocked", "TooManyRequests"}:
            raise TranscriptBlocked(f"{name}: {str(error)[:200]}") from error
        raise LookupError(f"{name}: {str(error)[:200]}") from error


# --------------------------------------------------------------------------- llm


def analyze_transcript(target: Dict[str, Any], transcript_text: str) -> Optional[Dict[str, Any]]:
    truncated = transcript_text[:MAX_TRANSCRIPT_CHARS]
    user_prompt = (
        f"영상 제목: {target.get('title') or ''}\n"
        f"검색 키워드: {target.get('keyword') or ''}\n"
        f"자막 길이: {len(transcript_text)}자 (아래는 앞부분 {len(truncated)}자)\n\n"
        f"자막:\n{truncated}"
    )
    result = call_llm_json(SYSTEM_PROMPT, user_prompt, max_tokens=2048)
    if result is None:
        return None
    return normalize_analysis(result)


def normalize_analysis(result: Dict[str, Any]) -> Dict[str, Any]:
    analysis = {key: result.get(key) for key in ANALYSIS_KEYS}
    selection = analysis.get("card_selection") or {}
    if not isinstance(selection, dict):
        selection = {"method": "other", "card_count": None, "staging": str(selection)}
    analysis["card_selection"] = {
        "method": selection.get("method") or "other",
        "card_count": selection.get("card_count"),
        "staging": selection.get("staging") or "",
    }
    for list_key in ("reading_structure", "tone_tags", "recurring_phrases"):
        value = analysis.get(list_key)
        analysis[list_key] = [str(item) for item in value][:6] if isinstance(value, list) else []
    return analysis


# --------------------------------------------------------------------------- cache


def load_cache() -> Dict[str, Any]:
    if CACHE_PATH.exists():
        try:
            data = load_json(CACHE_PATH)
            if isinstance(data, dict) and isinstance(data.get("videos"), dict):
                return data
        except Exception as error:  # noqa: BLE001
            log(f"cache unreadable, starting fresh: {error}")
    return {"version": 1, "updated_at": "", "videos": {}}


def save_cache(cache: Dict[str, Any]) -> None:
    cache["updated_at"] = now_iso()
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- agent mode


def list_pending(cache: Dict[str, Any]) -> int:
    """Write every cached-but-unanalyzed transcript to output/transcripts/<id>.txt and print the list as JSON."""
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    pending = []
    for video_id, entry in cache["videos"].items():
        text = (entry.get("transcript") or {}).get("text")
        if entry.get("status") in {"no_llm", "llm_error"} and text:
            path = PENDING_DIR / f"{video_id}.txt"
            path.write_text(
                f"# {entry.get('title') or ''}\n# keyword: {entry.get('keyword') or ''}\n# url: {entry.get('url') or ''}\n\n{text[:MAX_TRANSCRIPT_CHARS]}",
                encoding="utf-8",
            )
            pending.append({"video_id": video_id, "title": entry.get("title"), "keyword": entry.get("keyword"), "chars": len(text), "path": str(path)})
    print(json.dumps({"schema": {key: "..." for key in ANALYSIS_KEYS}, "system_prompt": SYSTEM_PROMPT, "pending": pending}, ensure_ascii=False, indent=2))
    log(f"{len(pending)} transcripts waiting for analysis in {PENDING_DIR}")
    return 0


def apply_analyses(cache: Dict[str, Any], path: Path, label: str) -> int:
    """Merge analyses written by an agent: a JSON object {video_id: analysis} or a list of {video_id, ...analysis}."""
    data = load_json(path)
    items: Dict[str, Dict[str, Any]] = {}
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("video_id"):
                items[item["video_id"]] = item
    elif isinstance(data, dict):
        items = {key: value for key, value in data.items() if isinstance(value, dict)}
    applied, skipped = 0, []
    for video_id, raw in items.items():
        entry = cache["videos"].get(video_id)
        if not entry:
            skipped.append(video_id)
            continue
        entry.update({"status": "ok", "error": None, "analysis": normalize_analysis(raw), "model": label, "analyzed_at": now_iso()})
        (entry.get("transcript") or {}).pop("text", None)
        applied += 1
        pending_file = PENDING_DIR / f"{video_id}.txt"
        if pending_file.exists():
            pending_file.unlink()
    save_cache(cache)
    log(f"applied {applied} analyses" + (f", unknown video ids skipped: {skipped}" if skipped else ""))
    return 0


# --------------------------------------------------------------------------- main


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=60, help="Max new videos to process this run")
    parser.add_argument("--no-llm", action="store_true", help="Fetch transcripts only, skip the LLM analysis")
    parser.add_argument("--retry-errors", action="store_true", help="Retry videos cached with an error status")
    parser.add_argument("--video", action="append", default=[], help="Specific video id or URL (repeatable)")
    parser.add_argument("--sleep", type=float, default=1.0, help="Seconds to wait between caption downloads")
    parser.add_argument("--list-pending", action="store_true", help="Agent mode: dump unanalyzed transcripts to output/transcripts/ and list them")
    parser.add_argument("--apply", type=Path, help="Agent mode: merge a JSON file of analyses ({video_id: analysis}) into the cache")
    parser.add_argument("--label", default="claude-session", help="Model label recorded with --apply")
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    load_dotenv(ROOT / ".env")
    args = parse_args(argv)
    cache = load_cache()
    videos: Dict[str, Any] = cache["videos"]

    if args.list_pending:
        return list_pending(cache)
    if args.apply:
        return apply_analyses(cache, args.apply, args.label)

    if args.video:
        targets = []
        for raw in args.video:
            video_id = video_id_from_url(raw)
            if video_id:
                targets.append({"video_id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}", "title": "", "keyword": "", "source": "manual"})
    else:
        targets = collect_targets()

    pending = []
    llm_available = bool(active_provider()) and not args.no_llm
    for target in targets:
        entry = videos.get(target["video_id"])
        if entry is None:
            pending.append(target)
            continue
        status = entry.get("status")
        has_text = bool((entry.get("transcript") or {}).get("text"))
        if status == "ok":
            continue
        if status in {"no_llm", "llm_error"}:
            # Transcript cached but not analyzed: re-download if the text is missing, analyze when an LLM is available.
            if not has_text or (llm_available and (status == "no_llm" or args.retry_errors)):
                pending.append(target)
            continue
        if status in {"no_transcript", "blocked"} and args.retry_errors:
            pending.append(target)

    pending.sort(key=lambda item: 0 if item.get("source") == "claude" else 1)
    log(f"{len(targets)} candidate videos, {len(pending)} to process (limit {args.limit})")
    pending = pending[: args.limit]

    processed = 0
    blocked = False
    for target in pending:
        video_id = target["video_id"]
        entry = videos.get(video_id) or {}
        entry.update({k: target.get(k) for k in ("video_id", "url", "title", "keyword", "source") if target.get(k) or k not in entry})

        transcript_text = ""
        cached_transcript = entry.get("transcript") or {}
        if entry.get("status") in {"no_llm", "llm_error"} and cached_transcript.get("text"):
            transcript_text = cached_transcript["text"]
        else:
            try:
                transcript = fetch_transcript(video_id)
                transcript_text = transcript.pop("text")
                entry["transcript"] = transcript
                entry["fetched_at"] = now_iso()
            except TranscriptBlocked as error:
                log(f"{video_id}: blocked by YouTube ({error}). Stopping caption downloads for this run.")
                blocked = True
                break
            except LookupError as error:
                entry.update({"status": "no_transcript", "error": str(error), "fetched_at": now_iso(), "analysis": None})
                videos[video_id] = entry
                log(f"{video_id}: no transcript ({error})")
                time.sleep(args.sleep)
                continue

        if args.no_llm or not active_provider():
            entry.update({"status": "no_llm", "error": None, "analysis": entry.get("analysis")})
            entry.setdefault("transcript", {})["text"] = transcript_text  # keep so a later run can analyze without re-downloading
            videos[video_id] = entry
            processed += 1
            log(f"{video_id}: transcript cached ({len(transcript_text)} chars), analysis skipped")
            time.sleep(args.sleep)
            continue

        try:
            analysis = analyze_transcript(target | {"title": entry.get("title"), "keyword": entry.get("keyword")}, transcript_text)
            entry.update(
                {
                    "status": "ok",
                    "error": None,
                    "analysis": analysis,
                    "model": f"{active_provider()}:{active_model()}",
                    "analyzed_at": now_iso(),
                }
            )
            entry.get("transcript", {}).pop("text", None)
            log(f"{video_id}: analyzed ({entry['transcript'].get('chars', 0)} chars)")
        except Exception as error:  # noqa: BLE001
            entry.update({"status": "llm_error", "error": f"{type(error).__name__}: {str(error)[:200]}", "analysis": None})
            entry.setdefault("transcript", {})["text"] = transcript_text
            log(f"{video_id}: analysis failed ({entry['error']})")
        videos[video_id] = entry
        processed += 1
        save_cache(cache)
        time.sleep(args.sleep)

    save_cache(cache)
    ok = sum(1 for entry in videos.values() if entry.get("status") == "ok")
    log(f"done: processed {processed} this run, {ok} analyzed videos in cache ({len(videos)} total){' — blocked, using cached results' if blocked else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
