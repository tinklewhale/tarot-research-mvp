import csv
import json
import os
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import gspread
import requests
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "topics.json"
MANUAL_SOURCES_PATH = ROOT / "data" / "manual_sources.csv"
OUTPUT_DIR = ROOT / "output"
KST = timezone(timedelta(hours=9))


@dataclass
class Post:
    platform: str
    keyword: str
    title: str
    description: str
    hashtags: str
    author: str
    published_at: str
    url: str
    views: int
    likes: int
    source_type: str
    raw_text: str


def load_config() -> Dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def now_kst() -> datetime:
    return datetime.now(tz=KST)


def isoformat_or_empty(value: Optional[str]) -> str:
    return value or ""


def read_manual_sources() -> List[Post]:
    if not MANUAL_SOURCES_PATH.exists():
        return []

    posts: List[Post] = []
    with MANUAL_SOURCES_PATH.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            if not row.get("url"):
                continue
            title = (row.get("title") or "").strip()
            description = (row.get("description") or "").strip()
            hashtags = (row.get("hashtags") or "").strip()
            posts.append(
                Post(
                    platform=(row.get("platform") or "manual").strip(),
                    keyword=(row.get("keyword") or "").strip(),
                    title=title,
                    description=description,
                    hashtags=hashtags,
                    author=(row.get("author") or "").strip(),
                    published_at=isoformat_or_empty(row.get("published_at")),
                    url=(row.get("url") or "").strip(),
                    views=safe_int(row.get("views")),
                    likes=safe_int(row.get("likes")),
                    source_type="manual_seed",
                    raw_text=" ".join([title, description, hashtags]).strip(),
                )
            )
    return posts


def safe_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def youtube_headers() -> Dict[str, str]:
    return {"Accept": "application/json"}


