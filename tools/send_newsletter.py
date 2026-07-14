# -*- coding: utf-8 -*-
"""시장상황 알림 발송 (Buttondown).

update_adv_data.py --update 가 주간 또는 월간 데이터를 갱신한 경우에만 발송한다.
(갱신 여부는 .stats_changed 파일로 전달받음 — 저장소에 커밋되지 않는 작업 파일)

사용:
  BUTTONDOWN_API_KEY=... python tools/send_newsletter.py            # 실제 발송
  python tools/send_newsletter.py --preview                         # 본문만 생성해 출력(발송 없음)
  python tools/send_newsletter.py --preview weekly,monthly          # 갱신 종류를 지정해 미리보기

키가 없거나 주간·월간 갱신이 없으면 아무것도 하지 않고 정상 종료한다.
"""
import io, os, re, sys, json
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, 'index.html')
CHANGED = os.path.join(ROOT, '.stats_changed')
API = 'https://api.buttondown.com/v1/emails'
KEY = os.environ.get('BUTTONDOWN_API_KEY', '')
SITE = 'https://www.aptweather.co.kr'

CORE = ['수도권', '서울', '경기', '인천', '세종', '부산', '대구']


def read_adv():
    c = io.open(INDEX, encoding='utf-8').read()
    i, j = c.find('/*ADV_DATA_START*/'), c.find('/*ADV_DATA_END*/')
    m = re.match(r'const ADV=(.*);$', c[i + 18:j], re.S)
    return json.loads(m.group(1))


def fmt(v):
    if v is None: return '-'
    return '0.00%' if v == 0 else ('%+.2f%%' % v)


def section(title, unit, W):
    regs, row = W['regions'], W['rows'][-1]
    val = {r: {'ma': row['ma'][i], 'je': row['je'][i]} for i, r in enumerate(regs)}
    ranked = sorted((r for r in regs if val[r]['ma'] is not None and r != '수도권'),
                    key=lambda r: val[r]['ma'], reverse=True)
    up = [r for r in ranked if val[r]['ma'] > 0][:3]
    dn = [r for r in reversed(ranked) if val[r]['ma'] < 0][:3]
    L = ['## %s (%s)' % (title, row['p']), '', '%s 아파트 매매·전세 변동률입니다.' % unit, '',
         '| 지역 | 매매 | 전세 |', '|---|---|---|']
    for r in CORE:
        if r in val:
            L.append('| %s | %s | %s |' % (r, fmt(val[r]['ma']), fmt(val[r]['je'])))
    L.append('')
    if up:
        L.append('**상승 상위**: ' + ' · '.join('%s %s' % (r, fmt(val[r]['ma'])) for r in up))
    if dn:
        L.append('**하락 상위**: ' + ' · '.join('%s %s' % (r, fmt(val[r]['ma'])) for r in dn))
    L.append('')
    return L, val


def build_body(changed):
    adv = read_adv()
    L, parts = [], []
    seoul_ma = None
    if 'weekly' in changed and adv.get('weekly'):
        sec, val = section('주간 시장상황', '전주 대비', adv['weekly'])
        L += sec
        parts.append('주간')
        seoul_ma = val.get('서울', {}).get('ma')
        wk_p = adv['weekly']['rows'][-1]['p']
    if 'monthly' in changed and adv.get('monthly'):
        sec, val = section('월간 시장상황', '전월 대비', adv['monthly'])
        L += sec
        parts.append('월간')
        if seoul_ma is None:
            seoul_ma = val.get('서울', {}).get('ma')
    L.append('서울 구별 지도·전국 시군구 상세는 사이트에서 확인하세요.')
    L.append('')
    L.append('👉 [시장상황 바로가기](%s/#stats-market)' % SITE)
    L.append('')
    L.append('---')
    L.append('*이 메일은 통계가 갱신될 때만 발송됩니다. 자료: KOSIS 한국부동산원 전국주택가격동향조사.*')
    label = '·'.join(parts) if parts else '시장상황'
    subject = '[집값은 돌고 돈다] %s 통계 업데이트 — 서울 매매 %s' % (label, fmt(seoul_ma))
    return subject, '\n'.join(L)


def main():
    preview = '--preview' in sys.argv
    if preview:
        args = [a for a in sys.argv[1:] if a != '--preview']
        changed = args[0] if args else 'weekly,monthly'
    else:
        if not KEY:
            print('skip: BUTTONDOWN_API_KEY 없음')
            return
        try:
            changed = io.open(CHANGED, encoding='utf-8').read()
        except IOError:
            changed = ''
        if 'weekly' not in changed and 'monthly' not in changed:
            print('skip: 이번 실행에서 주간·월간 데이터 갱신 없음')
            return
    subject, body = build_body(changed)
    if preview:
        print(subject)
        print()
        print(body)
        return
    payload = json.dumps({'subject': subject, 'body': body, 'status': 'about_to_send'}).encode('utf-8')
    req = urllib.request.Request(API, data=payload, method='POST', headers={
        'Authorization': 'Token ' + KEY, 'Content-Type': 'application/json',
        # Buttondown 공식 요구사항: API 실발송 확인용 헤더 (키당 1회 요구, 상시 포함해도 무해)
        'X-Buttondown-Live-Dangerously': 'true'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            print('sent:', r.status)
    except urllib.error.HTTPError as e:
        # 발송 실패해도 배치 전체는 성공으로 끝낸다 (통계 갱신이 본체)
        print('send failed: HTTP %s — %s' % (e.code, e.read().decode('utf-8', 'replace')[:300]))


if __name__ == '__main__':
    main()
