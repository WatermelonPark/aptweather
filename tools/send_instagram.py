# -*- coding: utf-8 -*-
"""인스타그램 피드 자동 업로드 API 연동 스크립트.

update_adv_data.py --update 가 데이터를 갱신하고, weekly-map.png 가 깃허브 푸시로 공개된 경우 실행된다.
환경변수(.aptweather_keys.bat)에서 인스타 계정 ID 및 Meta 액세스 토큰을 로드한다.
"""
import io
import os
import sys
import json
import time
import urllib.request
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import send_newsletter as N  # noqa: E402

# 환경변수 로드
INSTAGRAM_BUSINESS_ID = os.environ.get('INSTAGRAM_BUSINESS_ID', '')
ACCESS_TOKEN = os.environ.get('META_ACCESS_TOKEN', '')
CHANGED = os.path.join(ROOT, '.stats_changed')
SITE = 'https://www.agongmap.co.kr'


def strip_markdown(text):
    """인스타그램 피드 캡션용으로 마크다운 특수문자 제거 및 평문 정리"""
    # 볼드 기호 ** 제거
    text = text.replace('**', '')
    # 링크 양식 [텍스트](URL) -> 텍스트 (URL)
    import re
    text = re.sub(r'\[(.*?)\]\((.*?)\)', r'\1 (\2)', text)
    # 표 기호 정리
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        if line.strip().startswith('|'):
            if '---' in line: continue
            cells = [c.strip() for c in line.split('|')[1:-1]]
            cleaned_lines.append(" · ".join(cells))
        else:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def main():
    if not os.path.exists(CHANGED):
        print("인스타그램 skip: 최근 갱신 내역 없음")
        return
        
    changed = io.open(CHANGED, encoding='utf-8').read()
    # 주간 시세 데이터가 바뀐 경우에만 인스타 맵 업로드 실행
    if 'weekly' not in changed:
        print("인스타그램 skip: 이번 주간 시세 변동 없음")
        return

    if not INSTAGRAM_BUSINESS_ID or not ACCESS_TOKEN:
        print("인스타그램 skip: INSTAGRAM_BUSINESS_ID 또는 META_ACCESS_TOKEN 환경변수 없음")
        return

    # 뉴스레터 본문에서 캡션 문구 추출 및 평문화
    subject, body_md = N.build_body(changed)
    caption = f"📢 {subject}\n\n" + strip_markdown(body_md)
    # 인스타 글 수량 제한(2,200자) 대응
    if len(caption) > 2100:
        caption = caption[:2100] + "\n\n...상세 지표는 아공맵 사이트에서 확인해 주세요!"

    # 캐시 방지용 쿼리 타임스탬프 추가
    img_url = f"{SITE}/share/weekly-map.png?t={int(time.time())}"

    # 1단계: 미디어 컨테이너 생성
    container_url = f"https://graph.facebook.com/v19.0/{INSTAGRAM_BUSINESS_ID}/media"
    payload = urllib.parse.urlencode({
        "image_url": img_url,
        "caption": caption,
        "access_token": ACCESS_TOKEN
    }).encode('utf-8')

    req = urllib.request.Request(container_url, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
    
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.loads(r.read().decode('utf-8'))
            creation_id = res.get("id")
    except Exception as e:
        print("인스타그램 미디어 컨테이너 생성 실패:", e)
        return

    if not creation_id:
        print("인스타그램 생성 실패: 컨테이너 ID 없음")
        return

    # 메타 서버가 이미지를 긁어가고 처리할 시간을 주기 위해 대기
    print("인스타 업로드 대기중 (15초)...")
    time.sleep(15)

    # 2단계: 피드 발행
    publish_url = f"https://graph.facebook.com/v19.0/{INSTAGRAM_BUSINESS_ID}/media_publish"
    publish_payload = urllib.parse.urlencode({
        "creation_id": creation_id,
        "access_token": ACCESS_TOKEN
    }).encode('utf-8')

    req2 = urllib.request.Request(publish_url, data=publish_payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
    
    try:
        with urllib.request.urlopen(req2, timeout=30) as r2:
            res2 = json.loads(r2.read().decode('utf-8'))
            print("인스타그램 포스팅 성공 ID:", res2.get("id"))
    except Exception as e:
        print("인스타그램 포스팅 발행 실패:", e)


if __name__ == '__main__':
    main()
