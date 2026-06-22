"""
Instagram 바이럴 신호 트래커
- Apify의 apidojo/instagram-scraper Actor를 호출해 해시태그 기반 게시물 수집
- 좋아요/댓글수 기준으로 정렬해서 누적 저장
- 실행 방식: GitHub Actions에서 하루 1회 자동 실행 (비용 절약을 위해 YouTube보다 낮은 빈도)
"""

import os
import csv
import datetime
import requests

# ============================================================
# 0. 설정값 — 여기를 Jin이 원하는 해시태그로 자유롭게 수정
# ============================================================

HASHTAGS = [
    "mystery",
    "viral",
    "transition",
    "scifi",
    "shortfilm",
]

# 해시태그당 최대 수집 개수 (전체 = HASHTAGS 개수 * 이 값)
MAX_ITEMS_PER_RUN = 100  # 전체 실행 1회 최대 수집량 (비용 관리용)

APIFY_API_TOKEN = os.environ["APIFY_API_TOKEN"]
ACTOR_ID = "apidojo~instagram-scraper"  # apidojo/instagram-scraper
APIFY_RUN_URL = f"https://api.apify.com/v2/acts/{ACTOR_ID}/run-sync-get-dataset-items"


def fetch_instagram_posts() -> list[dict]:
    """해시태그 기반으로 인스타그램 게시물 수집"""
    start_urls = [f"https://www.instagram.com/explore/tags/{tag}/" for tag in HASHTAGS]

    payload = {
        "startUrls": start_urls,
        "resultsLimit": MAX_ITEMS_PER_RUN,
    }
    params = {"token": APIFY_API_TOKEN}

    res = requests.post(APIFY_RUN_URL, params=params, json=payload, timeout=300)
    res.raise_for_status()
    return res.json()


def normalize(items: list[dict]) -> list[dict]:
    """결과를 CSV 저장용 형태로 정리"""
    rows = []
    for item in items:
        like_count = item.get("likeCount") or 0
        comment_count = item.get("commentCount") or 0
        owner = item.get("owner") or {}

        rows.append({
            "checked_at": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "caption": (item.get("caption") or "").replace("\n", " ")[:300],
            "owner_username": owner.get("username", ""),
            "like_count": like_count,
            "comment_count": comment_count,
            "created_at": item.get("createdAt", ""),
            "video_url": item.get("videoUrl", ""),
            "display_url": item.get("displayUrl") or item.get("thumbnailUrl") or "",
            "url": item.get("url", ""),
        })
    return rows


def save_to_csv(rows: list[dict]):
    filename = "instagram_results.csv"
    file_exists = os.path.exists(filename)
    fieldnames = [
        "checked_at", "caption", "owner_username", "like_count",
        "comment_count", "created_at", "video_url", "display_url", "url"
    ]
    with open(filename, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for r in rows:
            writer.writerow(r)
    print(f"[완료] {len(rows)}건을 {filename}에 저장했습니다.")


def main():
    print(f"[검색중] 해시태그: {', '.join(HASHTAGS)}")
    try:
        items = fetch_instagram_posts()
    except requests.HTTPError as e:
        print(f"[에러] Apify 호출 실패: {e}")
        return

    if not items:
        print("[결과] 수집된 게시물이 없습니다.")
        return

    rows = normalize(items)
    rows.sort(key=lambda r: r["like_count"], reverse=True)

    print(f"[결과] {len(rows)}건 수집됨")
    save_to_csv(rows)


if __name__ == "__main__":
    main()
