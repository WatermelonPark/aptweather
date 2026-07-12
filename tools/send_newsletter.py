# -*- coding: utf-8 -*-
"""주간 시장상황 알림 발송 (Buttondown).

update_adv_data.py --update 가 주간 데이터를 갱신한 경우에만 발송한다.
(갱신 여부는 .stats_changed 파일로 전달받음 — 저장소에 커밋되지 않는 작업 파일)

사용:
  BUTTONDOWN_API_KEY=... python tools/send_newsletter.py            # 실제 발송
  python tools/send_newsletter.py --preview                         # 본문만 생성해 출력(발송 없음)

키가 없거나 주간 갱신이 없으면 아무것도 하지 않고 정상 종료한다.
"""
import io, os, re, sys, json
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, 'index.html')
CHANGED = os.path.join(ROOT, '.stats_changed')
API = 'https://api.buttondown.com/v1/emails'
KEY = os.environ.get('BUTTONDOWN_API_KEY', '')
SITE = 'https://www.aptweather.co.kr'


def read_adv():
    c = io.open(INDEX, encoding='utf-8').read()
    i, j = c.find('/*ADV_DATA_START*/'), c.find('/*ADV_DATA_END*/')
    m = re.match(r'const ADV=(.*);$', c[i + 18:j], re.S)
    return json.loads(m.group(1))


def fmt(v):
    if v is None: return '-'
    return '0.00%' if v == 0 else ('%+.2f%%' % v)


def build_body():
    adv = read_adv()
    W = adv['weekly']
    regs, row = W['regions'], W['rows'][-1]
    val = {r: {'ma': row['ma'][i], 'je': row['je'][i]} for i, r in enumerate(regs)}
    ranked = sorted((r for r in regs if val[r]['ma'] is not None and r != '수도권'),
                    key=lambda r: val[r]['ma'], reverse=True)
    up = [r for r in ranked if val[r]['ma'] > 0][:3]
    dn = [r for r in reversed(ranked) if val[r]['ma'] < 0][:3]

    L = []
    L.append('**%s 주간 아파트 동향**이 갱신되었습니다. (전주 대비 변동률)' % row['p'])
    L.append('')
    L.append('| 지역 | 매매 | 전세 |')
    L.append('|---|---|---|')
    for r in ['수도권', '서울', '경기', '인천', '세종', '부산', '대구']:
        if r in val:
            L.append('| %s | %s | %s |' % (r, fmt(val[r]['ma']), fmt(val[r]['je'])))
    L.append('')
    if up:
        L.append('**상승 상위**: ' + ' · '.join('%s %s' % (r, fmt(val[r]['ma'])) for r in up))
    if dn:
        L.append('**하락 상위**: ' + ' · '.join('%s %s' % (r, fmt(val[r]['ma'])) for r in dn))
    L.append('')
    L.append('서울 구별 지도·전국 시군구 상세는 사이트에서 확인하세요.')
    L.append('')
    L.append('👉 [시장상황 바로가기](%s/#stats-market)' % SITE)
    L.append('')
    L.append('---')
    L.append('*이 메일은 데이터가 갱신된 주에만 발송됩니다. 자료: KOSIS 한국부동산원 전국주택가격동향조사.*')
    subject = '[집값은 돌고 돈다] %s 주간 시장상황 — 서울 매매 %s' % (row['p'], fmt(val.get('서울', {}).get('ma')))
    return subject, '\n'.join(L)


def main():
    preview = '--preview' in sys.argv
    if not preview:
        if not KEY:
            print('skip: BUTTONDOWN_API_KEY 없음')
            return
        try:
            changed = io.open(CHANGED, encoding='utf-8').read()
        except IOError:
            changed = ''
        if 'weekly' not in changed:
            print('skip: 이번 실행에서 주간 데이터 갱신 없음')
            return
    subject, body = build_body()
    if preview:
        print(subject)
        print()
        print(body)
        return
    payload = json.dumps({'subject': subject, 'body': body, 'status': 'about_to_send'}).encode('utf-8')
    req = urllib.request.Request(API, data=payload, method='POST', headers={
        'Authorization': 'Token ' + KEY, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        print('sent:', r.status)


if __name__ == '__main__':
    main()
