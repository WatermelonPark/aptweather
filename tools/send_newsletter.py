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
DATA = os.path.join(ROOT, 'data.js')
CHANGED = os.path.join(ROOT, '.stats_changed')
# 이미 발송한 기간을 기록하는 원장. 갱신 판정(update_adv_data)이 뚫리더라도
# 같은 기간을 두 번 보내지 않게 막는 마지막 방어선이다.
LEDGER = os.path.join(ROOT, '.last_sent')
# 발송 트리거를 보존하는 대기열. 발송 성공·이미발송일 때만 지운다.
# .stats_changed(매 실행 덮어씀)와 달리 실패해도 다음 실행까지 살아남는다.
PENDING = os.path.join(ROOT, '.pending_send')

def _has_trigger(c):
    return any(k in c for k in ('weekly', 'monthly', 'permits', 'occupancy', '금리'))
API = 'https://api.buttondown.com/v1/emails'
KEY = os.environ.get('BUTTONDOWN_API_KEY', '')
SITE = 'https://www.agongmap.co.kr'

CORE = ['전국', '수도권', '서울', '경기', '인천', '세종', '부산', '대구']


def read_adv():
    c = io.open(DATA, encoding='utf-8').read()
    i, j = c.find('/*ADV_DATA_START*/'), c.find('/*ADV_DATA_END*/')
    m = re.match(r'const ADV=(.*);$', c[i + 18:j], re.S)
    return json.loads(m.group(1))


def fmt(v):
    if v is None: return '-'
    return '0.00%' if v == 0 else ('%+.2f%%' % v)


def _wk_label(p):
    """'2026-07-13' → '7/13주', '2026-05' → '5월'"""
    if len(p) == 10:
        return '%d/%d주' % (int(p[5:7]), int(p[8:10]))
    return '%d월' % int(p[5:7])


def _tops(regs, vals, n=3, exclude=('수도권',)):
    ranked = sorted((r for r in regs if vals.get(r) is not None and r not in exclude),
                    key=lambda r: vals[r], reverse=True)
    up = [r for r in ranked if vals[r] > 0][:n]
    dn = [r for r in reversed(ranked) if vals[r] < 0][:n]
    return up, dn


def section(title, unit, W, with_seoul=False):
    regs, row = W['regions'], W['rows'][-1]
    val = {r: {'ma': row['ma'][i], 'je': row['je'][i]} for i, r in enumerate(regs)}
    ma = {r: v['ma'] for r, v in val.items()}
    up, dn = _tops(regs, ma)
    L = ['## 🗓️ %s — %s' % (title, row['p']), '', '%s 아파트 매매·전세 변동률(%%)입니다.' % unit, '',
         '| 지역 | 매매 | 전세 |', '|:---|---:|---:|']
    for r in CORE:
        if r in val:
            L.append('| **%s** | %s | %s |' % (r, fmt(val[r]['ma']), fmt(val[r]['je'])))
    L.append('')
    if up:
        L.append('🔺 **상승**: ' + ' · '.join('%s %s' % (r, fmt(ma[r])) for r in up))
    if dn:
        L.append('')
        L.append('🔻 **하락**: ' + ' · '.join('%s %s' % (r, fmt(ma[r])) for r in dn))
    L.append('')
    if with_seoul and W.get('seoul') and W['seoul'].get('rows'):
        S = W['seoul']
        srow = S['rows'][-1]
        sma = {r: srow['ma'][i] for i, r in enumerate(S['regions'])}
        sup, sdn = _tops(S['regions'], sma, n=3, exclude=())
        if sup or sdn:
            L.append('**서울 안에서는** — ' +
                     (('많이 오른 곳: ' + ' · '.join('%s %s' % (r, fmt(sma[r])) for r in sup)) if sup else '') +
                     ((' / 내린 곳: ' + ' · '.join('%s %s' % (r, fmt(sma[r])) for r in sdn)) if sdn else ''))
            L.append('')
    return L, val


