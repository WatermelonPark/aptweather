# -*- coding: utf-8 -*-
"""생활권별 공급 리포트 페이지 생성 — /zone/<생활권>/index.html

data.js의 ADV(livezone·occupancy·permits·bubble)와 STATS(전세가율·주택멸실)를 읽어
아공맵 점수 산출 근거를 서술형으로 풀어쓴 정적 페이지를 생활권 수만큼 만든다.
홈의 요약 카드가 "무슨 말인지 모르겠다"는 문제를 풀고, 검색 유입(SEO) 창구가 된다.

사용:  python tools/make_zone_pages.py         # 생성 + sitemap 갱신
"""
import io, os, re, json, sys, datetime
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data.js')
SITE = 'https://www.agongmap.co.kr'
H_MAX = 8  # 앞으로 최대 8분기 — 실제로는 데이터가 있는 미래 분기 수만 사용
LB = 12  # 과거 누적 3년(12분기) — 부족은 재고처럼 쌓이므로 1년으로는 부족
W = (0.55, 0.35, 0.10)


def load():
    t = io.open(DATA, encoding='utf-8').read()
    adv = json.loads(re.search(r'/\*ADV_DATA_START\*/const ADV=(\{.*?\});\s*/\*ADV_DATA_END\*/', t, re.S).group(1))
    sts = json.loads(re.search(r'/\*STATS_DATA_START\*/const STATS=(\{.*?\});\s*/\*STATS_DATA_END\*/', t, re.S).group(1))
    return adv, sts


def last_of(series, key):
    s = (series or {}).get(key)
    if not s:
        return 0
    for v in reversed(s):
        if v is not None:
            return v
    return 0


