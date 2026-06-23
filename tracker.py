"""
YouTube 바이럴 신호 트래커
- 키워드 기반으로 해외 숏폼 영상 검색
- 조회수/구독자수 대비 비정상적 증가량(이상치) 탐지
- 결과를 Google Sheets에 자동 누적 기록

실행 방식: GitHub Actions에서 6시간마다 자동 실행 (하루 4회 — tracker.yml에서 별도로 맞춰야 함)
"""

import os
import csv
import json
import datetime
import requests
import gspread
from google.oauth2.service_account import Credentials

# ============================================================
# 0. 설정값 — 여기를 Jin이 원하는 키워드로 자유롭게 수정
# ============================================================

SEARCH_KEYWORDS = [
    "creative transition reel",
    "liminal space short film",  # "simple concept video viral"에서 교체 — "viral"이 너무 흔해서 동남아 밈 콘텐츠를 끌어오던 단어였음. 새 카테고리(글리치·이미지오류)에 맞춤
    "one person short film idea",
    "dystopian sci-fi short film",
    "surreal short video",
    "mind blowing edit reels",
]

# 검색 결과를 어느 나라 시청자 기준으로 볼지 (ISO 3166-1 국가코드, 예: US/GB/JP)
# 주의: 이건 "영상을 올린 사람의 국적"을 거르는 기능이 아니라,
# "그 나라 시청자한테 보이는 화면 기준으로 검색 결과를 본다"는 뜻임.
# 그래도 그 나라에서 잘 보이는 콘텐츠 쪽으로 결과가 어느 정도 쏠리는 효과는 있음.
# "유럽"은 국가코드 하나로 못 묶어서, 일단 US + JP 2개로 잡음 — 유럽 특정 국가(GB/FR/DE 등)로
# 바꾸고 싶으면 이 리스트 값만 바꾸면 됨.
# 국가를 늘릴수록 search_videos 호출이 국가 수만큼 곱해져서 쿼터 사용량도 그만큼 늘어남.
REGION_CODES = ["US", "JP"]

# 검색 결과 중 며칠 이내 업로드된 영상만 볼지 (너무 오래된 영상 제외)
PUBLISHED_AFTER_DAYS = 14

# 구독자수 대비 조회수 비율이 이 값 이상이면 "후보"로 분류
# 예: 5.0 = 구독자수의 5배 이상 조회수가 나온 영상
ANOMALY_THRESHOLD = 5.0

# 한 키워드당 가져올 영상 수 (쿼터 절약을 위해 적게)
MAX_RESULTS_PER_KEYWORD = 15

# ============================================================
# 1. 환경변수 (GitHub Secrets에서 주입됨)
# ============================================================

YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]
GOOGLE_SHEETS_CREDENTIALS = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")  # JSON 문자열
SPREADSHEET_NAME = os.environ.get("SPREADSHEET_NAME", "viral-tracker")

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
YOUTUBE_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"


# ============================================================
# 2. YouTube 데이터 수집
# ============================================================