def collect_youtube_posts(config: Dict) -> List[Post]:
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        print("Skipping YouTube: missing YOUTUBE_API_KEY")
        return []

    max_results = safe_int(os.getenv("YOUTUBE_MAX_RESULTS_PER_QUERY", "10")) or 10
    published_after = (now_kst() - timedelta(days=7)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    search_url = "https://www.googleapis.com/youtube/v3/search"
    videos_url = "https://www.googleapis.com/youtube/v3/videos"
    posts: List[Post] = []

    for query in config.get("youtube_queries", []):
        params = {
            "key": api_key,
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": max_results,
            "order": "relevance",
            "publishedAfter": published_after,
            "regionCode": "KR",
            "relevanceLanguage": "ko",
        }
        response = requests.get(search_url, headers=youtube_headers(), params=params, timeout=30)
        response.raise_for_status()
        items = response.json().get("items", [])
        video_ids = [item["id"]["videoId"] for item in items if item.get("id", {}).get("videoId")]
        stats_by_id = fetch_youtube_stats(videos_url, api_key, video_ids)

        for item in items:
            video_id = item.get("id", {}).get("videoId")
            if not video_id:
                continue
            snippet = item.get("snippet", {})
            stats = stats_by_id.get(video_id, {})
            title = snippet.get("title", "").strip()
            description = snippet.get("description", "").strip()
            posts.append(
                Post(
                    platform="youtube",
                    keyword=query,
                    title=title,
                    description=description,
                    hashtags=extract_hashtags(" ".join([title, description])),
                    author=snippet.get("channelTitle", "").strip(),
                    published_at=isoformat_or_empty(snippet.get("publishedAt")),
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    views=safe_int(stats.get("viewCount")),
                    likes=safe_int(stats.get("likeCount")),
                    source_type="youtube_api",
                    raw_text=" ".join([title, description]).strip(),
                )
            )
    return posts


def fetch_youtube_stats(videos_url: str, api_key: str, video_ids: List[str]) -> Dict[str, Dict]:
    if not video_ids:
        return {}

    params = {
        "key": api_key,
        "part": "statistics",
        "id": ",".join(video_ids),
    }
    response = requests.get(videos_url, headers=youtube_headers(), params=params, timeout=30)
    response.raise_for_status()
    items = response.json().get("items", [])
    return {item["id"]: item.get("statistics", {}) for item in items}


def collect_instagram_posts(config: Dict) -> List[Post]:
    access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
    ig_user_id = os.getenv("INSTAGRAM_IG_USER_ID", "").strip()
    graph_version = os.getenv("META_GRAPH_VERSION", "v23.0").strip()
    if not access_token or not ig_user_id:
        print("Skipping Instagram: missing INSTAGRAM_ACCESS_TOKEN or INSTAGRAM_IG_USER_ID")
        return []

    posts: List[Post] = []
    base_url = f"https://graph.facebook.com/{graph_version}"

    for hashtag in config.get("instagram_hashtags", []):
        tag_response = requests.get(
            f"{base_url}/ig_hashtag_search",
            params={"user_id": ig_user_id, "q": hashtag, "access_token": access_token},
            timeout=30,
        )
        tag_response.raise_for_status()
        tag_data = tag_response.json().get("data", [])
        if not tag_data:
            continue

        hashtag_id = tag_data[0]["id"]
        media_response = requests.get(
            f"{base_url}/{hashtag_id}/recent_media",
            params={
                "user_id": ig_user_id,
                "fields": "id,caption,media_type,permalink,timestamp,like_count",
                "limit": 25,
                "access_token": access_token,
            },
            timeout=30,
        )
        media_response.raise_for_status()
        for item in media_response.json().get("data", []):
            caption = (item.get("caption") or "").strip()
            title = caption.splitlines()[0][:120] if caption else hashtag
            posts.append(
                Post(
                    platform="instagram",
                    keyword=hashtag,
                    title=title,
                    description=caption,
                    hashtags=extract_hashtags(caption),
                    author="",
                    published_at=isoformat_or_empty(item.get("timestamp")),
                    url=(item.get("permalink") or "").strip(),
                    views=0,
                    likes=safe_int(item.get("like_count")),
                    source_type="instagram_graph_api",
                    raw_text=" ".join([title, caption]).strip(),
                )
            )
    return posts


def extract_hashtags(text: str) -> str:
    tags = []
    for token in text.replace("\n", " ").split():
        cleaned = token.strip(",.?!:;()[]{}")
        if cleaned.startswith("#"):
            tags.append(cleaned)
    return " ".join(dict.fromkeys(tags))


def dedupe_posts(posts: List[Post]) -> List[Post]:
    seen = set()
    unique_posts = []
    for post in posts:
        key = post.url.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        unique_posts.append(post)
    return unique_posts


def detect_educational(post: Post, exclude_keywords: List[str]) -> Optional[str]:
    haystack = f"{post.title} {post.description}".lower()
    for keyword in exclude_keywords:
        if keyword.lower() in haystack:
            return keyword
    return None


def heuristic_major_topic(post: Post, config: Dict) -> str:
    text = f"{post.title} {post.description} {post.hashtags}".lower()
    for major_topic, keywords in config.get("major_topic_keywords", {}).items():
        for keyword in keywords:
            if keyword.lower() in text:
                return major_topic
    return "기타"


def heuristic_sub_topic(post: Post) -> str:
    text = f"{post.title} {post.description}".lower()
    rules = [
        ("이번달 운세", ["이번달", "이달", "월간"]),
        ("연락 시기", ["연락", "언제 연락", "몇 월"]),
        ("재회 가능성", ["재회 가능", "재회", "돌아올"]),
        ("상대 속마음", ["속마음", "마음", "진심"]),
        ("인연 외모", ["외모", "얼굴상", "생김새"]),
        ("인연 성격", ["성격", "성향", "특징"]),
        ("취업 합격 시기", ["취업", "합격", "면접"]),
        ("이직 타이밍", ["이직", "퇴사"]),
        ("돈 들어오는 시기", ["돈", "재물", "수입"]),
        ("반려동물 마음", ["반려동물", "강아지", "고양이", "펫"])
    ]
    for label, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return label
    return post.keyword or "일반 리딩"


def call_openai_json(system_prompt: str, user_prompt: str) -> Optional[Dict]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()
    if not api_key:
        return None

    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        },
        timeout=60,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return json.loads(content)


def classify_post(post: Post, config: Dict, exclude_reason: Optional[str]) -> Dict:
    if exclude_reason:
        return {
            "is_educational": True,
            "major_topic": "",
            "sub_topic": "",
            "content_angle": "",
            "target_emotion": "",
            "confidence": 1.0,
            "exclude_reason": exclude_reason,
        }

    system_prompt = (
        "당신은 한국어 타로 리딩 콘텐츠 분석기다. "
        "교육형인지 판별하고, 교육형이 아니면 대주제 1개와 소주제 1개를 정한다. "
        "반드시 JSON만 반환한다."
    )
    user_prompt = (
        "대주제 후보: " + ", ".join(config.get("major_topics", [])) + "\n"
        "출력 키: is_educational, major_topic, sub_topic, content_angle, target_emotion, confidence, exclude_reason\n"
        f"제목: {post.title}\n"
        f"설명: {post.description}\n"
        f"해시태그: {post.hashtags}\n"
    )

    try:
        result = call_openai_json(system_prompt, user_prompt)
        if result:
            return {
                "is_educational": bool(result.get("is_educational", False)),
                "major_topic": result.get("major_topic", "") or heuristic_major_topic(post, config),
                "sub_topic": result.get("sub_topic", "") or heuristic_sub_topic(post),
                "content_angle": result.get("content_angle", "") or "타로 리딩형 숏폼",
                "target_emotion": result.get("target_emotion", "") or "",
                "confidence": float(result.get("confidence", 0.7)),
                "exclude_reason": result.get("exclude_reason", "") or "",
            }
    except Exception as error:
        print(f"OpenAI classification fallback for {post.url}: {error}")

    return {
        "is_educational": False,
        "major_topic": heuristic_major_topic(post, config),
        "sub_topic": heuristic_sub_topic(post),
        "content_angle": "타로 리딩형 숏폼",
        "target_emotion": "",
        "confidence": 0.45,
        "exclude_reason": "",
    }