def build_body(changed):
    adv = read_adv()
    L, parts = [], []
    seoul_ma = None
    wk_label = None
    if 'weekly' in changed and adv.get('weekly'):
        wk_p = adv['weekly']['rows'][-1]['p']
        wk_label = _wk_label(wk_p)
        sec, val = section('주간 시장상황', '전주 대비', adv['weekly'], with_seoul=True)
        L += sec
        parts.append(wk_label)
        seoul_ma = val.get('서울', {}).get('ma')
        # 지도 한 장 (버전 파라미터로 메일 클라이언트 캐시 회피)
        L.append('![이번 주 아파트 시세 지도](%s/share/weekly-map.png?v=%s)' % (SITE, wk_p))
        L.append('')
    if 'monthly' in changed and adv.get('monthly'):
        mo_p = adv['monthly']['rows'][-1]['p']
        sec, val = section('월간 시장상황', '전월 대비', adv['monthly'])
        L += sec
        parts.append(_wk_label(mo_p) + ' 월간')
        if seoul_ma is None:
            seoul_ma = val.get('서울', {}).get('ma')
    if 'permits' in changed and adv.get('permits', {}).get('rows'):
        P = adv['permits']
        last = P['rows'][-1]
        tot = sum(v for v in last['v'] if v is not None)
        half = last['p'].replace('H1', '년 상반기').replace('H2', '년 하반기')
        L += ['## 🏗️ 인허가 물량 업데이트', '',
              '%s 아파트 인허가(40㎡ 제외)가 반영되었습니다 — 15개 지역 합계 **%s호**.' % (half, format(tot, ',')),
              '인허가는 4~6년 뒤 입주로 이어지는 가장 이른 공급 신호입니다.', '',
              '👉 [인허가 표·차트 보기](%s/#stats-adv)' % SITE, '']
        parts.append('인허가')
    if 'occupancy' in changed and adv.get('occupancy', {}).get('rows'):
        O = adv['occupancy']
        fut = [r for r in O['rows'] if r.get('e')]
        L += ['## 🏠 입주물량 업데이트', '',
              '분기별 입주물량 자료가 갱신되었습니다%s. 지역별 적정 밴드와 비교해보세요.' %
              (' (입주예정 %d개 분기 커버)' % len(fut) if fut else ''), '',
              '👉 [입주물량 표·차트 보기](%s/#stats-adv)' % SITE, '']
        parts.append('입주물량')
    if '금리' in changed:
        try:
            c = io.open(DATA, encoding='utf-8').read()
            i0, j0 = c.find('/*STATS_DATA_START*/'), c.find('/*STATS_DATA_END*/')
            st = json.loads(re.match(r'const STATS=(.*);$', c[i0 + 20:j0], re.S).group(1))
            sr = st['금리']['series']['CD(91일)']
            dts = st['금리']['dates']
            cur, prev = sr[-1], sr[-2]
            mm = re.match(r'^(\d{4})[.\/](\d{1,2})', str(dts[-1]))
            lab = ('%d월' % int(mm.group(2))) if mm else str(dts[-1])
            L += ['## 🏦 CD금리 업데이트', '',
                  '%s CD(91일) 금리 **%.2f%%** (전월 대비 %+.2f%%p)' % (lab, cur, cur - prev), '',
                  '👉 [금리 시계열 보기](%s/#stats-basic)' % SITE, '']
            parts.append('금리')
        except Exception:
            pass
    L.append('서울 25개 구 지형 지도와 전국 187개 시군구 상세는 사이트에서 확인할 수 있습니다.')
    L.append('')
    L.append('👉 **[시장상황 바로가기](%s/#stats-market)**' % SITE)
    label = '·'.join(parts) if parts else '통계'
    tail = (' — 서울 매매 %s' % fmt(seoul_ma)) if seoul_ma is not None else ''
    subject = '[집값 브리핑] %s 업데이트%s' % (label, tail)
    return subject, '\n'.join(L)


