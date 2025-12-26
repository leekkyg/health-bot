import feedparser
import requests
from datetime import datetime
import pytz
import os
import anthropic
import urllib.parse
import time

# 환경변수
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
WP_URL = os.environ.get("WP_URL")
WP_USER = os.environ.get("WP_USER")
WP_APP_PASSWORD = os.environ.get("WP_APP_PASSWORD")

# 건강정보 RSS 피드
RSS_FEEDS = [
    ("헬스조선", "https://health.chosun.com/rss/rss.xml"),
    ("코메디닷컴", "https://kormedi.com/feed/"),
    ("하이닥", "https://www.hidoc.co.kr/healthstory/news/rss"),
]

def fetch_health_news():
    all_news = []
    for source_name, feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:5]:
                all_news.append({
                    "source": source_name,
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "summary": entry.get("summary", entry.get("description", "")),
                })
        except Exception as e:
            print(f"[ERROR] {source_name} 피드 수집 실패: {e}")
    return all_news

def generate_health_article(news_list):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    
    news_text = ""
    for i, news in enumerate(news_list, 1):
        news_text += f"제목: {news['title']}\n내용: {news['summary']}\n\n"
    
    prompt = f"""너는 건강 전문 블로거야.
아래 건강 뉴스들을 참고해서 하나의 유익한 건강정보 블로그 글을 작성해.

[작성 규칙]
- 뉴스 중 가장 흥미롭고 유익한 주제 1개를 선택
- 제목은 클릭하고 싶게 매력적으로 (예: "매일 이것만 했더니 혈압이..." 스타일)
- 본문은 800~1200자 분량
- 친근하고 읽기 쉬운 문체
- 원본 기사를 복사하지 말고 완전히 새로운 문장으로 재작성
- 실용적인 팁이나 조언 포함
- HTML 형식으로 작성 (h2, h3, p 태그 사용)
- 마지막에 핵심 요약 3줄 포함

[입력 데이터]
{news_text}

반드시 아래 형식으로 출력:
TITLE: (제목)
IMAGE_PROMPT: (이 글에 어울리는 이미지를 영어로 설명, 예: healthy elderly woman doing yoga in park)
CONTENT: (HTML 본문)"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    
    return message.content[0].text

def parse_article(response):
    lines = response.strip().split('\n')
    title = ""
    image_prompt = ""
    content_lines = []
    current_section = None
    
    for line in lines:
        if line.startswith("TITLE:"):
            title = line.replace("TITLE:", "").strip()
            current_section = "title"
        elif line.startswith("IMAGE_PROMPT:"):
            image_prompt = line.replace("IMAGE_PROMPT:", "").strip()
            current_section = "image"
        elif line.startswith("CONTENT:"):
            current_section = "content"
            content_start = line.replace("CONTENT:", "").strip()
            if content_start:
                content_lines.append(content_start)
        elif current_section == "content":
            content_lines.append(line)
    
    content = '\n'.join(content_lines)
    return title, image_prompt, content

def generate_image(prompt):
    try:
        encoded_prompt = urllib.parse.quote(prompt)
        image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1200&height=630&nologo=true"
        print(f"이미지 URL: {image_url}")
        
        # 이미지 생성 대기
        time.sleep(5)
        response = requests.get(image_url, timeout=120)
        print(f"이미지 응답 코드: {response.status_code}")
        
        if response.status_code == 200:
            return response.content
        else:
            print(f"[ERROR] 이미지 생성 실패: {response.status_code}")
            return None
    except Exception as e:
        print(f"[ERROR] 이미지 생성 실패: {e}")
        return None

def upload_image_to_wordpress(image_data, filename):
    try:
        # 워드프레스에 업로드
        media_endpoint = f"{WP_URL}/wp-json/wp/v2/media"
        headers = {
            "Content-Disposition": f'attachment; filename="{filename}.jpg"',
            "Content-Type": "image/jpeg"
        }
        print(f"업로드 엔드포인트: {media_endpoint}")
        
        upload_response = requests.post(
            media_endpoint,
            headers=headers,
            data=image_data,
            auth=(WP_USER, WP_APP_PASSWORD)
        )
        
        print(f"업로드 응답 코드: {upload_response.status_code}")
        
        if upload_response.status_code == 201:
            media_data = upload_response.json()
            media_id = media_data.get("id")
            source_url = media_data.get("source_url")
            print(f"업로드 성공! ID: {media_id}, URL: {source_url}")
            return media_id, source_url
        else:
            print(f"[ERROR] 이미지 업로드 실패: {upload_response.status_code} - {upload_response.text}")
            return None, None
    except Exception as e:
        print(f"[ERROR] 이미지 업로드 실패: {e}")
        return None, None

def post_to_wordpress(title, content, image_id):
    endpoint = f"{WP_URL}/wp-json/wp/v2/posts"
    post_data = {
        "title": title,
        "content": content,
        "status": "publish",
        "categories": [124],
    }
    
    if image_id:
        post_data["featured_media"] = image_id
        print(f"대표 이미지 ID 설정: {image_id}")
    else:
        print("대표 이미지 없음")
    
    response = requests.post(
        endpoint,
        json=post_data,
        auth=(WP_USER, WP_APP_PASSWORD),
        headers={"Content-Type": "application/json"}
    )
    if response.status_code == 201:
        print(f"[SUCCESS] 발행 완료: {response.json().get('link')}")
    else:
        print(f"[ERROR] 발행 실패: {response.status_code} - {response.text}")

def main():
    print("=== 건강정보 자동 발행 시작 ===")
    
    news_list = fetch_health_news()
    print(f"[1/5] {len(news_list)}개 건강뉴스 수집 완료")
    
    if not news_list:
        print("[ERROR] 수집된 뉴스가 없습니다.")
        return
    
    print("[2/5] Claude로 글 생성 중...")
    response = generate_health_article(news_list)
    
    print("[3/5] 글 파싱 중...")
    title, image_prompt, content = parse_article(response)
    print(f"제목: {title}")
    print(f"이미지 프롬프트: {image_prompt}")
    
    print("[4/5] AI 이미지 생성 및 업로드 중...")
    image_data = generate_image(image_prompt)
    image_id = None
    image_source_url = None
    
    if image_data:
        print(f"이미지 데이터 크기: {len(image_data)} bytes")
        kst = pytz.timezone('Asia/Seoul')
        timestamp = datetime.now(kst).strftime("%Y%m%d%H%M%S")
        image_id, image_source_url = upload_image_to_wordpress(image_data, f"health_{timestamp}")
        
        if image_source_url:
            content = f'<img src="{image_source_url}" alt="{title}" />\n\n{content}'
    else:
        print("이미지 생성 실패 - 이미지 없이 발행")
    
    print("[5/5] WordPress 발행 중...")
    post_to_wordpress(title, content, image_id)
    print("=== 완료 ===")

if __name__ == "__main__":
    main()