def build_weekly_ideas(classified_rows: List[Dict], config: Dict) -> List[Dict]:
    usable_rows = [row for row in classified_rows if not row["classification"]["is_educational"]]
    if not usable_rows:
        return []

    sample_rows = usable_rows[:30]
    summaries = []
    for row in sample_rows:
        summaries.append(
            {
                "platform": row["post"].platform,
                "title": row["post"].title,
                "major_topic": row["classification"]["major_topic"],
                "sub_topic": row["classification"]["sub_topic"],
                "url": row["post"].url,
            }
        )

    system_prompt = (
        "당신은 타로 숏폼 콘텐츠 기획자다. "
        "리서치 결과를 바탕으로 중복되지 않는 한국어 콘텐츠 아이디어를 제안한다. "
        "반드시 JSON 객체만 반환한다."
    )
    user_prompt = (
        "다음은 이번 주 타로 리딩 콘텐츠 리서치 샘플이다.\n"
        f"{json.dumps(summaries, ensure_ascii=False)}\n"
        "10개의 아이디어를 제안하라. "
        "출력 형식: {\"ideas\": [{\"idea_title\": \"\", \"major_topic\": \"\", \"sub_topic\": \"\", "
        "\"hook\": \"\", \"summary\": \"\", \"recommended_format\": \"shorts|reels|threads\", "
        "\"source_urls\": [], \"priority_score\": 0}]}"
    )

    try:
        result = call_openai_json(system_prompt, user_prompt)
        ideas = result.get("ideas", []) if result else []
        if ideas:
            return ideas[:10]
    except Exception as error:
        print(f"OpenAI idea generation fallback: {error}")

    topic_counts = Counter((row["classification"]["major_topic"], row["classification"]["sub_topic"]) for row in usable_rows)
    ideas = []
    for index, ((major_topic, sub_topic), count) in enumerate(topic_counts.most_common(10), start=1):
        source_urls = [row["post"].url for row in usable_rows if row["classification"]["major_topic"] == major_topic][:3]
        ideas.append(
            {
                "idea_title": f"{major_topic} {sub_topic} 리딩 {index}",
                "major_topic": major_topic,
                "sub_topic": sub_topic,
                "hook": f"지금 가장 궁금한 {sub_topic}, 카드로 바로 확인해볼까요?",
                "summary": f"최근 리서치에서 반복된 {major_topic}/{sub_topic} 수요를 반영한 숏폼 아이디어입니다.",
                "recommended_format": "reels",
                "source_urls": source_urls,
                "priority_score": min(count, 10),
            }
        )
    return ideas


def ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def write_local_outputs(raw_rows: List[Dict], classified_rows: List[Dict], weekly_ideas: List[Dict]) -> None:
    ensure_output_dir()
    timestamp = now_kst().strftime("%Y%m%d-%H%M%S")
    serialized_classified_rows = []
    for row in classified_rows:
        serialized_classified_rows.append(
            {
                "run_date": row["run_date"],
                "post": row["post"].__dict__,
                "classification": row["classification"],
            }
        )
    with (OUTPUT_DIR / f"raw_posts_{timestamp}.json").open("w", encoding="utf-8") as file:
        json.dump(raw_rows, file, ensure_ascii=False, indent=2)
    with (OUTPUT_DIR / f"classified_topics_{timestamp}.json").open("w", encoding="utf-8") as file:
        json.dump(serialized_classified_rows, file, ensure_ascii=False, indent=2)
    with (OUTPUT_DIR / f"weekly_ideas_{timestamp}.json").open("w", encoding="utf-8") as file:
        json.dump(weekly_ideas, file, ensure_ascii=False, indent=2)


