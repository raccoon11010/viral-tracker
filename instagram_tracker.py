"""
Instagram 바이럴 신호 트래커
- Apify의 data-slayer/instagram-search-reels Actor를 호출해 키워드 기반 릴스 수집
- 무료 플랜에서도 API 자동화 가능한 Actor로 선정함 (apidojo 버전은 API 호출 시 유료 플랜 필요해서 제외)
- 좋아요/댓글수 기준으로 정렬해서 누적 저장
- 실행 방식: GitHub Actions에서 하루 1회 자동 실행
"""

import os
import csv
import datetime
import requests

# ============================================================
# 0. 설정값 — 여기를 Jin이 원하는 키워드로 자유롭게 수정
# ============================================================

KEYWORDS = [
    "mystery",
    "viral",
    "transition",
    "scifi",
    "shortfilm",
]

MAX_PAGES_PER_KEYWORD = 1  # 페이지당 약 10~12개 수집됨, 늘리면 더 많이/비싸짐

APIFY_API_TOKEN = os.environ["APIFY_API_TOKEN"]
ACTOR_ID = "data-slayer~instagram-search-reels"
APIFY_RUN_URL = f"https://api.apify.com/v2/acts/{ACTOR_ID}/run-sync-get-dataset-items"


def fetch_reels_for_keyword(keyword: str) -> list[dict]:
    payload = {"query": keyword, "maxPages": MAX_PAGES_PER_KEYWORD}
    params = {"token": APIFY_API_TOKEN}
    res = requests.post(APIFY_RUN_URL, params=params, json=payload, timeout=300)
    res.raise_for_status()
    return res.json()


def normalize(items: list[dict]) -> list[dict]:
    rows = []
    for item in items:
        caption = item.get("caption") or {}
        user = item.get("user") or {}
        code = item.get("code", "")

        rows.append({
            "checked_at": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "caption": (caption.get("text") or "").replace("\n", " ")[:300],
            "owner_username": user.get("username", ""),
            "like_count": item.get("like_count") or 0,
            "comment_count": item.get("comment_count") or 0,
            "play_count": item.get("play_count") or item.get("ig_play_count") or 0,
            "video_duration": item.get("video_duration", ""),
            "created_at": item.get("taken_at_date", ""),
            "video_url": item.get("video_url", ""),
            "display_url": item.get("thumbnail_url", ""),
            "url": f"https://www.instagram.com/reel/{code}/" if code else "",
        })
    return rows


def save_to_csv(rows: list[dict]):
    filename = "instagram_results.csv"
    file_exists = os.path.exists(filename)
    fieldnames = [
        "checked_at", "caption", "owner_username", "like_count", "comment_count",
        "play_count", "video_duration", "created_at", "video_url", "display_url", "url"
    ]
    with open(filename, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for r in rows:
            writer.writerow(r)
    print(f"[완료] {len(rows)}건을 {filename}에 저장했습니다.")


def main():
    all_rows = []
    for kw in KEYWORDS:
        print(f"[검색중] {kw}")
        try:
            items = fetch_reels_for_keyword(kw)
            all_rows.extend(normalize(items))
        except requests.HTTPError as e:
            print(f"[에러] '{kw}' 검색 실패: {e}")

    if not all_rows:
        print("[결과] 수집된 게시물이 없습니다.")
        return

    all_rows.sort(key=lambda r: r["like_count"], reverse=True)
    print(f"[결과] {len(all_rows)}건 수집됨")
    save_to_csv(all_rows)


if __name__ == "__main__":
    main()