def _qkey(idx):
    return '%dQ%d' % (idx // 4, idx % 4 + 1)


def _conf(k):
    """신뢰가중: k=미래 몇 분기 뒤(1..). 1분기 뒤 1.0 → 20분기(5년) 뒤 0으로 선형 감쇠."""
    return max(0.0, 1.0 - ((k - 1) / 4.0) * 0.2)


ANCHOR = 2010 * 4  # 2010Q1
FUT_HORIZON = 16  # 4년(기준표 3년룰 + 준공예정 실측 ~4년); conf가 3~4년차를 낮게 가중
DEFICIT_CAP = 16  # 부족(음수 재고) 누적 상한 = 적정물량 몇 분기치까지 쌓이게 둘지(4년)

# ── 등급 판정 (2026-07-31 UX 재기획) ─────────────────────────────
# 기준값 = 순부족(tot) ÷ 4년 필요량(refq*share*16). 경계는 상위 등급 포함(>=).
# 절대 컷 고정 — 상대평가는 전국이 과잉이어도 같은 수의 '부족'을 만들어 왜곡한다.
# 색은 app.css .sc-tier 팔레트 재사용(새 색 도입 금지).
# ⚠️ index.html의 scGrade()와 반드시 동치(이중구현 미러) — check_dual_calc가 대조한다.
# ── 수요 풀(공급 영향권) — 2026-08-01 재정의 ────────────────────────────────
# 생활권의 원 정의(사용자): 일상 이동권이 아니라 "공급에 따라 가격 방향이 같이
# 정해지는 영향권". 잔차 가격 동조성(0.73~0.89) × 지리 인접(45km) × 12격자
# 강건성(9/12+)으로 확정한 두 풀만 묶는다(tools/zone_pool_map.py, 2026-08-01).
# 풀 적정 = 구성 존들의 기존 시도 배분액 합 → 풀 안에서 세대(hh) 비중으로 재배분.
# 새 추정 없이 기존 시도 ref만 재배선 — 세대당 수요가 풀 안에서 균등해진다
# (부산으로 통근하는 김해·창원에 부산 수준의 세대당 수요가 배정되는 효과).
# 두 풀은 서로 완전히 별개다(부산권역과 대구권역을 합치는 게 아니다).
# 이천·평택은 수도권 사이클과 독립(실측)이지만 자체 역산이 표본 부족(금리쇼크
# 제외 시 저점 1개)으로 불가해 현행 수도권 안분 유지 + 존 페이지 공시(사용자 결정).
# ⚠️ index.html scCalc()와 반드시 동치(이중구현 미러 — check_dual_calc가 대조).
POOLS = {
    '동남권': ('부산권', '김해권', '창원권'),
    '대구권역': ('대구권', '구미권'),
}
POOL_OF = {z: p for p, ms in POOLS.items() for z in ms}
INDEP_ZONES = ('이천권', '평택권')   # 독립 시장 공시 대상(⑤ 한계 섹션)

GRADE_CUTS = (1.5, 1.0, 0.5, -0.5)
GRADE_ORDER = ('g4', 'g3', 'g2', 'g1', 'g0')
GRADES = (
    ('g4', '매우 부족', '#a93226', '앞으로 4년, 필요한 집이 크게 모자랍니다'),
    ('g3', '부족', '#c0392b', '공급이 수요를 못 따라갑니다'),
    ('g2', '다소 부족', '#b9770e', '부족하지만 심하진 않습니다'),
    ('g1', '균형', '#5e6f74', '필요한 만큼 들어오고 있습니다'),
    ('g0', '공급 여유', '#1a5276', '입주가 몰려 있어 세입자·매수자에게 유리한 시기가 옵니다'),
)


def grade(tot, need4):
    r = (tot / need4) if need4 else 0.0
    for cut, g in zip(GRADE_CUTS, GRADES):
        if r >= cut:
            break
    else:
        g = GRADES[-1]
    return {'k': g[0], 'label': g[1], 'color': g[2], 'desc': g[3], 'ratio': r}


def running_shortage(done, sched, demol, refq, cur_q, horizon=20, weight_demand=True, full=False):
    """준공 기반 러닝재고 순부족.

    I_now = 2010Q1부터 현재분기까지 매 분기 max(-DEFICIT_CAP*refq, 재고+준공-멸실-refq)로
    굴린 재고. 음수(=부족)도 쌓이되 적정물량 DEFICIT_CAP분기치(4년)가 상한이다.
    ⚠️ 원래는 max(0, ·)였는데, 그러면 만성부족 존은 재고가 늘 0에 붙어 정보를 잃는다
    (서울권은 2010Q1 이후 재고>0인 분기가 6%뿐이었다 — "이번 분기부터 모자란 곳"과
    "16년째 모자란 곳"이 똑같이 0). 2026-07-31 검증: 44개 생활권 × 2010~ 패널에서
    금리 잔잔한 구간만 뽑아 재고→향후 2년 가격을 보면 예측력이 0.030(p=0.31, 무의미)
    -> 0.142(p=0.007)로 오른다. 상한을 더 늘리면 8년에서 0.179로 포화하지만 서울권
    순부족이 78만세대(4년 수요의 2.9배)까지 터져 쓸 수 없어 4년으로 정했다(순위 변동
    평균 1.3계단). 근거·재현: tools/zone_floor_cap.py, memory/agongmap-index-calibration.md
    순공급=준공−멸실(기준표: 재건축 준공은 순공급을 부풀린다 —
    서울 인허가 100 = 멸실 70 + 순증 30) — 철거(멸실) 시점에 재고를 먼저 깎고
    준공 시점에 다시 채우므로, 재건축 진행중(철거~준공 사이)엔 재고가 낮게
    잡혀 그 구간의 단기 공급부족이 드러난다. demol은 done과 동일하게 이미
    zone-level 절대값(멸실 세대)이라 share를 곱하지 않는다(호출측 계약).
    미래(future) 항은 멸실 데이터가 희소해 그대로 sched만 사용한다.
    weight_demand=True (A안 — 이 함수의 기본값일 뿐, 라이브는 아니다): 수요도 conf로 가중 —
      순부족 = Σ_{k=1..horizon} conf(k)*(refq - sched(cur_q+k)) - I_now.
    weight_demand=False (B안·스펙 원문 — 현재 라이브. calc()가 False로 넘긴다): 수요는
      비가중, 공급만 conf로 가중 —
      순부족 = Σ_{k=1..horizon} refq  -  Σ_{k=1..horizon} conf(k)*sched(cur_q+k) - I_now.
    두 안 모두 refq는 호출측이 이미 zone-level(적정*share)로 넘긴 값이어야 한다.
    양수=부족(발산 막대 오른쪽), 음수=과잉.
    """
    # M1: full(분해값 반환)은 항등식 tot == demand - supplyw - inow 성립을 전제로
    # 문서화돼 있는데, 그 항등식은 weight_demand=False(B안)에서만 성립한다(A안은
    # fut가 이미 conf 가중 결합이라 demand_sum/supply_weighted로 쪼갤 수 없다).
    # 두 플래그가 동시에 True인 호출은 분해값이 조용히 틀린 채 나가므로 여기서 막는다.
    assert not (full and weight_demand), '분해값은 B안(weight_demand=False)에서만 유효'
    I = 0.0
    lo = -DEFICIT_CAP * refq
    for idx in range(ANCHOR, cur_q + 1):
        qk = _qkey(idx)
        I = max(lo, I + done.get(qk, 0) - demol.get(qk, 0) - refq)
    I_now = I
    fut_weighted = 0.0
    demand_sum = 0.0
    supply_weighted = 0.0
    for k in range(1, horizon + 1):
        w = _conf(k)
        if w <= 0:
            break
        s = sched.get(_qkey(cur_q + k), 0)
        fut_weighted += w * (refq - s)
        demand_sum += refq
        supply_weighted += w * s
    fut = fut_weighted if weight_demand else (demand_sum - supply_weighted)
    tot = fut - I_now
    if full:
        # 존 페이지 '왜 이 판정인가' 근거 3줄용 분해값.
        # 항등식: tot == demand - supplyw - inow (weight_demand=False 기준.
        # True(A안)면 fut가 이미 가중 결합이라 분해가 성립하지 않는다 — 라이브는 False).
        return {'tot': tot, 'inow': I_now, 'demand': demand_sum, 'supplyw': supply_weighted}
    return tot


def calc(adv, sts, weight_demand=False, horizon=FUT_HORIZON):
    """홈 renderScoreSec(scCalc)와 동일한 산식으로 생활권별 누적 순부족을 계산.

    weight_demand, horizon: running_shortage()로 그대로 전달(A안/B안, Issue #4).
    기본값 weight_demand=False(B안) + horizon=FUT_HORIZON(4년)이 라이브 산식(scCalc와
    동치) — 기준표 「기본의 기본 3」 근거(2026-07-25 확정). 여기서 바꾸지 않는 한 운영
    동작은 그대로다. verify_rankdiff.py는 이 파라미터를 명시적으로 오버라이드해
    A(True)/B(False)를 나란히 비교한다.
    """
    LZ, O, P, B = adv['livezone'], adv['occupancy'], adv['permits'], adv.get('bubble') or {}
    J = (sts.get('전세가율') or {}).get('series') or {}
    DM = (sts.get('주택멸실') or {}).get('series') or {}
    # 적정물량 안분 잣대 — 2026-07-31 인구 -> 주민등록세대수. 아파트 수요는 사람 수보다
    # 가구 수에 가깝고 1인가구 증가를 반영한다. data.js는 hh/sidohh를 항상 실으므로
    # 폴백 없음. ⚠️ index.html scCalc()와 산식이 같아야 한다(이중구현 미러).
    SH = LZ.get('sidohh') or {}
    act = [r for r in O['rows'] if not r.get('e')]
    ph = P['rows'][-2:]
    today = datetime.date.today()
    cur_q = today.year * 4 + (today.month - 1) // 3        # 현재 분기 인덱스
    def qi(k):
        m = re.match(r'^(\d{4})Q([1-4])$', k)
        return int(m.group(1)) * 4 + int(m.group(2)) - 1 if m else None
    # 전역 미래 분기 창 — 모든 생활권이 같은 창을 써야 절대량 비교가 성립
    allq = {k for zz in LZ['zones'] for k in (zz.get('byq') or {})}
    FUTQ = sorted([k for k in allq if qi(k) is not None and qi(k) > cur_q], key=qi)[:H_MAX]
    HQ = max(1, len(FUTQ))
    def fut_supply(zz):
        b = zz.get('byq') or {}
        return sum(b.get(k, 0) for k in FUTQ), HQ
    # 풀 사전 패스: 구성 존들의 기존 시도 배분액과 세대수를 합산(POOLS 주석 참조).
    # ⚠️ scCalc()의 poolRef/poolHh 패스와 반드시 동치.
    pool_ref, pool_hh = {}, {}
    for zz in LZ['zones']:
        p = POOL_OF.get(zz['z'])
        if not p:
            continue
        ps_ = '수도권' if zz['region'] == '수도권' else (zz.get('psido') or '수도권')
        band_ = (O.get('band') or {}).get(ps_)
        ref_ = (O.get('ref') or {}).get(ps_) or (sum(band_) / 2 if band_ else None)
        if not ref_:
            continue
        pool_ref[p] = pool_ref.get(p, 0.0) + ref_ * min(1.0, zz['hh'] / (SH.get(ps_) or zz['hh'] or 1))
        pool_hh[p] = pool_hh.get(p, 0.0) + zz['hh']
    out = []
    for z in LZ['zones']:
        ps = '수도권' if z['region'] == '수도권' else (z.get('psido') or '수도권')
        if ps not in O['regions']:
            continue
        oi = O['regions'].index(ps)
        band = (O.get('band') or {}).get(ps)
        refq = (O.get('ref') or {}).get(ps) or (sum(band) / 2 if band else None)
        if not refq:
            continue
        share = min(1.0, z['hh'] / (SH.get(ps) or z['hh'] or 1))
        # 존 적정(zrefq): 기본은 시도 안분, 풀 소속 존은 풀 배분액을 세대 비중으로.
        zrefq = refq * share
        pool = POOL_OF.get(z['z'])
        pshare = None
        if pool and pool_hh.get(pool):
            pshare = z['hh'] / pool_hh[pool]
            zrefq = pool_ref[pool] * pshare
        dY = last_of(DM, ps); dQ = dY / 4.0
        fsup, H = fut_supply(z)
        need = zrefq * H
        dA = need - fsup
        n4 = [r['v'][oi] for r in act[-LB:] if r['v'][oi] is not None]
        dB = (refq * len(n4) - (sum(n4) - dQ * len(n4))) * share if n4 else 0
        dC = 0; pv = None; plo = None
        if ps in P['regions']:
            pi = P['regions'].index(ps)
            vals = [r['v'][pi] for r in ph]
            if all(v is not None for v in vals):
                pv = sum(vals); plo = P['ref'][ps][0]
                dC = (plo - (pv - dY)) * share
        tot_fallback = W[0] * dA + W[1] * dC + W[2] * dB
        zdone = (P.get('done') or {}).get(z['z']) or {}
        zsched = (P.get('sched') or {}).get(z['z']) or {}
        zdemol = (P.get('demol') or {}).get(z['z']) or {}
        inv_path = bool(zdone) or bool(zsched)
        # done/sched가 있는 존만 러닝재고 산식(신모델)을 쓴다. 없는 존(비완결·inactive)은
        # pre-HUB 산식(dA/dB/dC 가중합)을 그대로 유지 — activate 게이트 전엔 전 존이 이 경로.
        # zdone/zsched는 ZONE(생활권) 단위 실적인데 refq는 REGION(시도) 적정이다 —
        # zone-level 적정으로 맞추려면 share를 곱해야 한다(dA/dB/dC 폴백 경로와 동일 원칙).
        if inv_path:
            # M1: full=True(분해값)는 weight_demand=False(B안·라이브)에서만 유효하다.
            # verify_rankdiff.py의 A안(weight_demand=True) 호출이 이 calc()를 거쳐
            # 오므로, A안일 때는 분해 없이 tot만 받는다(그렇지 않으면 running_shortage의
            # 새 assert에 걸려 A/B 비교 스크립트가 죽는다).
            if weight_demand:
                _rs = None
                tot = running_shortage(zdone, zsched, zdemol, zrefq, cur_q,
                                       horizon=horizon, weight_demand=True, full=False)
            else:
                _rs = running_shortage(zdone, zsched, zdemol, zrefq, cur_q,
                                       horizon=horizon, weight_demand=False, full=True)
                tot = _rs['tot']
        else:
            _rs = None
            tot = tot_fallback
        flag = None; lo = hi = None
        cv = (B.get('conv') or {}).get(ps)
        jr = last_of(J, ps) or None
        loan = (B.get('loan') or {}).get('v')
        if cv and jr and loan:
            lo = jr / 100.0 * cv; hi = lo * 2
            flag = 'warn' if loan >= hi else ('watch' if loan <= lo else None)
        # 입주예정 물량 0은 '자료 없음'이 아니라 그냥 0이다(2026-07-19 사용자 확정).
        # odcloud는 물량이 없는 지역의 행을 아예 보내지 않으므로 '단지 없음 = 물량 0'이고,
        # 원자료 자체의 건강성은 update_adv_data의 가드 1(생활권 급감 감지)이 따로 지킨다.
        # 진주권 실측(2026-07-19): 2027-12까지 입주 0세대, 다음은 2028-06 840세대로
        # 원자료 시야(2026-01~2027-12) 밖. 즉 결측이 아니라 실제 공급 가뭄이다.
        need4 = zrefq * 16
        out.append(dict(z=z, ps=ps, share=share, need=need, dA=dA, dB=dB, dC=dC, tot=tot, fsup=fsup, fq=H,
                        flag=flag, lo=lo, hi=hi, loan=loan, pv=pv, plo=plo, dY=dY, refq=refq, band=band,
                        inv_path=inv_path, tot_fallback=tot_fallback,
                        need4=need4, zrefq=zrefq, pool=pool, pshare=pshare,
                        inow=(_rs['inow'] if _rs else 0.0),
                        fsupw=(_rs['supplyw'] if _rs else 0.0),
                        zsched=zsched,
                        gr=grade(tot, need4)))
    out.sort(key=lambda r: -r['tot'])
    return out


def make_capital(rows):
    """수도권 16개 생활권을 하나로 합친 unit — 홈 순위표와 같은 기준."""
    caps = [r for r in rows if r['z']['region'] == '수도권']
    if not caps:
        return None
    agg = dict(caps[0])
    q0s = [c['z'].get('q0') for c in caps if c['z'].get('q0')]
    q1s = [c['z'].get('q1') for c in caps if c['z'].get('q1')]
    agg['z'] = {'z': '수도권', 'region': '수도권',
                'pop': sum(c['z']['pop'] for c in caps),
                'supply': sum(c['z']['supply'] for c in caps),
                'sgg': [], 'q0': min(q0s) if q0s else '', 'q1': max(q1s) if q1s else '',
                'span': 1 if q0s else 0}
    for k in ('need', 'dA', 'dB', 'dC', 'tot', 'fsup', 'need4', 'inow', 'fsupw'):
        agg[k] = sum(c[k] for c in caps)
    # Fix I3+M4: ③ 타임라인이 ②와 같은 HUB sched 소스를 쓰려면 수도권 롤업도
    # 자기 zsched(원래 없음 — 수도권은 calc()의 개별 zone 루프를 안 돈다)를
    # 소속 생활권 합산으로 채워야 한다(분기별 세대수 합).
    agg_sched = {}
    for c in caps:
        for qk, v in (c.get('zsched') or {}).items():
            agg_sched[qk] = agg_sched.get(qk, 0) + v
    agg['zsched'] = agg_sched
    agg['fq'] = max(c['fq'] for c in caps)
    agg['share'] = sum(c['share'] for c in caps)
    agg['ps'] = '수도권'
    agg['subs'] = sorted(caps, key=lambda c: -c['tot'])
    agg['gr'] = grade(agg['tot'], agg['need4'])
    return agg


def num(v):
    return '{:,}'.format(int(round(v)))


def signed(v):
    """화면 표기는 부호 반전 — 부족을 음수로."""
    d = -v
    s = '−' if d < 0 else '+'
    a = abs(d)
    return s + ('{:,}'.format(int(round(a))))


UNIT_WINDOW = 48   # 단지 목록 창(개월): 앞으로 4년 · 지난 4년. 상위 N개 캡 대신
                   # 시간 창으로 자른다(옛 top-20은 2005년 준공 대단지가 밀고 들어왔다).


def render_units_2sec(units, today=None):
    """permits.units[zone](또는 수도권처럼 소속 존 합산) → 2섹션 HTML.

    "앞으로 들어올 단지"(sched)와 "최근 들어온 단지"(done) 2섹션.

    ⚠️ 합계(N세대)를 쓰지 않는다. units는 수집기(fetch_hub_permits UNITS_CAP=40)가
    시군구당 상위 40개만 담은 **부분집합**이라 존 전체 물량과 다르다 — 총량은
    '언제 들어오나' 차트(permits.sched 전량)가 유일한 출처다. 두 숫자를 나란히
    보이면 안 맞는다(2026-08-01 실제 보고: 대구권 차트 55,693 vs 목록 15,020).

    창은 UNIT_WINDOW: sched는 오늘~+48개월, done은 -48개월~오늘만 남긴다(예정일이
    이미 지난 sched 항목도 제외 — 스테일 데이터). 2026-07-31 사용자 결정으로
    지연/지연 가능 태그는 제거했다(공간 과다 + 판정과 무관한 노이즈).

    units에 sched/done이 둘 다 없으면 빈 문자열을 반환 — 호출부가 이걸로
    "이 존은 HUB 커버 안 됨"을 판단해 기존 odcloud 리스트로 폴백한다.
    """
    if today is None:
        today = datetime.date.today()
    units = units or {}
    sched = list(units.get('sched') or [])
    done = list(units.get('done') or [])
    if not sched and not done:
        return ''
    # title="%s" 속성에 그대로 들어가므로 따옴표까지 이스케이프한다 — HUB 원자료에
    # '일신 "에일린의 뜰" 아파트' 같은 단지명이 실재한다(2026-08-01 리뷰 M3).
    esc = lambda s: (str(s).replace('&', '&amp;').replace('<', '&lt;')
                     .replace('>', '&gt;').replace('"', '&quot;'))

    def months_out(ym):
        try:
            y, m = int(ym[:4]), int(ym[5:7])
        except (TypeError, ValueError, IndexError):
            return None
        return (y - today.year) * 12 + (m - today.month)

    # ⚠️ 창은 '언제 들어오나' 차트와 분기 단위로 정확히 같아야 한다(2026-08-01 버그):
    # 예전엔 목록이 '오늘로부터 0~48개월'이라 현재 분기 물량까지 넣었는데, 차트는
    # cur_q+1..cur_q+16이라 현재 분기를 뺐다 — 춘천권 874세대(2026-08)가 목록에만
    # 있고 차트엔 없어 합이 안 맞았다. 이제 둘 다 분기 인덱스로 비교한다.
    cur_q = today.year * 4 + (today.month - 1) // 3
    HQ = UNIT_WINDOW // 3                   # 48개월 = 16분기

    def uq(u):
        ym = u[2] if len(u) > 2 else None
        if not ym:
            return None
        try:
            return int(ym[:4]) * 4 + (int(ym[5:7]) - 1) // 3
        except (TypeError, ValueError, IndexError):
            return None

    def in_future(u):
        q = uq(u)
        return True if q is None else (cur_q < q <= cur_q + HQ)

    def in_past(u):
        q = uq(u)
        return True if q is None else (cur_q - HQ < q <= cur_q)

    sched = [u for u in sched if in_future(u)]
    done = [u for u in done if in_past(u)]
    # 같은 단지가 동·블록별로 따로 등록돼 PK가 갈리는 경우가 있다(예: 대구금호워터폴리스
    # D2블록 ×2) — 화면에선 (이름, 세대, 연월)이 같으면 한 줄로 접는다.
    def _dedupe(us):
        seen, out = set(), []
        for u in us:
            k = (u[0], u[1], u[2] if len(u) > 2 else None)
            if k in seen:
                continue
            seen.add(k)
            out.append(u)
        return out
    sched, done = _dedupe(sched), _dedupe(done)
    if not sched and not done:
        return ''

    def sched_row(u):
        name, hh = u[0], u[1]
        ym = u[2] if len(u) > 2 else None
        label = ('%s 예정' % ym.replace('-', '.')) if ym else '미정'
        return ('<tr><td class="uname" title="%s">%s</td><td class="num">%s</td>'
                '<td class="num">%s</td></tr>' % (esc(name), esc(name), num(hh), label))

    def done_row(u):
        name, hh = u[0], u[1]
        ym = u[2] if len(u) > 2 else None
        label = ('%s 준공' % ym.replace('-', '.')) if ym else '준공일 미상'
        return ('<tr><td class="uname" title="%s">%s</td><td class="num">%s</td>'
                '<td class="num">%s</td></tr>' % (esc(name), esc(name), num(hh), label))

    parts = []
    if sched:
        rows = ''.join(sched_row(u) for u in sched)
        parts.append(
            '<section><div class="wrap">\n'
            '  <h2>앞으로 들어올 단지 <span class="ucnt">4년 내 · 세대 큰 순 %d곳</span></h2>\n'
            '  <div class="ulist"><table class="utable2">\n'
            '    <thead><tr><th>단지명</th><th>세대수</th><th>준공예정</th></tr></thead>\n'
            '    <tbody>%s</tbody>\n'
            '  </table></div>\n'
            '</div></section>\n' % (len(sched), rows))
    if done:
        rows = ''.join(done_row(u) for u in done)
        parts.append(
            '<section><div class="wrap">\n'
            '  <h2>최근 들어온 단지 <span class="ucnt">지난 4년 · 세대 큰 순 %d곳</span></h2>\n'
            '  <div class="ulist"><table class="utable2">\n'
            '    <thead><tr><th>단지명</th><th>세대수</th><th>준공</th></tr></thead>\n'
            '    <tbody>%s</tbody>\n'
            '  </table></div>\n'
            '</div></section>\n' % (len(done), rows))
    return ''.join(parts)


CSS = """b,strong{font-weight:600}
  tr.rollup td{border-top:1.5px solid var(--ink);color:var(--muted)}
  tr.rollup .sub{font-size:11.5px;color:var(--muted)}
:root{--ink:#131e24;--ink2:#4c5f66;--paper:#f4f6f5;--paper2:#e9edeb;--muted:#5e6f74;--line:#c4cec9}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--paper);color:var(--ink);word-break:keep-all;overflow-wrap:break-word;
 font-family:'Pretendard Variable','Pretendard',-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;
 line-height:1.75;-webkit-font-smoothing:antialiased;padding-bottom:66px}
.bottomnav{position:fixed;bottom:0;left:0;right:0;height:62px;background:var(--ink);
 display:flex;justify-content:center;z-index:100;box-shadow:0 -4px 18px rgba(22,32,58,.28)}
.nav-btn{flex:1;max-width:220px;display:flex;flex-direction:column;align-items:center;
 justify-content:center;gap:3px;color:#97a0b8;font-size:11.5px;font-weight:600;text-decoration:none}
.nav-btn svg{display:block}
.nav-btn:hover{color:#fff}
.nav-btn:focus-visible{outline:2px solid #fff;outline-offset:-3px}
.wrap{max-width:620px;margin:0 auto;padding:0 22px}
header{padding:44px 0 28px;text-align:center}
.chip{display:inline-block;font-size:12.5px;font-weight:600;color:#fff;
 background:var(--ink);padding:5px 14px;border-radius:0;margin-bottom:14px}
h1{font-size:clamp(25px,5.6vw,34px);font-weight:700;letter-spacing:-.02em;line-height:1.28;margin-bottom:12px}
.lead{font-size:15.5px;color:var(--ink2)}
.big{font-size:clamp(34px,9vw,48px);font-weight:700;letter-spacing:-.02em;margin:6px 0 2px}
.bigsub{font-size:13.5px;color:var(--muted)}
section{padding:30px 0;border-top:1px solid var(--line)}
h2{font-size:19.5px;font-weight:700;margin-bottom:12px}
p{font-size:15px;color:var(--ink2);margin-bottom:11px}
.card{background:#fff;border:1px solid var(--line);border-radius:0;padding:16px 18px;margin-bottom:11px}
.card b{display:block;font-size:15px;color:var(--ink);margin-bottom:5px}
.card span{font-size:13.5px;color:var(--muted)}
table{width:100%;border-collapse:collapse;font-size:14px;background:#fff;border:1px solid var(--line);border-radius:0;overflow:hidden}
th,td{padding:9px 11px;border-bottom:1px solid var(--line);text-align:right}
td:first-child{text-align:left}
thead th{background:#edf0ee;font-size:12.5px;color:var(--muted);text-align:center}
tbody tr:last-child td{border-bottom:0}
.num{font-variant-numeric:tabular-nums;font-weight:600}
.cta{display:block;max-width:400px;margin:22px auto 0;text-align:center;text-decoration:none;
 background:var(--ink);color:#fff;font-size:16.5px;font-weight:600;padding:15px 22px;border-radius:3px}
.cta.sub{background:#fff;color:var(--ink);border:1.5px solid var(--ink);font-size:15px;padding:13px 20px}
.zlist{display:flex;flex-wrap:wrap;gap:7px;margin-top:6px}
.zlist a{font-size:12.5px;font-weight:600;text-decoration:none;color:var(--ink2);background:#fff;
 border:1px solid var(--line);border-radius:3px;padding:5px 9px}
.note{font-size:12.5px;color:var(--muted);line-height:1.8}
footer{padding:26px 0 40px;text-align:center;font-size:12.5px;color:var(--muted);border-top:1px solid var(--line)}
footer a{color:var(--muted)}
.disc{font-size:12px;color:var(--muted);line-height:1.75;margin-top:14px}
@media(max-width:560px){
 table,tbody,tr,td{display:block;width:100%}
 thead{display:none}
 tr{border-bottom:1px solid var(--line);padding:13px 14px}
 tbody tr:last-child{border-bottom:0}
 td{border:0;padding:3px 0;text-align:left;display:flex;justify-content:space-between;align-items:baseline;gap:12px}
 td.lbl{display:block;font-weight:600;color:var(--ink);font-size:14.5px;margin-bottom:7px}
 td.lbl .note{display:block;font-weight:400;margin-top:2px}
 td[data-l]::before{content:attr(data-l);font-size:12.5px;color:var(--muted);font-weight:600;flex:none}
}
.gauge{background:#fff;border:1px solid var(--line);padding:16px 18px 14px}
.g-row{margin-bottom:10px}
.g-lab{display:flex;justify-content:space-between;align-items:baseline;font-size:13px;color:var(--ink2);margin-bottom:4px}
.g-lab b{font-variant-numeric:tabular-nums;font-size:14px;color:var(--ink)}
.g-bar{height:14px;background:var(--paper2)}
.g-fill{height:100%}
.g-gap{font-size:14.5px;font-weight:600;margin-top:8px}
.qwrap{background:#fff;border:1px solid var(--line);border-top:0;padding:12px 14px 10px}
.qtitle{font-size:12px;color:var(--muted);margin-bottom:8px}
.qchart{display:flex;align-items:flex-end;gap:5px;height:86px}
.q-col{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;gap:2px;height:100%}
.q-bar{width:100%;max-width:36px;background:#8fa3ab}
.q-v{font-size:9.5px;color:var(--muted);font-variant-numeric:tabular-nums;white-space:nowrap}
.q-l{font-size:10px;color:var(--muted);white-space:nowrap;margin-top:2px}
.trio{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.t-card{background:#fff;border:1px solid var(--line);padding:13px 8px 11px;text-align:center}
.t-lab{font-size:12px;color:var(--ink);font-weight:600;line-height:1.35}
.t-sub{font-size:10.5px;color:var(--muted);margin:1px 0 7px}
.t-val{font-size:17px;font-weight:700;font-variant-numeric:tabular-nums;letter-spacing:-.01em}
.t-w{font-size:10.5px;color:var(--muted);margin-top:4px}
.t-plus{display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:15px}
details.fold{background:#fff;border:1px solid var(--line);margin-bottom:9px}
details.fold summary{cursor:pointer;padding:13px 16px;font-size:14.5px;font-weight:600;color:var(--ink);
 list-style:none;display:flex;align-items:center;gap:9px;user-select:none}
details.fold summary::-webkit-details-marker{display:none}
details.fold summary::before{content:'▸';color:var(--muted);transition:transform .15s;flex:none}
details.fold[open] summary::before{transform:rotate(90deg)}
details.fold .dbody{padding:2px 16px 15px}
details.fold .dbody p{font-size:14px}
@media(max-width:420px){.t-val{font-size:14.5px}.trio{gap:6px}}
.ucnt{font-size:12.5px;color:var(--muted);font-weight:400;margin-left:4px}
.ulist{max-height:396px;overflow-y:auto;background:#fff;border:1px solid var(--line)}
.utable{border:0;table-layout:fixed;width:100%;font-size:13.5px}
.utable thead th{position:sticky;top:0;z-index:1;cursor:pointer;user-select:none;white-space:nowrap}
.utable thead th::after{content:' ⇅';color:#aeb9b5;font-size:11px}
.utable thead th.on.asc::after{content:' ↑';color:var(--ink)}
.utable thead th.on.desc::after{content:' ↓';color:var(--ink)}
.utable th:nth-child(1){width:20%}
.utable th:nth-child(3){width:15%}
.utable th:nth-child(4){width:23%}
.utable td{padding:8px 10px}
.utable td:nth-child(1),.utable td:nth-child(2){text-align:left}
.utable td:nth-child(1),.utable td:nth-child(3),.utable td:nth-child(4){white-space:nowrap}
.utable .uname{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
@media(max-width:560px){
 .utable{display:table;font-size:12.5px}
 .utable thead{display:table-header-group}
 .utable tbody{display:table-row-group}
 .utable tr{display:table-row;border:0;padding:0}
 .utable td{display:table-cell;border-bottom:1px solid var(--line);text-align:right;padding:8px 6px}
 .utable td:nth-child(1),.utable td:nth-child(2){text-align:left}
 .utable tbody tr:last-child td{border-bottom:0}
}
.utable2{border:0;table-layout:fixed;width:100%;font-size:13.5px}
.utable2 thead th{position:sticky;top:0;z-index:1;white-space:nowrap;background:#edf0ee;
 font-size:12.5px;color:var(--muted);text-align:center;padding:8px 10px}
.utable2 th:nth-child(1){width:46%}
.utable2 th:nth-child(2){width:24%}
.utable2 th:nth-child(3){width:30%}
.utable2 td{padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
.utable2 tbody tr:last-child td{border-bottom:0}
.utable2 td:nth-child(1){text-align:left}
.utable2 td:nth-child(2),.utable2 td:nth-child(3){text-align:right}
.utable2 .uname{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.utable2 tr.far td{color:var(--muted)}
.utable2 .hint{font-size:11px;color:#a93226}
@media(max-width:560px){.utable2{font-size:12.5px}}
.zg-badge{display:inline-block;padding:5px 12px;font-weight:700;font-size:14px;border-radius:2px}
.zg-cap{color:var(--muted);font-size:12px;margin:6px 0 0}
.why3 .w-row{display:flex;justify-content:space-between;align-items:baseline;padding:9px 0;border-bottom:1px solid var(--line)}
.why3 .w-lab i{display:block;font-style:normal;color:var(--muted);font-size:11.5px}
.why3 .w-tag{display:inline-block;font-style:normal;font-size:10.5px;font-weight:700;color:var(--muted);border:1px solid var(--line);padding:1px 7px;margin-right:8px;vertical-align:2px;white-space:nowrap}
.why3 .w-sum{padding:11px 0 0;font-weight:700}
.w-lead{border-left:3px solid;padding:2px 0 2px 14px;margin:0 0 18px}
.w-lead .wl-sum{font-size:19px;font-weight:700;line-height:1.45}
.w-lead .wl-note{color:var(--muted);font-size:12.5px;margin:4px 0 0}
.pidx{margin-top:20px;border-top:1px solid var(--line);padding-top:16px}
.pidx h3{font-size:14px;margin:0 0 2px}
.pidx .px-sub{color:var(--muted);font-size:11.5px;margin:0 0 10px}
.pidx .px-now{display:flex;gap:16px;flex-wrap:wrap;margin:0 0 10px;font-size:13px}
.pidx .px-c{white-space:nowrap}
.pidx .px-c b{font-weight:700;margin-left:4px}
.pidx .px-c i{font-style:normal;color:var(--muted);font-size:11px;margin-left:5px}
.pidx .px-lgs{display:flex;gap:14px;margin:0 0 4px;font-size:11.5px;color:var(--muted)}
.pidx .px-lg{display:inline-flex;align-items:center;gap:5px}
.pidx .px-lg i{width:14px;height:2.5px;display:inline-block;border-radius:2px}
.pidx svg{display:block;width:100%;height:auto;overflow:visible}
.near{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
.n-card{border:1px solid var(--line);padding:10px 12px;display:block}
.n-card .n-g{display:block;font-size:12px;font-weight:700;margin-top:2px}
.n-card i{font-style:normal;color:var(--muted);font-size:12px}
.px-tip{position:absolute;pointer-events:none;background:var(--ink);color:#fff;padding:7px 10px;
 font-size:11.5px;line-height:1.6;white-space:nowrap;opacity:0;transition:opacity .12s;z-index:5}
.px-tip b{font-weight:700}
.px-tip i{font-style:normal;display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px}
.pidx{position:relative}
.px-more{display:inline-block;margin-top:12px;padding:8px 15px;border:1px solid var(--line);
 background:#fff;font-weight:600;font-size:13px;color:var(--ink);text-decoration:none}
.px-more:hover{border-color:var(--ink)}"""



# ── 존별 시세 지수(주간·월간) — 2026-08-01 ──────────────────────────────────
# 시황통계(ADV.weekly/monthly.sgg)는 시군구별 변동률(%)이다. 존 페이지에 그 존
# 소속 시군구만 골라 평균(세대 가중)해 보여준다.
# 코드 사전은 index.html의 SGG_QNAME("서울 강남구"/"수원 장안구"/"이천" 형식)을
# 빌드 타임에 파싱해 쓴다 — 사전이 거기 한 곳에만 있어 중복 정의를 피하려는 것.
# 구조가 바뀌면 test_zone_price_index가 커버리지로 즉시 잡는다.
_SIDO_PREFIX = {'a7': '서울', 'a8': '경기', 'a9': '인천', 'b1': '부산', 'b2': '대구',
                'b3': '광주', 'b4': '대전', 'b5': '울산', 'b6': '세종', 'c1': '강원',
                'c2': '충북', 'c3': '충남', 'c4': '전북', 'c5': '전남', 'c6': '경북',
                'c7': '경남', 'c8': '제주'}


def _sgg_qname():
    src = io.open(os.path.join(ROOT, 'index.html'), encoding='utf-8').read()
    m = re.search(r'const SGG_QNAME=(\{.*?\});', src, re.S)
    if not m:
        raise SystemExit('index.html에서 SGG_QNAME을 찾지 못했다 — 구조 변경 확인')
    return json.loads(m.group(1))


def zone_sgg_codes(adv):
    """생활권 -> [시황통계 시군구 코드]. LIVEZONE(시도,시군구) 규칙으로 고른다.

    SGG_QNAME 값 형식 두 가지: '서울 강남구'(시도 접두어) / '이천'(경기 시·군, 접두어
    없음). 코드 접두어(a7/b1/c7...)로 시도를 판별해 두 형식을 통일해서 매칭한다.
    분구 도시(수원시 등)는 시 단위 코드가 없고 구 코드만 있어 '수원 '으로 시작하는
    코드를 전부 담는다.
    """
    qn = _sgg_qname()
    codes = set((adv.get('monthly') or {}).get('sgg', {}).get('codes') or [])
    # (시도, 표시명) 목록
    ent = []
    for c, v in qn.items():
        if c not in codes:
            continue
        sd = _SIDO_PREFIX.get(c[:2])
        if not sd:
            continue
        nm = v.split(' ', 1)[1] if ' ' in v else v
        base = v.split(' ', 1)[0] if ' ' in v else None   # '수원 장안구' -> '수원'
        ent.append((sd, nm, base, c))
    out = {}
    for z in adv['livezone']['zones']:
        zn = z['z']
        picks = []
        for sd, sg in _lz_members(zn):
            if sg == '*':
                picks += [c for s2, _, _, c in ent if s2 == sd]
                continue
            stem = re.sub(r'(특별시|광역시|특별자치시|특별자치도|시|군|구)$', '', sg)
            for s2, nm, base, c in ent:
                if s2 != sd:
                    continue
                if base == stem or nm == sg or nm == stem:
                    picks.append(c)
        out[zn] = sorted(set(picks))
    return out


def _lz_members(zone):
    """생활권 -> [(시도, 시군구)] — update_adv_data.LIVEZONE + 경기 동적존 규칙.
    존 정의는 파이프라인(update_adv_data)이 단일 소스라 거기서 가져온다."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from update_adv_data import LIVEZONE
    if zone in LIVEZONE:
        return list(LIVEZONE[zone])
    base = zone[:-1]
    if base.startswith('경기'):
        base = base[2:]
    return [('경기', base + '시'), ('경기', base + '군')]


def render_price_index(adv, zone, codes):
    """존 소속 시군구의 매매·전세·월세 지수 흐름(24개월) + 최근 변동률.

    시황통계(ADV.monthly/weekly.sgg)는 시군구별 전월(주)비 변동률(%)이라, 최근값을
    100으로 두고 거꾸로 누적해 '흐름'을 만든다(수준 비교가 아니라 추세를 보여주는 것).
    월세(wo)는 주간 계열에 없고 월간에만 있다.
    """
    if not codes:
        return ''
    SERIES = (('ma', '매매', '#a93226'), ('je', '전세', '#1a5276'), ('wo', '월세', '#5e6f74'))

    def series(block, key, n):
        sg = (adv.get(block) or {}).get('sgg') or {}
        allc = sg.get('codes') or []
        idx = [allc.index(c) for c in codes if c in allc]
        if not idx:
            return []
        out = []
        for row in (sg.get('rows') or [])[-n:]:
            arr = row.get(key) or []
            vs = [arr[i] for i in idx if i < len(arr) and arr[i] is not None]
            if vs:
                out.append((row['p'], sum(vs) / len(vs)))
        return out

    mo = {k: series('monthly', k, 24) for k, _, _ in SERIES}
    wk = {k: series('weekly', k, 13) for k, _, _ in SERIES}
    if not any(mo.values()) and not any(wk.values()):
        return ''

    def chip(lab, ser):
        if not ser:
            return ''
        p_, v = ser[-1]
        col = '#a93226' if v > 0 else ('#1a5276' if v < 0 else 'var(--muted)')
        return ('<span class="px-c">%s <b style="color:%s">%+.2f%%</b>'
                '<i>%s</i></span>' % (lab, col, v, p_))

    now = ''.join([chip('이번 주 매매', wk.get('ma') or []),
                   chip('이번 달 매매', mo.get('ma') or []),
                   chip('이번 달 전세', mo.get('je') or [])])

    # ── 24개월 지수 흐름(마지막=100 기준 역산) ──
    lines, months = [], []
    for k, _, _ in SERIES:
        ser = mo.get(k) or []
        if len(ser) < 6:
            lines.append(None)
            continue
        lvl, cur = [], 100.0
        for _, v in reversed(ser):
            lvl.append(cur)
            cur = cur / (1 + v / 100)
        lvl.reverse()
        lines.append(lvl)
        if len(ser) > len(months):
            months = [p_ for p_, _ in ser]
    live = [(SERIES[i], l) for i, l in enumerate(lines) if l]
    if not live:
        return ('<div class="pidx"><h3>이 지역 아파트값은 지금 어떤가</h3>'
                '<p class="px-sub">한국부동산원 아파트 가격지수 변동률 · 이 생활권 시군구 평균</p>'
                '<div class="px-now">%s</div></div>' % now)

    vals = [v for _, l in live for v in l]
    lo, hi = min(vals), max(vals)
    pad = max((hi - lo) * 0.12, 0.4)
    lo, hi = lo - pad, hi + pad
    W, H = 640.0, 200.0
    L, R, T, B = 42.0, 10.0, 12.0, 24.0
    n = max(len(months), 2)

    def X(i):
        return L + (W - L - R) * i / (n - 1)

    def Y(v):
        return T + (H - T - B) * (1 - (v - lo) / (hi - lo))

    g = []
    # y 그리드 3줄 + 라벨
    for t in (0.0, 0.5, 1.0):
        v = lo + (hi - lo) * t
        y = Y(v)
        g.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#e6eae8"/>'
                 % (L, y, W - R, y))
        g.append('<text x="%.1f" y="%.1f" font-size="10" fill="#8a969b" text-anchor="end">%.0f</text>'
                 % (L - 6, y + 3.4, v))
    # 100 기준선(현재 수준)
    if lo < 100 < hi:
        g.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#c4cec9" '
                 'stroke-dasharray="3 3"/>' % (L, Y(100), W - R, Y(100)))
    # x 눈금: 1월과 마지막
    for i, m in enumerate(months):
        if m.endswith('-01') or i == len(months) - 1:
            g.append('<text x="%.1f" y="%.1f" font-size="10" fill="#8a969b" '
                     'text-anchor="%s">%s</text>'
                     % (X(i), H - 6, 'end' if i == len(months) - 1 else 'middle',
                        m if m.endswith('-01') else m))
    for (k, lab, col), l in live:
        pts = ' '.join('%.1f,%.1f' % (X(i), Y(v)) for i, v in enumerate(l))
        g.append('<polyline fill="none" stroke="%s" stroke-width="1.9" '
                 'stroke-linejoin="round" points="%s"/>' % (col, pts))
    # hover: 월별 세로 히트영역 + 표식점(스크립트가 켜고 끈다)
    g.append('<g class="px-mk" style="display:none">'
             '<line class="px-vline" y1="%.1f" y2="%.1f" stroke="#c4cec9"/>%s</g>'
             % (T, H - B, ''.join('<circle class="px-dot" r="3.2" fill="%s"/>' % col
                                  for (_, _, col), _ in live)))
    step = (W - L - R) / (n - 1) if n > 1 else (W - L - R)
    for i in range(n):
        g.append('<rect class="px-hit" data-i="%d" x="%.1f" y="%.1f" width="%.1f" height="%.1f" '
                 'fill="transparent"/>' % (i, X(i) - step / 2, T, step, H - T - B))
    # 툴팁용 원자료(변동률 %) — 지수 레벨이 아니라 사용자가 물어본 '상승률'
    tip = {'m': months,
           's': [{'k': lab, 'c': col,
                  'v': [round(v, 2) for _, v in (mo.get(k) or [])]}
                 for (k, lab, col), _ in live]}
    svg = ('<svg viewBox="0 0 %d %d" role="img" aria-label="%s 아파트 매매·전세·월세 지수 흐름" '
           'data-tip=\'%s\'>%s</svg>'
           % (int(W), int(H), zone,
              json.dumps(tip, ensure_ascii=False).replace("'", '&#39;'), ''.join(g)))
    legend = ''.join('<span class="px-lg"><i style="background:%s"></i>%s</span>' % (col, lab)
                     for (k, lab, col), _ in live)
    return ('<div class="pidx"><h3>이 지역 아파트값은 지금 어떤가</h3>'
            '<p class="px-sub">한국부동산원 아파트 가격지수 변동률 · 이 생활권 시군구 평균 '
            '· 최근값 100 기준 흐름 · <b>그래프를 짚으면 그 달 수치</b></p>'
            '<div class="px-now">%s</div>'
            '<div class="px-lgs">%s</div>%s'
            '<div class="px-tip" hidden></div>'
            '<a class="px-more" href="/#stats">전국 시황 통계 자세히 보기 →</a>'
            '</div>' % (now, legend, svg))

def build_page(r, allrows, prd, today, punits=None, pidx=None):
    z = r['z']; nm = z['z']; ps = r['ps']
    gr = r['gr']
    tname, tcol = gr['label'], gr['color']
    disp = signed(r['tot'])
    sgg = z.get('sgg') or []
    subs = r.get('subs') or []
    if subs:
        members = '%d개 생활권 · 인구 %s명 · 입주예정 %s세대' % (len(subs), num(z['pop']), num(z['supply']))
        sublist = ('<div class="zlist" style="margin-top:9px">' +
                   ''.join('<a href="/zone/%s/">%s %s</a>' % (c['z']['z'], c['z']['z'], signed(c['tot']))
                           for c in subs) + '</div>')
        sgg_names = [c['z']['z'] for c in subs]
    else:
        members = ' · '.join('%s %s세대' % (s[0], num(s[1])) for s in sgg) if sgg else '입주예정 단지 없음'
        sublist = ''
        sgg_names = [s[0] for s in sgg]
    rank_no = 0
    if subs:
        ranktxt = '수도권 %d개 생활권 합계' % len(subs)
    else:
        # 순위 기준 = 비율(순부족/4년 필요량) — 등급과 같은 잣대(2026-07-31 사용자 결정:
        # 절대값 순위는 큰 지역이 항상 위라 등급 그룹과 어긋나 반직관적이었다).
        by_ratio = sorted(allrows, key=lambda x: -(x['tot'] / x['need4'] if x['need4'] else 0))
        rk = [i for i, x in enumerate(by_ratio, 1) if x['z']['z'] == nm]
        ranktxt = ('생활권 %d곳 중 %d위' % (len(allrows), rk[0])) if rk else ''
        rank_no = rk[0] if rk else 0
    span = ('%s~%s' % (z.get('q0'), z.get('q1'))) if z.get('span') else '예정 없음'

    # ── ① 판정 히어로 — 5등급 배지 + 자연어 판정문 (2026-07-31 UX 재기획) ──
    # 저장 버튼 없음 — 2026-07-31 사용자 결정: 명시적 '저장' 대신 페이지를 보면
    # 조용히 기억(암묵 저장, 하단 save_js). 홈 히어로가 이 값을 읽는다.
    hero_html = (
        '<span class="zg-badge" style="background:%s1a;color:%s">%s</span>\n'
        '<h1>%s, %s</h1>\n'
        '<p class="zg-cap">공급 기준 · 가격 예측 아님 · %s 데이터 · %s</p>\n'
        % (gr['color'], gr['color'], gr['label'], nm, gr['desc'], prd, ranktxt))

    # ── ② 왜 이 판정인가 — 근거 3줄. 세 줄의 합이 히어로 순부족과 정확히 일치
    # (need4/inow/fsupw만 사용 — tot == need4 - fsupw - inow 항등식이 Task 1
    # 테스트로 보장된다). 여유 존(tot<0)은 "여유"로 문구 분기.
    backlog = -r['inow']          # 양수면 '밀린 집', 음수면 '쌓인 재고'
    # 2026-07-31 사용자 피드백: '필요한 집'(미래)과 '밀린 것'(과거)은 시간 방향이
    # 반대인데 라벨에 안 드러나고, 상한 도달 존은 숫자까지 같아(둘 다 4년치) 버그처럼
    # 보였다. → 과거→미래 시간순으로 재배열하고 각 줄에 [과거]/[앞으로 4년] 시간
    # 칩을 달아 방향을 명시한다. 서사: "이미 이만큼 밀렸는데, 앞으로 이만큼 더
    # 필요하고, 들어올 건 이것뿐".
    b_lab, b_sub = ('그동안 밀린 집', '2010년부터 쌓인 부족 · 실측') if backlog >= 0 \
              else ('그동안 쌓인 집', '2010년부터 남은 재고 · 실측')
    if backlog >= 0 and abs(backlog - r['need4']) < 1:
        b_sub = ('2010년부터 쌓인 부족 · 실측 · 4년치 상한 도달 — 실제로는 더 밀렸습니다'
                 '(그래서 아래 ‘필요한 집’과 숫자가 같습니다)')
    # 필요한 집 출처: 풀 소속 존은 풀 이름·구성·풀 내 세대 비중으로 표기.
    if r.get('pool'):
        need_src = '%s 풀(%s) 세대의 %d%%' % (
            r['pool'], '·'.join(m[:-1] for m in POOLS[r['pool']]),
            round((r['pshare'] or 0) * 100))
    else:
        need_src = '%s 세대의 %d%%' % (ps, round(r['share'] * 100))
    if r['tot'] < 0:
        sum_line = '여유 %s세대' % num(-r['tot'])
    elif backlog >= 0:
        sum_line = '순부족 %s세대 = 밀린 것 + 필요 − 들어올 것' % num(r['tot'])
    else:
        sum_line = '순부족 %s세대 = 필요 − 쌓인 것 − 들어올 것' % num(r['tot'])
    # 이 지역 시세 지수(주간·월간) — '왜 이 판정인가' 하단에 붙인다(2026-08-01).
    # 공급 판정 바로 다음에 실제 가격이 어떻게 움직이는지를 보여줘 검증 가능하게.
    idx_html = pidx.get(nm, '') if pidx else ''
    # 2026-08-01 사용자: 결론부터 — 순부족 합계와 '재고처럼 쌓인다' 설명을
    # 근거 3줄 위(=섹션 맨 앞)로 올려 가시성을 높인다.
    # 결론 문장은 부호에 따라 갈라야 한다 — 여유 존에 "부족은 재고처럼 쌓입니다"가
    # 붙어 결론과 근거가 어긋났다(2026-08-01 리뷰 I3: 평택·제주 등 여유 7곳 전부).
    wl_note = ('부족은 재고처럼 쌓입니다 — 몇 해 모자란 지역은 한 해 물량이 몰려도 '
               '메워지지 않습니다.') if r['tot'] >= 0 else \
              ('여유도 재고처럼 쌓입니다 — 몇 해 몰린 지역은 한 해 물량이 줄어도 '
               '바로 해소되지 않습니다.')
    verdict_html = (
        '<div class="w-lead" style="border-color:%s">'
        '<div class="wl-sum" style="color:%s">%s</div>'
        '<p class="wl-note">%s</p></div>' % (gr['color'], gr['color'], sum_line, wl_note))
    why_html = (
        '<section><div class="wrap"><h2>왜 이 판정인가</h2>'
        '%s'
        '<div class="why3">'
        '<div class="w-row"><span class="w-lab"><em class="w-tag">과거</em>%s<i>%s</i></span><b>%s%s</b></div>'
        '<div class="w-row"><span class="w-lab"><em class="w-tag">앞으로 4년</em>필요한 집<i>%s = %s 몫 · 추정</i></span><b>+%s</b></div>'
        '<div class="w-row"><span class="w-lab"><em class="w-tag">앞으로 4년</em>들어올 집<i>준공예정 실측 · 먼 미래는 낮춰 반영</i></span><b>−%s</b></div>'
        '</div>%s</div></section>' % (
            verdict_html,
            b_lab, b_sub, ('+' if backlog >= 0 else '−'), num(abs(backlog)),
            need_src, nm, num(r['need4']),
            num(r['fsupw']),
            idx_html))

    # ── 인포그래픽: 분기별 입주 미니차트 ──
    # Fix I3+M4: 이전엔 legacy odcloud byq(짧은 창, H_MAX=8분기)를 그려 ②(왜 이
    # 판정인가 — HUB sched 16분기 가중)와 다른 미래를 말했다. ③도 같은 소스
    # (permits['sched'][존], calc()가 running_shortage에 넘기는 것과 동일 —
    # calc()가 r['zsched']로 그대로 실어 보낸다; 수도권은 make_capital()이 이미
    # subs 합산)로 같은 16분기(FUT_HORIZON) 창을 그린다. sched가 아예 없는 존
    # (HUB 미커버)만 옛 odcloud 단지 실측(byq)으로 폴백한다.
    _now = datetime.date.today()
    _curq = _now.year * 4 + (_now.month - 1) // 3
    zsched_raw = dict(r.get('zsched') or {})
    hub_sched = bool(zsched_raw)
    if hub_sched:
        byq = {}
        for k in range(1, FUT_HORIZON + 1):
            qk = _qkey(_curq + k)
            v = zsched_raw.get(qk, 0)
            if v:
                byq[qk] = v
    else:
        byq = dict(z.get('byq') or {})
        if subs and not byq:
            for cc in subs:
                for q, v in (cc['z'].get('byq') or {}).items():
                    byq[q] = byq.get(q, 0) + v
    # calc()의 FUTQ와 같은 규칙: 유효한 분기 라벨 + 미래 분기만.
    # (원자료에 '2027Q0' 같은 비정상 키와 과거 분기가 섞여 있다 — 과거까지 그리면
    #  게이지의 '들어올 집' 합과 막대 합이 안 맞아 정합성이 깨진다)
    _qre = re.compile(r'^(\d{4})Q([1-4])$')
    def qkey(q):
        m = _qre.match(q)
        return int(m.group(1)) * 4 + int(m.group(2)) - 1 if m else -1
    qs = sorted((q for q in byq if byq[q] > 0 and qkey(q) > _curq), key=qkey)
    def qlabel(q):
        return q[2:4] + 'Q' + q[5]
    if qs:
        mxq = max(byq[q] for q in qs) or 1
        peakq = max(qs, key=lambda q: byq[q])
        def qfmt(v):
            return ('%.1f만' % (v / 10000)) if v >= 10000 else format(v, ',')
        # 모든 막대 양식 동일 — 최대 분기 강조(외곽선·진한 색·굵은 숫자) 전부 제거
        # (2026-08-01 사용자). 어느 분기가 몰리는지는 아래 캡션 문장이 말해준다.
        cols = ''.join(
            '<div class="q-col"><span class="q-v">%s</span>'
            '<div class="q-bar" style="height:%.0f%%"></div>'
            '<span class="q-l">%s</span></div>' % (
                qfmt(byq[q]), max(byq[q] / mxq * 72, 3), qlabel(q))
            for q in qs)
        # 합계는 여기서만 보여준다 — 단지 목록(상위 N곳)과 헷갈리지 않게 '전체'로 명시.
        # ⚠️ ②'들어올 집'(conf 가중)과 여기 '전체'(원시 합)는 다른 값이다. 한 화면에
        # 인접해 있어 최대 36% 차이가 설명 없이 노출됐다(2026-08-01 리뷰 I1) —
        # 가중 후 값을 괄호로 병기해 두 숫자를 잇는다.
        qchart_html = ('<div class="qwrap"><div class="qtitle">분기별 입주 예정 물량 (세대) '
                       '<b style="color:var(--ink)">· 전체 %s세대</b>'
                       '<span style="color:var(--muted)"> · 먼 미래를 낮춰 반영하면 %s세대'
                       '(위 \'들어올 집\')</span></div>'
                       '<div class="qchart">%s</div></div>'
                       % (num(sum(byq[q] for q in qs)), num(r['fsupw']), cols))
        # ── ③ 언제 들어오나 — qchart_html 재사용, 최대 분기 강조 + 한 줄 캡션
        qcap = ('가장 몰리는 분기는 %s — 그래도 필요량에는 못 미칩니다' % qlabel(peakq)) if r['tot'] > 0 else \
               ('입주가 가장 몰리는 %s 전후가 세입자·매수자에게 유리합니다' % qlabel(peakq))
    else:
        qchart_html = '<div class="qwrap"><div class="qtitle">입주 예정 단지 없음</div></div>'
        qcap = ''
    cap_line = ('앞으로 4년(16분기) 창 · 국토부 건축HUB 준공예정 실측' if hub_sched
                else '앞으로 %s분기 · 입주예정 단지 실측' % r['fq'])
    timeline_html = (
        '<section><div class="wrap"><h2>언제 들어오나</h2>'
        '<p class="note" style="margin-bottom:9px">%s</p>'
        '%s%s</div></section>' % (
            cap_line, qchart_html,
            ('<p class="note" style="margin-top:9px">%s</p>' % qcap) if qcap else ''))

    # ── 인포그래픽: 기여 3카드 (가중 반영, 합계 = tot = 히어로 숫자) ──
    def tcard(lab, sub_, contrib, w):
        col = '#a93226' if contrib > 0 else ('#1a5276' if contrib < 0 else 'var(--muted)')
        return ('<div class="t-card"><div class="t-lab">%s</div><div class="t-sub">%s</div>'
                '<div class="t-val" style="color:%s">%s</div><div class="t-w">영향 %d%%</div></div>'
                % (lab, sub_, col, signed(contrib), w))
    trio_html = ('<div class="trio">%s%s%s</div>' % (
        tcard('입주예정', '2년 안 · 실측', 0.55 * r['dA'], 55),
        tcard('인허가', '3~4년 뒤 · 추정', 0.35 * r['dC'], 35),
        tcard('최근 3년', '입주 실적 · 추정', 0.10 * r['dB'], 10)))

    # Fix I2: inv_path(러닝재고 신모델) 존은 히어로 숫자(tot)가 running_shortage()에서
    # 나오지, dA/dC/dB 가중합(tot_fallback)에서 나오지 않는다. 그런데 trio 카드와
    # "세 값을 더한 것이 맨 위의 숫자입니다" 문구는 dA/dC/dB가 tot를 구성한다고
    # 주장한다 — inv_path 존에서는 이 주장 자체가 거짓이라 숫자가 안 맞는 걸 보고
    # 사용자가 신뢰를 잃는다. inv_path 존은 이 breakdown을 통째로 숨기고 정직한
    # 한 줄 요약으로 바꾼다(폴백 존은 기존 그대로).
    inv = bool(r.get('inv_path'))
    if inv:
        origin_body_html = (
            '<p class="note">적정 공급량 대비 <b>준공(입주 완료)</b>·<b>준공예정</b> 물량 '
            '실측을 누적한 러닝재고 기준 순부족입니다.</p>')
    else:
        origin_body_html = (
            '%s\n'
            '<p class="note" style="margin-top:9px">세 값을 더한 것이 맨 위의 '
            '<b style="color:%s">%s세대</b>입니다. 음수(−)는 부족, 양수(+)는 여유.</p>'
            % (trio_html, tcol, disp))

    # ── 입주 예정 단지 목록 (아실 스타일) — 미래 분기만, 차트·게이지와 동일 규칙 ──
    uraw = list(z.get('units') or [])
    if subs and not uraw:
        for cc in subs:
            uraw += list(cc['z'].get('units') or [])
    ufut = []
    for u in uraw:
        try:
            uy, um = int(u[3][:4]), int(u[3][5:7])
        except (ValueError, IndexError, TypeError):
            continue
        if 1 <= um <= 12 and uy * 4 + (um - 1) // 3 > _curq:
            ufut.append(u)
    ufut.sort(key=lambda u: (u[3], -u[2]))
    if ufut:
        _esc = lambda s: (str(s).replace('&', '&amp;').replace('<', '&lt;')
                          .replace('>', '&gt;').replace('"', '&quot;'))
        urows = ''.join(
            '<tr><td>%s</td><td class="uname" title="%s">%s</td>'
            '<td class="num">%s</td><td class="num">%s</td></tr>' % (
                _esc(u[0]), _esc(u[1]), _esc(u[1]), num(u[2]), u[3].replace('-', '.'))
            for u in ufut)
        unitsec = (
            '<section><div class="wrap">\n'
            '  <h2>입주 예정 단지 <span class="ucnt">%d곳 · %s세대</span></h2>\n'
            '  <div class="ulist"><table class="utable" id="utable">\n'
            '    <thead><tr><th>지역</th><th>단지명</th><th data-num>세대수</th>'
            '<th class="on asc">입주예정</th></tr></thead>\n'
            '    <tbody>%s</tbody>\n'
            '  </table></div>\n'
            '</div></section>\n' % (len(ufut), num(sum(u[2] for u in ufut)), urows))
    else:
        unitsec = ''

    # ── HUB 기반 2섹션(앞으로 들어올 물량/최근 들어온 물량) — 커버된 존만.
    # permits.units에 이 존(또는 수도권처럼 소속 존 합산)이 없으면 render_units_2sec가
    # 빈 문자열을 돌려주고, 그때는 위에서 이미 만든 옛 odcloud 리스트(unitsec)를 그대로 쓴다.
    punits = punits or {}
    zone_units = punits.get(nm) or {}
    if subs and not (zone_units.get('sched') or zone_units.get('done')):
        agg_sched, agg_done = [], []
        for cc in subs:
            uu = punits.get(cc['z']['z']) or {}
            agg_sched += uu.get('sched') or []
            agg_done += uu.get('done') or []
        if agg_sched or agg_done:
            # 수도권은 여러 존의 리스트를 이어붙인 것이라 순서가 존별 블록으로 뒤섞인다.
            # 개수 캡은 두지 않는다 — render_units_2sec의 UNIT_WINDOW(±4년)가 창으로
            # 자른다(2026-07-31: top-N 캡 폐지, 시간 창으로 전환). 세대 큰 순으로
            # 먼저 세워 상위가 앞서게 한 뒤 날짜순(준공예정 오름/준공 내림) 정렬.
            agg_sched = sorted(agg_sched, key=lambda u: -u[1])
            agg_done = sorted(agg_done, key=lambda u: -u[1])
            agg_sched.sort(key=lambda u: u[2] or '9999-99')
            agg_done.sort(key=lambda u: u[2] or '0000-00', reverse=True)
            zone_units = {'sched': agg_sched, 'done': agg_done}
    unitsec2 = render_units_2sec(zone_units, _now)
    hub_units = bool(unitsec2)
    if unitsec2:
        unitsec = unitsec2

    # ── ④ 어느 단지가 들어오나 — 펼친 두 섹션 그대로(2026-07-31 사용자 결정:
    # 접이식보다 기존 UI가 낫다). 창은 render_units_2sec의 UNIT_WINDOW(±4년)가 자른다.
    units_sec_html = unitsec or ''

    rows_html = ''.join([
        '<tr><td class="lbl">앞으로 ' + str(r['fq']) + '분기, 입주 예정<br><span class="note">생활권 실측 · 가중 0.55</span></td>'
        '<td class="num" data-l="적정">%s</td><td class="num" data-l="실제">%s</td><td class="num" data-l="부족분" style="color:%s">%s</td></tr>' % (
            num(r['need']), num(r['fsup']), '#a93226' if r['dA'] > 0 else '#1a5276', signed(r['dA'])),
        '<tr><td class="lbl">인허가 — 3~4년 뒤 입주<br><span class="note">시도 배분 추정 · 가중 0.35</span></td>'
        '<td class="num" data-l="적정">%s</td><td class="num" data-l="실제">%s</td><td class="num" data-l="부족분" style="color:%s">%s</td></tr>' % (
            num(r['plo'] * r['share']) if r['plo'] else '·',
            num((r['pv'] - r['dY']) * r['share']) if r['pv'] is not None else '·',
            '#a93226' if r['dC'] > 0 else '#1a5276', signed(r['dC'])),
        '<tr><td class="lbl">최근 3년, 입주 실적<br><span class="note">시도 배분 추정 · 가중 0.10</span></td>'
        '<td class="num" data-l="적정">%s</td><td class="num" data-l="실제">·</td><td class="num" data-l="부족분" style="color:%s">%s</td></tr>' % (
            num(r['refq'] * LB * r['share']),
            '#a93226' if r['dB'] > 0 else '#1a5276', signed(r['dB'])),
    ])

    # Fix I2(계속): "어떻게 계산했나" 폴드 안의 적정/실제/부족분 표와 그 아래 note도
    # dA/dB/dC(구 dC폴백 산식) 기준이라 inv_path 존에서는 히어로 tot와 안 맞는다.
    # inv_path 존은 표·note를 숨기고, 러닝재고 기준이라는 짧은 설명만 남긴다.
    if inv:
        calc_detail_html = (
            '<p class="note" style="margin-top:10px">이 존은 준공(입주 완료)·준공예정 물량 '
            '실측을 기반으로 하는 <b>러닝재고</b> 방식입니다. 적정 공급량 대비 쌓인 재고와 '
            '앞으로 %s분기의 준공예정을 함께 반영한 누적 순부족입니다.</p>' % FUT_HORIZON)
    else:
        calc_detail_html = (
            '<table>\n'
            '    <thead><tr><th>구간</th><th>적정</th><th>실제</th><th>부족분</th></tr></thead>\n'
            '    <tbody>%s</tbody>\n'
            '  </table>\n'
            '  <p class="note" style="margin-top:10px">부족은 재고처럼 쌓이므로 <b>3년</b>을 봅니다'
            '(멸실 뺀 순공급).<br>인허가·최근 실적은 시군구 통계가 없어 '
            '<b>시도(%s) 값을 인구 비중으로 배분한 추정치</b>이고, 입주예정만 단지 주소 기반 실측입니다.</p>'
            % (rows_html, ps))

    # ★(watch) 섹션은 2026-07-31 제거 — "실거주 유리" 표기가 투자 추천처럼 읽히는
    # 오해 소지(홈 리스트 보라 별표 삭제와 같은 결정). ⚠(warn)는 위험 경고라 유지.
    flag_html = ''
    if r['flag'] == 'warn':
        flag_html = ('<section><div class="wrap"><h2>⚠ 보유 부담이 큰 구간입니다</h2>'
            '<p>%s의 주택담보대출 금리(<b>%.2f%%</b>)가 임대수익률의 두 배(위험선 <b>%.1f%%</b>)를 넘었습니다. '
            '대출로 사서 보유하면 <b>이자가 월세로 받을 수 있는 돈의 두 배를 넘는다</b>는 뜻입니다. '
            '과거 2008년·2022년 급락기가 이 조건에서 시작됐습니다. 공급이 모자라더라도 보유 비용이 수익을 잠식하는 구간이라 '
            '진입 시점은 신중히 볼 필요가 있습니다.</p></div></section>' % (ps, r['loan'], r['hi']))

    # 예전에는 수도권 소속 생활권을 네비에서 통째로 뺐다. 그 결과 서울권·인천권 등
    # 16장이 인바운드 링크 1개짜리 고아가 됐다 — 검색 수요가 가장 큰 페이지들이
    # 링크 자산을 가장 적게 받는 역전이었다.
    nav = '<a href="/zone/"><b>전체 생활권</b></a>'
    nav += '<a href="/zone/수도권/">수도권</a>' if nm != '수도권' else ''
    nav += ''.join('<a href="/zone/%s/">%s</a>' % (x['z']['z'], x['z']['z'])
                   for x in allrows if x['z']['z'] != nm)

    # ── ⑤ 이 숫자의 한계 — breakdown_sec_html/calc_detail_html(방법론) +
    # 기존 구성/주의점 폴드를 details로 흡수(삭제 없이 재배치, 6섹션 구조 유지)
    origin_fold_html = (
        '<details class="fold"><summary>이 숫자는 어디서 왔나</summary><div class="dbody">\n'
        '%s\n</div></details>' % origin_body_html)
    calc_fold_html = (
        '<details class="fold"><summary>어떻게 계산했나</summary><div class="dbody">\n'
        '<p><b>적정물량</b>은 과거 이 지역의 가격이 하락에서 상승으로 방향을 바꾼 시점의 입주물량을 실측해 잡은 기준선입니다.</p>\n'
        '%s\n</div></details>' % calc_detail_html)
    compo_fold_html = (
        '<details class="fold"><summary>이 생활권은 어디를 묶었나</summary><div class="dbody">\n'
        '<p>행정구역이 아니라 <b>하나의 주택시장처럼 움직이는 범위</b>로 묶었습니다.</p>\n'
        '<div class="card"><b>%s 구성</b><span>%s</span></div>%s\n'
        '<p class="note">입주예정은 단지 주소 기반 <b>실측치</b>(%s).</p>\n'
        '</div></details>' % (nm, members, sublist, span))
    caution_fold_html = (
        '<details class="fold"><summary>이 숫자를 읽을 때 주의할 점</summary><div class="dbody">\n'
        '<div class="card"><b>공급은 3년 전에 결정된다</b><span>오늘 인허가받은 아파트는 3년쯤 뒤에 입주합니다. 즉 지금 보이는 입주예정 물량은 이미 확정된 미래이고, 바꿀 수 없습니다.</span></div>\n'
        '<div class="card"><b>부족이 곧 상승은 아니다</b><span>공급 부족은 가격을 밀어올리는 힘이지만, 금리·규제·수요 같은 다른 힘과 함께 작동합니다. 이 지표는 그중 <b>공급</b> 한 축만 정확히 보여줍니다.</span></div>\n'
        '<div class="card"><b>순위는 비율, 숫자는 절대량</b><span>등급과 순위는 그 지역이 4년간 필요한 양 대비 몇 %%가 모자라는지로 매깁니다. 그래서 작은 지역의 가뭄도 큰 도시와 나란히 비교됩니다. 화면에 보이는 세대수는 체감을 위한 절대량이라, 순위와 크기 순서가 다를 수 있습니다.</span></div>\n'
        '</div></details>')
    methodology_details_html = (
        origin_fold_html + calc_fold_html + compo_fold_html + caution_fold_html +
        '<a class="cta" href="/cycle/">사이클 리포트 읽기 →</a>')
    # 이천·평택 공시(2026-08-01 사용자 결정): 이 두 곳은 수도권 가격 사이클과
    # 독립적으로 움직이는 것으로 실측됐지만(잔차 동조 0.14 이하), 자체 적정물량
    # 역산이 표본 부족(금리쇼크 저점 제외 시 전환점 1개)으로 불가해 수도권 안분을
    # 유지한다 — 그 사실을 숨기지 않고 명시한다.
    indep_note = ''
    if nm in INDEP_ZONES:
        indep_note = ('<p class="note"><b>이 지역만의 참고</b>: %s 가격은 수도권 사이클과 '
                      '독립적으로 움직이는 것으로 실측됐습니다. 위 \'필요한 집\'은 수도권 기준 '
                      '배분값이라 실제 지역 수요와 다를 수 있습니다 — 다음 가격 전환점이 '
                      '확인되면 이 지역만의 값으로 다시 계산할 예정입니다.</p>' % nm)
    limits_html = (
        '<section><div class="wrap"><h2>이 숫자의 한계</h2>'
        '<p class="note">가격을 맞히는 지표가 아닙니다. 2010년 이후 44개 생활권으로 직접 확인한 결과, '
        '금리가 크게 움직인 시기에는 공급이 가격에 준 영향이 거의 보이지 않았습니다. '
        '금리가 잔잔했던 시기에는 공급이 적었던 곳이 이후 2년간 평균 2%%p 남짓 더 올랐을 뿐입니다. '
        '이 페이지는 <b>이 동네 공급 사정</b>으로만 읽어주세요.</p>'
        '%s%s</div></section>' % (indep_note, methodology_details_html))

    # ── C1(최우선 회귀): nav/zlist/CTA는 near의 존재 여부와 무관하게 '항상' 렌더한다.
    # 예전엔 이 44존 전체 링크 + /#score CTA가 near 섹션 안에 있어서, near가 빈
    # 7개 시도(부산·대구·대전세종·광주·울산·청주·제주권 — 시도에 존이 하나뿐)에서
    # 통째로 사라져 그 페이지들의 아웃바운드 /zone/ 링크가 0이 됐다(727행 주석이
    # 경고한 고아 페이지). nav 섹션을 near와 분리해 모든 페이지에 항상 낸다.
    nav_html = (
        '<section><div class="wrap"><h2>다른 생활권도 보기</h2>'
        '<div class="zlist">%s</div>'
        '<a class="cta sub" href="/#score">전국 생활권 순위 한눈에 보기 →</a>'
        '</div></section>' % nav)

    # ── ⑥ 주변과 비교하면 — 같은 시도(ps) 생활권 미니 카드(최대 4곳).
    # 시도에 존이 하나뿐이면(위 7곳) 같은 region(경상·전라 등)으로 넓히고,
    # 그래도 못 채우면(제주권처럼 region에도 혼자인 경우) 전국에서 채운다 —
    # "카드가 아예 안 뜨는" 상태를 만들지 않기 위한 최후 단계.
    near = [x for x in allrows if x['ps'] == ps and x['z']['z'] != nm]
    seen = {x['z']['z'] for x in near} | {nm}
    if len(near) < 4:
        reg = z.get('region')
        for x in allrows:
            if len(near) >= 4:
                break
            if x['z'].get('region') == reg and x['z']['z'] not in seen:
                near.append(x); seen.add(x['z']['z'])
    if len(near) < 4:
        for x in allrows:
            if len(near) >= 4:
                break
            if x['z']['z'] not in seen:
                near.append(x); seen.add(x['z']['z'])
    near = near[:4]
    if near:
        near_html = (
            '<section><div class="wrap"><h2>주변과 비교하면</h2><div class="near">' +
            ''.join('<a class="n-card" href="/zone/%s/"><b>%s</b>'
                    '<span class="n-g" style="color:%s">%s</span><i>%s</i></a>'
                    % (x['z']['z'], x['z']['z'], x['gr']['color'], x['gr']['label'],
                       signed(x['tot']))
                    for x in near) +
            '</div></div></section>')
    else:
        near_html = ''

    # ── 암묵 저장(2026-07-31) — 버튼 없이 페이지를 보면 이 존을 '내 지역'으로 기억.
    # 같은 존을 다시 보면 last(지난 방문 기록)를 보존해 홈의 diff 표시가 살아있게 하고,
    # 다른 존이면 이 페이지의 빌드 시점 값으로 last를 초기화한다(엉뚱한 diff 방지).
    # 수도권 합계 페이지는 선택 가능한 존이 아니라 기억하지 않는다.
    if subs:
        save_js = ''
    else:
        save_js = (
            '<script>try{var _mz=null;try{_mz=JSON.parse(localStorage.getItem("agong_myzone"))}catch(e){}'
            'var _same=_mz&&_mz.z===%s;'
            'localStorage.setItem("agong_myzone",JSON.stringify({z:%s,'
            'savedAt:(_same&&_mz.savedAt)||%s,'
            'last:(_same&&_mz.last)||{tot:%d,rank:%d,grade:%s,seen:%s}}));'
            '}catch(e){}</script>'
            % (json.dumps(nm, ensure_ascii=False), json.dumps(nm, ensure_ascii=False),
               json.dumps(str(today)), round(r['tot']), rank_no,
               json.dumps(gr['label'], ensure_ascii=False), json.dumps(str(today))))

    # 시세 그래프 hover — 월별 히트영역에 올리면 세로선·표식점·툴팁(그 달 변동률).
    # 정적 페이지라 인라인 스크립트로 자족 동작한다(그래프 없으면 no-op).
    if idx_html:
        save_js += (
            '<script>(function(){var w=document.querySelector(".pidx");if(!w)return;'
            'var svg=w.querySelector("svg"),tip=w.querySelector(".px-tip");'
            'if(!svg||!tip)return;var d;try{d=JSON.parse(svg.getAttribute("data-tip"))}catch(e){return}'
            'var mk=svg.querySelector(".px-mk"),vl=svg.querySelector(".px-vline"),'
            'dots=svg.querySelectorAll(".px-dot"),lines=svg.querySelectorAll("polyline"),'
            'hits=svg.querySelectorAll(".px-hit");'
            'function pts(p){return p.getAttribute("points").split(" ").map(function(s){'
            'var a=s.split(",");return [parseFloat(a[0]),parseFloat(a[1])]})}'
            'var P=[].map.call(lines,pts);'
            'function show(i){if(!P.length||!P[0][i])return;mk.style.display="";'
            'vl.setAttribute("x1",P[0][i][0]);vl.setAttribute("x2",P[0][i][0]);'
            'for(var k=0;k<dots.length;k++){if(!P[k]||!P[k][i]){dots[k].style.display="none";continue}'
            'dots[k].style.display="";dots[k].setAttribute("cx",P[k][i][0]);dots[k].setAttribute("cy",P[k][i][1])}'
            'var h="<b>"+d.m[i]+"</b>";'
            'for(var s=0;s<d.s.length;s++){var v=d.s[s].v[i];if(v==null)continue;'
            'h+="<br><i style=\\"background:"+d.s[s].c+"\\"></i>"+d.s[s].k+" "+(v>0?"+":"")+v.toFixed(2)+"%"}'
            'tip.innerHTML=h;tip.hidden=false;tip.style.opacity=1;'
            'var b=svg.getBoundingClientRect(),wb=w.getBoundingClientRect(),'
            'x=b.left-wb.left+P[0][i][0]/svg.viewBox.baseVal.width*b.width,'
            'y=b.top-wb.top+P[0][i][1]/svg.viewBox.baseVal.height*b.height;'
            'tip.style.left=Math.max(0,Math.min(x+10,wb.width-tip.offsetWidth-2))+"px";'
            'tip.style.top=Math.max(0,y-tip.offsetHeight-8)+"px"}'
            'function hide(){mk.style.display="none";tip.style.opacity=0;tip.hidden=true}'
            '[].forEach.call(hits,function(r){var i=+r.getAttribute("data-i");'
            'r.addEventListener("mouseenter",function(){show(i)});'
            'r.addEventListener("touchstart",function(){show(i)},{passive:true})});'
            'svg.addEventListener("mouseleave",hide);'
            # 터치로 연 툴팁은 그래프 밖을 누르면 닫는다(모바일엔 mouseleave가 없다)
            'document.addEventListener("touchstart",function(e){if(!svg.contains(e.target))hide()},{passive:true});'
            '})();</script>')

    title = '%s 아파트 공급 분석 — 준공·입주예정으로 본 %s | 아공맵' % (nm, tname)
    # sgg가 비면 '구성: —'가 그대로 메타 설명에 나갔다. odcloud는 물량이 없는
    # 지역의 행을 보내지 않으므로, 빈 sgg는 '입주예정 단지가 없다'는 뜻이다.
    comp = ('구성: %s. ' % ', '.join(sgg_names[:3])) if sgg_names else '예정 단지 없음. '
    desc = ('%s의 아파트 공급은 적정물량 대비 %s세대(%s). 입주예정 %s세대, %s'
            '한국부동산원·국토교통부 통계로 매주 자동 갱신.' % (
                nm, disp, tname, num(z['supply']), comp))

    ld = {
        "@context": "https://schema.org", "@type": "Article",
        "headline": '%s 아파트 공급 분석' % nm,
        "description": desc,
        "datePublished": today, "dateModified": today,
        "author": {"@type": "Organization", "name": "아공맵"},
        "publisher": {"@type": "Organization", "name": "아공맵"},
        "mainEntityOfPage": '%s/zone/%s/' % (SITE, quote(nm)),
        "about": {"@type": "Place", "name": nm},
    }
    # 한 script 안에 [Article, BreadcrumbList] 배열 — Google이 배열 표기를 지원한다.
    ld = [ld, {
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "아공맵",
             "item": '%s/' % SITE},
            {"@type": "ListItem", "position": 2, "name": "생활권 공급 분석",
             "item": '%s/zone/' % SITE},
            {"@type": "ListItem", "position": 3, "name": nm},
        ],
    }]

    return """<!DOCTYPE html>
<html lang="ko">
<head>
<script async src="https://www.googletagmanager.com/gtag/js?id=G-3FJNG6G1F3"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','G-3FJNG6G1F3');</script>
<script>document.addEventListener('click',function(e){var a=e.target&&e.target.closest?e.target.closest('a[href]'):null;if(!a)return;var h=a.getAttribute('href');if(!h||h.charAt(0)!=='/')return;try{gtag('event','zone_cta',{to:h,zone:'%(nm)s'});}catch(err){}});</script>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.css">
<title>%(title)s</title>
<meta name="description" content="%(desc)s">
<link rel="canonical" href="%(site)s/zone/%(enc)s/">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="icon" type="image/png" href="/app_icon.png">
<meta name="theme-color" content="#16203a">
<meta property="og:type" content="article">
<meta property="og:title" content="%(nm)s 아파트 공급 분석 — %(tname)s">
<meta property="og:description" content="%(desc)s">
<meta property="og:url" content="%(site)s/zone/%(enc)s/">
<meta property="og:image" content="%(site)s/og-brand.png">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">%(ld)s</script>
<style>%(css)s</style>
</head>
<body>

<header><div class="wrap">
  <div class="chip">아공맵 생활권 리포트</div>
  %(hero)s
</div></header>

%(why)s
%(timeline)s
%(units)s
%(flag)s
%(limits)s
%(near)s
%(nav)s

<footer><div class="wrap">
  <b>아공맵</b> — 아파트 · 공급량 · 투자지도<br>
  <a href="/">agongmap.co.kr</a> · 자료: 한국부동산원 입주예정물량 · 국토교통부 주택건설실적 · 행정안전부 주민등록인구 · 한국은행
  <div class="disc">본 페이지는 공개된 국가통계를 가공한 정보 제공 목적의 자료이며, 특정 부동산의 매수·매도를 권유하거나 투자 수익을 보장하지 않습니다. 투자 판단과 그 결과는 이용자 본인에게 귀속됩니다.</div>
</div></footer>

<nav class="bottomnav">
  <a class="nav-btn" href="/"><svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M3 11l9-8 9 8M5 10v10h14V10" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg><span>홈</span></a>
  <a class="nav-btn" href="/#test"><svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><circle cx="7.4" cy="12" r="4.4" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="7.4" cy="12" r="1.7" fill="currentColor"/><circle cx="16.6" cy="12" r="4.4" fill="none" stroke="currentColor" stroke-width="2"/></svg><span>퀴즈</span></a>
  <a class="nav-btn" href="/#stats"><svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg><span>통계</span></a>
  <a class="nav-btn" href="/cycle/"><svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.34-5.66" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M20.3 3.7v5h-5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg><span>리포트</span></a>
</nav>

<script>
(function(){
  var t=document.getElementById('utable'); if(!t) return;
  var tb=t.tBodies[0], ths=t.tHead.rows[0].cells, cur=3, dir=1;
  function val(row,k,isNum){
    var s=row.cells[k].textContent.trim();
    return isNum ? (parseFloat(s.replace(/[^0-9.-]/g,''))||0) : s;
  }
  Array.prototype.forEach.call(ths, function(h,i){
    h.addEventListener('click', function(){
      var isNum=h.hasAttribute('data-num');
      dir=(cur===i)?-dir:1; cur=i;
      var rows=Array.prototype.slice.call(tb.rows);
      rows.sort(function(a,b){
        var x=val(a,i,isNum), y=val(b,i,isNum);
        return (x<y?-1:x>y?1:0)*dir;
      });
      rows.forEach(function(rw){ tb.appendChild(rw); });
      Array.prototype.forEach.call(ths, function(o){ o.classList.remove('on','asc','desc'); });
      h.classList.add('on', dir>0?'asc':'desc');
    });
  });
})();
</script>
%(save_js)s

</body>
</html>""" % dict(
        title=title, desc=desc, site=SITE, nm=nm, enc=quote(nm), tname=tname, tcol=tcol, disp=disp,
        ranktxt=ranktxt, prd=prd, fq=r['fq'],
        hero=hero_html, why=why_html, timeline=timeline_html, units=units_sec_html,
        flag=flag_html, limits=limits_html, near=near_html, nav=nav_html, save_js=save_js,
        ld=json.dumps(ld, ensure_ascii=False),
        css=CSS)


DATE_RE = re.compile(r'"date(?:Published|Modified)": "(\d{4}-\d{2}-\d{2})"')


def strip_dates(html):
    """날짜만 지운 본문 — '내용이 실제로 바뀌었나'의 판정 기준."""
    return DATE_RE.sub('"date": "-"', html or '')


def read_old(path):
    try:
        return io.open(path, encoding='utf-8').read()
    except IOError:
        return ''


def keep_dates(new_html, old_html, today):
    """내용이 같으면 옛 날짜를 그대로 둔다. (반환: html, lastmod, 변경여부)

    이 배치는 매일 돈다. 예전에는 today를 무조건 심어서, 데이터가 하나도
    안 바뀐 날에도 37장과 sitemap의 lastmod가 날짜만 바뀐 채 커밋됐다.
    검색엔진에 '매일 갱신'이라 신고하면서 내용은 그대로면 신선도 신호의
    신뢰도가 깎이고, 최초 발행일이어야 할 datePublished마저 매일 리셋됐다.
    """
    if not old_html or strip_dates(new_html) != strip_dates(old_html):
        return new_html, today, True
    olds = DATE_RE.findall(old_html)
    if len(olds) < 2:
        return new_html, today, True
    pub, mod = olds[0], olds[1]
    out = new_html.replace('"datePublished": "%s"' % today, '"datePublished": "%s"' % pub, 1)
    out = out.replace('"dateModified": "%s"' % today, '"dateModified": "%s"' % mod, 1)
    return out, mod, False


HUB_TPL = u"""<!DOCTYPE html>
<html lang="ko">
<head>
<script async src="https://www.googletagmanager.com/gtag/js?id=G-3FJNG6G1F3"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}
gtag('js',new Date());gtag('config','G-3FJNG6G1F3');</script>
<script>document.addEventListener('click',function(e){var a=e.target&&e.target.closest?e.target.closest('a[href]'):null;if(!a)return;var h=a.getAttribute('href');if(!h||h.charAt(0)!=='/')return;try{gtag('event','zone_cta',{to:h,zone:'hub'});}catch(err){}});</script>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>전국 생활권 아파트 공급 순위 %(n)d곳 — 준공·입주예정으로 본 부족·과잉 | 아공맵</title>
<meta name="description" content="전국 %(n)d개 생활권의 아파트 공급을 적정물량과 비교해 누적 순부족 순으로 정렬했습니다. 공급 절벽부터 공급 과잉까지 한눈에. 기준 %(prd)s.">
<link rel="canonical" href="%(site)s/zone/">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="icon" type="image/png" href="/app_icon.png">
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="#16203a">
<meta property="og:type" content="website">
<meta property="og:title" content="전국 생활권 아파트 공급 순위 %(n)d곳">
<meta property="og:description" content="적정물량 대비 누적 순부족 순. 공급 절벽부터 과잉까지.">
<meta property="og:url" content="%(site)s/zone/">
<meta property="og:image" content="%(site)s/og-brand.png">
<script type="application/ld+json">
%(ld)s
</script>
<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.css">
<style>
b,strong{font-weight:600}:root{--ink:#131e24;--paper:#f4f6f5;--paper2:#e9edeb;--line:#c4cec9;--muted:#5e6f74;--body:#4c5f66}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--paper);color:var(--body);word-break:keep-all;padding-bottom:78px;
 font-family:'Pretendard Variable','Pretendard',-apple-system,'Malgun Gothic',sans-serif;line-height:1.7}