def get_gspread_client():
    service_account_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
    spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "").strip()
    if not service_account_file or not spreadsheet_id:
        print("Skipping Google Sheets: missing GOOGLE_SERVICE_ACCOUNT_FILE or GOOGLE_SHEETS_SPREADSHEET_ID")
        return None, None

    credentials = Credentials.from_service_account_file(
        service_account_file,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    client = gspread.authorize(credentials)
    spreadsheet = client.open_by_key(spreadsheet_id)
    return client, spreadsheet


def get_or_create_worksheet(spreadsheet, title: str, headers: List[str]):
    try:
        worksheet = spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=title, rows=1000, cols=max(len(headers), 12))
        worksheet.append_row(headers)
        return worksheet

    if not worksheet.get_all_values():
        worksheet.append_row(headers)
    return worksheet


def append_sheet_rows(raw_rows: List[Dict], classified_rows: List[Dict], weekly_ideas: List[Dict]) -> None:
    _, spreadsheet = get_gspread_client()
    if not spreadsheet:
        return

    raw_headers = [
        "run_date", "platform", "keyword", "title", "description", "hashtags",
        "author", "published_at", "url", "views", "likes", "raw_text",
        "exclude_reason", "source_type"
    ]
    classified_headers = [
        "run_date", "platform", "title", "url", "major_topic", "sub_topic",
        "content_angle", "target_emotion", "evidence_excerpt", "confidence"
    ]
    idea_headers = [
        "run_date", "idea_title", "major_topic", "sub_topic", "hook",
        "summary", "recommended_format", "source_urls", "priority_score"
    ]

    raw_sheet = get_or_create_worksheet(
        spreadsheet,
        os.getenv("GOOGLE_SHEETS_RAW_SHEET", "raw_posts"),
        raw_headers,
    )
    classified_sheet = get_or_create_worksheet(
        spreadsheet,
        os.getenv("GOOGLE_SHEETS_CLASSIFIED_SHEET", "classified_topics"),
        classified_headers,
    )
    ideas_sheet = get_or_create_worksheet(
        spreadsheet,
        os.getenv("GOOGLE_SHEETS_IDEAS_SHEET", "weekly_ideas"),
        idea_headers,
    )

    if raw_rows:
        raw_sheet.append_rows([[row.get(header, "") for header in raw_headers] for row in raw_rows], value_input_option="USER_ENTERED")
    if classified_rows:
        formatted = []
        for row in classified_rows:
            post = row["post"]
            classification = row["classification"]
            formatted.append([
                row["run_date"],
                post.platform,
                post.title,
                post.url,
                classification["major_topic"],
                classification["sub_topic"],
                classification["content_angle"],
                classification["target_emotion"],
                post.raw_text[:300],
                classification["confidence"],
            ])
        classified_sheet.append_rows(formatted, value_input_option="USER_ENTERED")
    if weekly_ideas:
        idea_rows = []
        run_date = now_kst().strftime("%Y-%m-%d")
        for idea in weekly_ideas:
            idea_rows.append([
                run_date,
                idea.get("idea_title", ""),
                idea.get("major_topic", ""),
                idea.get("sub_topic", ""),
                idea.get("hook", ""),
                idea.get("summary", ""),
                idea.get("recommended_format", ""),
                "\n".join(idea.get("source_urls", [])),
                idea.get("priority_score", ""),
            ])
        ideas_sheet.append_rows(idea_rows, value_input_option="USER_ENTERED")


def main() -> None:
    load_dotenv(ROOT / ".env")
    config = load_config()
    run_date = now_kst().strftime("%Y-%m-%d")

    collected_posts = []
    collected_posts.extend(collect_youtube_posts(config))
    collected_posts.extend(collect_instagram_posts(config))
    collected_posts.extend(read_manual_sources())
    collected_posts = dedupe_posts(collected_posts)

    raw_rows = []
    classified_rows = []
    for post in collected_posts:
        exclude_reason = detect_educational(post, config.get("exclude_keywords", []))
        classification = classify_post(post, config, exclude_reason)
        raw_rows.append(
            {
                "run_date": run_date,
                "platform": post.platform,
                "keyword": post.keyword,
                "title": post.title,
                "description": post.description,
                "hashtags": post.hashtags,
                "author": post.author,
                "published_at": post.published_at,
                "url": post.url,
                "views": post.views,
                "likes": post.likes,
                "raw_text": post.raw_text,
                "exclude_reason": classification["exclude_reason"],
                "source_type": post.source_type,
            }
        )
        classified_rows.append(
            {
                "run_date": run_date,
                "post": post,
                "classification": classification,
            }
        )

    weekly_ideas = build_weekly_ideas(classified_rows, config)
    write_local_outputs(raw_rows, classified_rows, weekly_ideas)
    append_sheet_rows(raw_rows, classified_rows, weekly_ideas)

    summary = {
        "run_date": run_date,
        "raw_post_count": len(raw_rows),
        "classified_post_count": len(classified_rows),
        "weekly_idea_count": len(weekly_ideas),
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