def search_videos(keyword: str, region: str) -> list[str]:
    """키워드+국가로 영상 검색 → video_id 리스트 반환"""
    published_after = (
        datetime.datetime.utcnow() - datetime.timedelta(days=PUBLISHED_AFTER_DAYS)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    params = {
        "part": "id",
        "q": keyword,
        "type": "video",
        "order": "viewCount",
        "publishedAfter": published_after,
        "maxResults": MAX_RESULTS_PER_KEYWORD,
        "key": YOUTUBE_API_KEY,
        "relevanceLanguage": "en",
        "regionCode": region,
        # videoDuration 필터 없음 — 쇼츠/릴스(짧은 영상)부터 롱폼까지 전부 검색됨
    }
    res = requests.get(YOUTUBE_SEARCH_URL, params=params, timeout=20)
    res.raise_for_status()
    data = res.json()
    return [item["id"]["videoId"] for item in data.get("items", [])]


def get_video_stats(video_ids: list[str]) -> list[dict]:
    """video_id 리스트 → 조회수/채널ID/제목 등 상세 정보"""
    if not video_ids:
        return []

    results = []
    # videos.list는 한 번에 최대 50개 id까지만 허용 (51개 이상이면 400 에러)
    # 국가를 2개로 늘리면서 video_id 모음이 50개를 넘는 경우가 생겨서 이 청크 처리가 꼭 필요해짐
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i + 50]
        params = {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(chunk),
            "key": YOUTUBE_API_KEY,
        }
        res = requests.get(YOUTUBE_VIDEOS_URL, params=params, timeout=20)
        res.raise_for_status()
        data = res.json()

        for item in data.get("items", []):
            duration_iso = item.get("contentDetails", {}).get("duration", "")
            results.append({
                "video_id": item["id"],
                "title": item["snippet"]["title"],
                "channel_id": item["snippet"]["channelId"],
                "channel_title": item["snippet"]["channelTitle"],
                "published_at": item["snippet"]["publishedAt"],
                "view_count": int(item["statistics"].get("viewCount", 0)),
                "duration": duration_iso,  # 예: PT45S(쇼츠/릴스 성격), PT12M30S(롱폼)
                "url": f"https://youtube.com/watch?v={item['id']}",
            })
    return results


def get_subscriber_counts(channel_ids: list[str]) -> dict[str, int]:
    """channel_id 리스트 → {channel_id: 구독자수} 매핑"""
    if not channel_ids:
        return {}
    unique_ids = list(set(channel_ids))
    counts = {}
    # API는 한 번에 최대 50개 채널만 허용
    for i in range(0, len(unique_ids), 50):
        chunk = unique_ids[i:i + 50]
        params = {
            "part": "statistics",
            "id": ",".join(chunk),
            "key": YOUTUBE_API_KEY,
        }
        res = requests.get(YOUTUBE_CHANNELS_URL, params=params, timeout=20)
        res.raise_for_status()
        data = res.json()
        for item in data.get("items", []):
            counts[item["id"]] = int(item["statistics"].get("subscriberCount", 0))
    return counts


# ============================================================
# 3. 이상치(바이럴 신호) 계산
# ============================================================

def calculate_signals(videos: list[dict], sub_counts: dict[str, int]) -> list[dict]:
    """구독자수 대비 조회수 비율로 '기회 점수' 계산"""
    scored = []
    for v in videos:
        subs = sub_counts.get(v["channel_id"], 0)
        # 구독자 0~100명짜리 신생 채널은 비율 왜곡이 심해서 최소값 보정
        safe_subs = max(subs, 100)
        ratio = round(v["view_count"] / safe_subs, 2)

        if ratio >= ANOMALY_THRESHOLD:
            v["subscriber_count"] = subs
            v["view_to_sub_ratio"] = ratio
            v["checked_at"] = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
            scored.append(v)

    scored.sort(key=lambda x: x["view_to_sub_ratio"], reverse=True)
    return scored


# ============================================================
# 4. Google Sheets 저장
# ============================================================

def save_to_sheets(rows: list[dict]):
    if not GOOGLE_SHEETS_CREDENTIALS:
        print("[알림] GOOGLE_SHEETS_CREDENTIALS 없음 — CSV로만 저장합니다.")
        save_to_csv(rows)
        return

    creds_dict = json.loads(GOOGLE_SHEETS_CREDENTIALS)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)

    sheet = client.open(SPREADSHEET_NAME).sheet1

    # 헤더가 없으면 추가
    if sheet.row_count == 0 or not sheet.row_values(1):
        sheet.append_row([
            "checked_at", "title", "channel_title", "view_count",
            "subscriber_count", "view_to_sub_ratio", "duration", "published_at", "url"
        ])

    for r in rows:
        sheet.append_row([
            r["checked_at"], r["title"], r["channel_title"], r["view_count"],
            r["subscriber_count"], r["view_to_sub_ratio"], r["duration"], r["published_at"], r["url"]
        ])

    print(f"[완료] {len(rows)}개 후보를 Google Sheets에 저장했습니다.")