.wrap{max-width:660px;margin:0 auto;padding:0 20px}
header{padding:46px 0 26px;border-bottom:1px solid var(--line)}
h1{font-size:clamp(23px,5.4vw,31px);color:var(--ink);letter-spacing:-.02em;line-height:1.32}
.lead{color:var(--muted);font-size:14.5px;margin-top:10px}
section{padding:26px 0;border-bottom:1px solid var(--line)}
h2{font-size:18px;color:var(--ink);margin-bottom:6px}
p{font-size:14.5px;margin:8px 0}
table{width:100%%;border-collapse:collapse;font-size:14.5px;margin-top:12px}
th,td{padding:10px 8px;border-bottom:1px solid var(--line)}
td{text-align:left}
th{font-size:12px;letter-spacing:.04em;color:var(--muted);white-space:nowrap;text-align:center}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
td.rk{color:var(--muted);width:2.2em;text-align:right;font-variant-numeric:tabular-nums}
a.z{color:var(--ink);text-decoration:none;font-weight:600}
a.z:hover{text-decoration:underline}
.ghead td{border:0;padding:16px 0 4px;font-weight:700;font-size:13px}
  .ghead i{font-style:normal;font-weight:400;color:#8a969b;font-size:11.5px}
  .tag{font-size:11.5px;font-weight:600;padding:2px 7px;border-radius:0;white-space:nowrap}
.tag.g4{background:#fdecea;color:#a93226}
.tag.g3{background:#fbeee9;color:#c0392b}
.tag.g2{background:#faf3e7;color:#b9770e}
.tag.g1{background:#edf0ee;color:#5e6f74}
.tag.g0{background:#e9f0f7;color:#1a5276}
.bottomnav{position:fixed;bottom:0;left:0;right:0;height:62px;background:var(--ink);
 display:flex;justify-content:center;z-index:100}
.nav-btn{flex:1;max-width:220px;display:flex;flex-direction:column;align-items:center;
 justify-content:center;gap:3px;color:#97a0b8;font-size:11.5px;font-weight:600;text-decoration:none}
.nav-btn svg{display:block}
footer{padding:24px 0 40px;color:var(--muted);font-size:12.5px}
footer a{color:var(--muted)}
</style>
</head>
<body>
<header><div class="wrap">
  <h1>전국 어디가 모자라고 어디가 남나</h1>
  <p class="lead">생활권 %(n)d곳을 <b>공급 부족 등급</b>으로 묶었습니다.
    등급은 그 지역에 필요한 양 대비 얼마나 모자라는지의 비율이고,
    숫자는 세대수입니다(음수 −는 모자람, 양수 +는 남음). 기준 %(prd)s.</p>
</div></header>

<section><div class="wrap">
  <h2>등급별 순위</h2>
  <p>생활권 이름을 누르면 판정 근거(밀린 것·필요한 집·들어올 집)와 분기별 입주 일정,
    그 지역 아파트값 흐름까지 볼 수 있습니다.</p>
  <p style="color:var(--muted);font-size:12.5px">공급 기준 · 가격 예측 아님</p>
  <table>
    <thead><tr><th>#</th><th>생활권</th><th class="num">누적 순부족</th><th>판정</th></tr></thead>
    <tbody>
%(rows)s
    </tbody>
  </table>
</div></section>

<section><div class="wrap">
  <h2>이 숫자는 무엇인가</h2>
  <p><b>순부족</b>은 그 지역에 <b>그동안 밀린 부족</b>과 <b>앞으로 4년간 필요한 양</b>을 더한 뒤,
    <b>이미 준공예정이 잡힌 물량</b>을 뺀 값입니다(세대수). 공급은 국토부 건축HUB 단지별 실측이고,
    필요량만 시장 단위로 배분한 추정입니다.</p>
  <p>공급이 모자란다고 값이 반드시 오르는 것도, 남는다고 반드시 내리는 것도 아닙니다.
    공급은 사이클을 움직이는 여러 힘 가운데 하나이며, 금리·전세가율·심리가 함께 작용합니다.
    <a href="/cycle/">사이클이 어떻게 도는지 보기 →</a></p>
</div></section>

<footer><div class="wrap">
  <b>아공맵</b> — 아파트 · 공급량 · 투자지도<br>
  <a href="/">agongmap.co.kr</a> · 자료: 한국부동산원 입주예정물량 · 국토교통부 주택건설실적 · 행정안전부 주민등록인구<br>
  <a href="/privacy/">개인정보처리방침</a> · 본 자료는 공공 데이터를 가공한 참고 자료이며 투자자문이 아닙니다.
</div></footer>

<nav class="bottomnav">
  <a class="nav-btn" href="/"><svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M3 11l9-8 9 8M5 10v10h14V10" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg><span>홈</span></a>
  <a class="nav-btn" href="/#test"><svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><circle cx="7.4" cy="12" r="4.4" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="7.4" cy="12" r="1.7" fill="currentColor"/><circle cx="16.6" cy="12" r="4.4" fill="none" stroke="currentColor" stroke-width="2"/></svg><span>퀴즈</span></a>
  <a class="nav-btn" href="/#stats"><svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg><span>통계</span></a>
  <a class="nav-btn" href="/cycle/"><svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.34-5.66" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M20.3 3.7v5h-5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg><span>리포트</span></a>
</nav>

<script>
if('serviceWorker' in navigator){window.addEventListener('load',function(){navigator.serviceWorker.register('/sw.js').catch(function(){});});}
</script>
</body>
</html>
"""


def build_hub(pages, prd, today):
    """전 생활권을 한 페이지에 모은 허브.

    존재 이유는 링크다. 홈의 생활권 타일은 JS 런타임 생성이라 정적 HTML에
    /zone/ 링크가 하나도 없었고, 37장의 사실상 유일한 발견 경로가 sitemap이었다.
    sitemap은 발견은 시켜주지만 링크 가치를 전달하지 않는다.
    """
    # 입주예정 0은 '자료 없음'이 아니라 그냥 0이다(3c897f7 확정). 전부 순위에 넣는다.
    # 다만 수도권은 16개 생활권을 묶은 상위 단위라 개별 생활권과 같은 순위표에
    # 넣으면 이중 계상이 되고, 그 아래 행이 상세 페이지와 1씩 어긋난다.
    # 홈(index.html)이 이미 쓰는 방식대로 순위 밖 소계로 분리한다.
    ROLLUP = '수도권'
    # 정렬 기준 = 비율(순부족/4년 필요량) — 등급·본문 순위와 같은 잣대(2026-07-31).
    live = sorted([r for r in pages if r['z']['z'] != ROLLUP],
                  key=lambda r: -(r['tot'] / r['need4'] if r['need4'] else 0))
    roll = next((r for r in pages if r['z']['z'] == ROLLUP), None)
    # ⚠️ 표시 번호는 '비율 순위'여야 한다 — 존 페이지의 "생활권 44곳 중 N위"와
    # 홈 히어로(mzRank)가 모두 비율 기준이라, 여기만 표시 순서대로 번호를 매기면
    # 같은 존이 화면마다 다른 순위로 보인다(2026-08-01 리뷰 C1: 31/44곳 불일치,
    # 서울권 허브 #1 vs 페이지 5위). live는 이미 비율 내림차순이므로 그 인덱스를 쓴다.
    # 여기는 '#' 번호가 있는 순위표다 — 정렬도 그 번호와 같은 잣대(비율)여야 한다.
    # 등급 구간이 비율 경계라 비율 정렬만으로 그룹이 이어지고 #도 1..44 순차가 된다.
    # (2026-08-01: 번호만 비율로 바꾸고 정렬은 절대값으로 둬서 5,6,1,3,4,2,7처럼
    #  뒤죽박죽 나왔다. 홈은 번호가 없으니 그룹 안 절대값 정렬 그대로 유지 — 다른 화면
    #  다른 규칙이 아니라, 번호가 있느냐 없느냐에 따른 것.)
    rows = []
    prev_gk = None
    for i, r in enumerate(live):
        nm = r['z']['z']
        gr = r['gr']
        if gr['k'] != prev_gk:
            n_in = sum(1 for x in live if x['gr']['k'] == gr['k'])
            rows.append('      <tr class="ghead"><td colspan="4" style="color:%s">%s '
                        '<i>%d곳</i></td></tr>' % (gr['color'], gr['label'], n_in))
            prev_gk = gr['k']
        rows.append(
            '      <tr><td class="rk">%d</td><td><a class="z" href="/zone/%s/">%s</a></td>'
            '<td class="num" style="color:%s" title="필요량 대비 %s">%s</td>'
            '<td><span class="tag %s">%s</span></td></tr>'
            % (i + 1, nm, nm, gr['color'],
               ('%+.0f%%' % (-100 * r['tot'] / r['need4']) if r['need4'] else '·'),
               signed(r['tot']), gr['k'], gr['label']))
    if roll is not None:
        gr = roll['gr']
        sub = len(roll['z'].get('subs') or []) or 16
        rows.append(
            '      <tr class="rollup"><td class="rk">—</td>'
            '<td><a class="z" href="/zone/%s/">%s</a> <span class="sub">%d개 생활권 합계</span></td>'
            '<td class="num" style="color:%s">%s</td><td><span class="tag %s">%s</span></td></tr>'
            % (ROLLUP, ROLLUP, sub, gr['color'], signed(roll['tot']), gr['k'], gr['label']))
    ld = json.dumps([{
        "@context": "https://schema.org", "@type": "Article",
        "headline": "전국 생활권 아파트 공급 순위",
        "description": "전국 %d개 생활권의 아파트 공급을 적정물량과 비교해 누적 순부족 순으로 정렬." % len(live),
        "datePublished": today, "dateModified": today,
        "author": {"@type": "Organization", "name": "아공맵"},
        "publisher": {"@type": "Organization", "name": "아공맵"},
        "mainEntityOfPage": '%s/zone/' % SITE,
    }, {
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "아공맵",
             "item": '%s/' % SITE},
            {"@type": "ListItem", "position": 2, "name": "생활권 공급 분석"},
        ],
    }], ensure_ascii=False, indent=2)
    return HUB_TPL % dict(n=len(live), prd=prd, site=SITE, ld=ld,
                          rows='\n'.join(rows))


def update_sitemap(names, lastmods):
    p = os.path.join(ROOT, 'sitemap.xml')
    x = io.open(p, encoding='utf-8').read()
    x = re.sub(r'\s*<url>\s*<loc>[^<]*/zone/[^<]*</loc>.*?</url>', '', x, flags=re.S)
    x = re.sub(r'\s*<url>\s*<loc>[^<]*/zone/</loc>.*?</url>', '', x, flags=re.S)
    newest = max(lastmods.values()) if lastmods else ''
    # 홈·주간 페이지도 같은 주간 데이터로 움직이므로 lastmod를 함께 민다.
    # (zone이 안 바뀐 주엔 newest도 그대로라 불필요한 갱신이 없다)
    if newest:
        for loc in ('%s/' % SITE, '%s/weekly/' % SITE):
            x = re.sub(
                r'(<loc>%s</loc>\s*<lastmod>)[^<]*(</lastmod>)' % re.escape(loc),
                r'\g<1>%s\g<2>' % newest, x)
    block = ('\n  <url>\n    <loc>%s/zone/</loc>\n    <lastmod>%s</lastmod>\n'
             '    <changefreq>weekly</changefreq>\n    <priority>0.8</priority>\n  </url>'
             % (SITE, newest))
    block += ''.join(
        '\n  <url>\n    <loc>%s/zone/%s/</loc>\n    <lastmod>%s</lastmod>\n'
        '    <changefreq>weekly</changefreq>\n    <priority>0.7</priority>\n  </url>'
        % (SITE, quote(n), lastmods.get(n, ''))
        for n in names)
    x = x.replace('</urlset>', block + '\n</urlset>')
    io.open(p, 'w', encoding='utf-8', newline='\n').write(x)


def main():
    adv, sts = load()
    rows = calc(adv, sts)
    punits = (adv.get('permits') or {}).get('units') or {}
    prd = adv['livezone'].get('prd', '')
    today = datetime.date.today().isoformat()
    outdir = os.path.join(ROOT, 'zone')
    # ⚠️ 삭제 전에 읽어야 한다 — 날짜 유지 판정에 옛 내용이 필요하다.
    old_pages = {}
    if os.path.isdir(outdir):
        for d in os.listdir(outdir):
            fp = os.path.join(outdir, d, 'index.html')
            if os.path.exists(fp):
                old_pages[d] = read_old(fp)
    old_hub = read_old(os.path.join(outdir, 'index.html'))
    # 옛 페이지 정리(생활권 구성이 바뀌었을 수 있음)
    if os.path.isdir(outdir):
        for d in os.listdir(outdir):
            fp = os.path.join(outdir, d, 'index.html')
            if os.path.exists(fp):
                os.remove(fp)
            if os.path.isdir(os.path.join(outdir, d)) and not os.listdir(os.path.join(outdir, d)):
                os.rmdir(os.path.join(outdir, d))
    cap = make_capital(rows)
    pages = list(rows) + ([cap] if cap else [])
    # 존별 시세 지수 HTML 사전(수도권 합계는 소속 존 코드 합집합)
    zcodes = zone_sgg_codes(adv)
    if cap:
        agg_codes = sorted({c for sub in (cap['z'].get('subs') or []) for c in zcodes.get(sub, [])}
                           or {c for z in rows if z['z']['region'] == '수도권'
                               for c in zcodes.get(z['z']['z'], [])})
        zcodes[cap['z']['z']] = agg_codes
    pidx = {z: render_price_index(adv, z, cs) for z, cs in zcodes.items()}
    names, lastmods, nchanged = [], {}, 0
    for r in pages:
        nm = r['z']['z']
        d = os.path.join(outdir, nm)
        os.makedirs(d, exist_ok=True)
        html, lm, ch = keep_dates(build_page(r, rows, prd, today, punits, pidx), old_pages.get(nm, ''), today)
        io.open(os.path.join(d, 'index.html'), 'w', encoding='utf-8', newline='\n').write(html)
        names.append(nm)
        lastmods[nm] = lm
        nchanged += 1 if ch else 0
    hub, _, _ = keep_dates(build_hub(pages, prd, today), old_hub, today)
    io.open(os.path.join(outdir, 'index.html'), 'w', encoding='utf-8', newline='\n').write(hub)
    update_sitemap(names, lastmods)
    print('zone pages: %d개 + 허브 1개 생성 (내용 변경 %d개) → /zone/ · sitemap 갱신'
          % (len(names), nchanged))


if __name__ == '__main__':
    main()