def read_ledger():
    try:
        return json.loads(io.open(LEDGER, encoding='utf-8').read())
    except Exception:
        return {}


def periods_of(changed):
    """이번 메일이 '새로 나왔다'고 주장하게 될 기간을 종류별로 뽑는다."""
    adv = read_adv()
    out = {}
    for k in ('weekly', 'monthly', 'permits', 'occupancy'):
        if k in changed and adv.get(k, {}).get('rows'):
            out[k] = adv[k]['rows'][-1]['p']
    if '금리' in changed:
        try:
            c = io.open(DATA, encoding='utf-8').read()
            i0, j0 = c.find('/*STATS_DATA_START*/'), c.find('/*STATS_DATA_END*/')
            st = json.loads(re.match(r'const STATS=(.*);$', c[i0 + 20:j0], re.S).group(1))
            out['금리'] = str(st['금리']['dates'][-1])
        except Exception:
            pass
    return out


def _clear_pending():
    try:
        os.remove(PENDING)
        print('pending cleared')
    except OSError:
        pass


def main():
    preview = '--preview' in sys.argv
    if preview:
        args = [a for a in sys.argv[1:] if a != '--preview']
        changed = args[0] if args else 'weekly,monthly'
    else:
        try:
            changed = io.open(CHANGED, encoding='utf-8').read()
        except IOError:
            changed = ''
        # 이번 실행에 발송 트리거가 없으면, 지난 실패분(.pending_send)을 되살려 재시도한다.
        if not _has_trigger(changed):
            try:
                pending = io.open(PENDING, encoding='utf-8').read()
            except IOError:
                pending = ''
            if _has_trigger(pending):
                changed = pending
                print('retry: 이전 발송 실패분 재시도(.pending_send)')
        if not _has_trigger(changed):
            print('skip: 이번 실행에서 통계 갱신 없음')
            return
        if not KEY:
            # 키가 없어도 트리거는 보존한다 — 예전엔 여기서 그냥 끝나 유실됐다.
            io.open(PENDING, 'w', encoding='utf-8', newline='\n').write(changed)
            print('skip: BUTTONDOWN_API_KEY 없음 — 발송 보류(.pending_send)')
            return
    periods = periods_of(changed) if not preview else {}
    ledger = read_ledger()
    if periods and all(ledger.get(k) == v for k, v in periods.items()):
        print('skip: 이미 발송한 기간 (%s) — 중복 발송 방지'
              % ', '.join('%s=%s' % kv for kv in sorted(periods.items())))
        if not preview:
            _clear_pending()
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
    # 발송 실패는 반드시 종료코드로 드러낸다. 예전에는 print만 하고 0으로 끝나
    # 배치가 'OK'를 찍었고, 발송 성공과 실패가 구분되지 않았다.
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            print('sent:', r.status)
    except urllib.error.HTTPError as e:
        print('send failed: HTTP %s — %s' % (e.code, e.read().decode('utf-8', 'replace')[:300]))
        io.open(PENDING, 'w', encoding='utf-8', newline='\n').write(changed)
        sys.exit(1)
    except Exception as e:
        print('send failed: %s: %s' % (type(e).__name__, e))
        io.open(PENDING, 'w', encoding='utf-8', newline='\n').write(changed)
        sys.exit(1)
    # 발송이 실제로 성공한 뒤에만 원장을 갱신한다.
    if periods:
        ledger.update(periods)
        io.open(LEDGER, 'w', encoding='utf-8', newline='\n').write(
            json.dumps(ledger, ensure_ascii=False, sort_keys=True, indent=1))
        print('ledger:', ', '.join('%s=%s' % kv for kv in sorted(periods.items())))
    _clear_pending()


if __name__ == '__main__':
    main()