def save_to_csv(rows: list[dict]):
    filename = "results.csv"
    file_exists = os.path.exists(filename)
    with open(filename, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "checked_at", "title", "channel_title", "view_count",
            "subscriber_count", "view_to_sub_ratio", "duration", "published_at", "url"
        ])
        if not file_exists:
            writer.writeheader()
        for r in rows:
            writer.writerow({k: r[k] for k in writer.fieldnames})
    print(f"[완료] {len(rows)}개 후보를 {filename}에 저장했습니다.")


def load_existing_urls() -> set[str]:
    """이미 저장돼 있는 영상의 url을 모아서 반환 — 다음 검색에서 똑같은 영상을 또 저장하지 않게 거르는 용도.
    인기 영상은 14일(PUBLISHED_AFTER_DAYS) 동안 매 실행마다 계속 다시 잡힐 수 있어서,
    이 체크 없이는 같은 영상이 하루 4번 × 14일 = 최대 56번까지 중복으로 쌓일 수 있음."""
    if GOOGLE_SHEETS_CREDENTIALS:
        try:
            creds_dict = json.loads(GOOGLE_SHEETS_CREDENTIALS)
            scopes = ["https://www.googleapis.com/auth/spreadsheets"]
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
            client = gspread.authorize(creds)
            sheet = client.open(SPREADSHEET_NAME).sheet1
            header = sheet.row_values(1)
            if "url" not in header:
                return set()
            url_col_index = header.index("url") + 1  # gspread 칸 번호는 1부터 시작
            return {v for v in sheet.col_values(url_col_index)[1:] if v}
        except Exception as e:
            print(f"[알림] 기존 Sheets 데이터 확인 실패, 중복 체크 없이 진행합니다: {e}")
            return set()
    else:
        filename = "results.csv"
        if not os.path.exists(filename):
            return set()
        try:
            with open(filename, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                return {row["url"] for row in reader if row.get("url")}
        except Exception as e:
            print(f"[알림] 기존 {filename} 확인 실패, 중복 체크 없이 진행합니다: {e}")
            return set()


# ============================================================
# 5. 메인 실행
# ============================================================

def main():
    video_id_set = set()
    for region in REGION_CODES:
        for keyword in SEARCH_KEYWORDS:
            print(f"[검색중] ({region}) {keyword}")
            try:
                video_ids = search_videos(keyword, region)
                video_id_set.update(video_ids)  # 같은 영상이 다른 국가/키워드에서 또 잡혀도 한 번만 처리됨
            except requests.HTTPError as e:
                print(f"[에러] ({region}) '{keyword}' 검색 실패: {e}")

    all_videos = get_video_stats(list(video_id_set))

    if not all_videos:
        print("[결과] 검색된 영상이 없습니다.")
        return

    channel_ids = [v["channel_id"] for v in all_videos]
    sub_counts = get_subscriber_counts(channel_ids)

    candidates = calculate_signals(all_videos, sub_counts)
    print(f"[결과] 후보 {len(candidates)}건 발견 (기준: 조회수/구독자 ≥ {ANOMALY_THRESHOLD})")

    if not candidates:
        print("[결과] 기준을 넘는 후보가 없습니다.")
        return

    existing_urls = load_existing_urls()
    new_candidates = [c for c in candidates if c["url"] not in existing_urls]
    skipped = len(candidates) - len(new_candidates)
    print(f"[결과] 이미 저장된 영상 {skipped}건 제외 → 신규 저장 대상 {len(new_candidates)}건")

    if new_candidates:
        save_to_sheets(new_candidates)
    else:
        print("[결과] 전부 이미 저장된 영상이라 새로 저장할 후보가 없습니다.")


if __name__ == "__main__":
    main()
