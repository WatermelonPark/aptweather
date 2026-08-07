# -*- coding: utf-8 -*-
"""시도 20곳의 공급 지표 — 국토부 준공·착공만으로 계산한다.

왜 이 모듈이 따로 있나: 2026-08-06 이전에는 미래 공급을 건축HUB **준공예정**으로
셌는데, 그건 인허가만 받고 삽을 안 뜬 계획이었다(2028년 입주예정 363,701세대 중
착공 0건 — 데이터 누락이 아니라 사실. 준공된 단지의 착공일 보유율은 연도별로 전부
100%다). 착공 기반 추정 대비 1.29~1.68배 과대였고, 그게 "서울이 균형으로 나온다"의
원인이었다. 설계 근거는 docs/superpowers/specs/2026-08-06-sido-supply-table-design.md.

핵심: **착공과 준공은 같은 통계표(국토부 주택건설실적)의 두 열**이라 정의가 일치하고
오차가 같은 방향으로 걸린다. 착공을 3년 뒤로 밀면 준공과 맞는다(전환율 0.958,
변동계수 0.138 — k=2는 0.208, k=4는 0.239로 더 흔들린다).

⚠️ KOSIS는 값 0을 '-'로 준다. 시리즈의 None은 결측이 아니라 **진짜 0**이다
(시도 합계 ÷ 전국이 모든 연도에서 정확히 1.00). 대구 2023년 하반기 착공 0은 사실
— 미분양이 쌓여 착공이 멈춘 것이다. 건너뛰지 말고 0으로 다뤄야 한다.
"""
# ── 적정물량(분기, 호) ──────────────────────────────────────────────────────
# 적정물량 기준표(시도별 분기 입주물량)의 상수. 국토부 스케일이라는 근거:
# 합계 연 380,000호 vs 국토부 아파트 준공 실적 평균(2011~2025) 연 325,816호 = 0.86배.
# 15년 평균이 적정의 86%면 만성적 소폭 부족 — 기준표의 전제와 맞는다.
#
# ⚠️ 상수로 **고정**한다. 서울·경기·인천은 기준표에 없어(수도권 50,000 하나뿐)
# 세대수 비중 37.3/51.0/11.7%로 나눈 값이고, 세종·제주도 표에 없어 13개 지역의
# 세대당 원단위(0.00388호/세대·분기)로 추정했다. 매 갱신마다 세대수로 다시 계산하면
# 잣대가 해마다 흔들린다 — 적정물량은 기준선이지 데이터가 아니다.
REF_Q = {
    '전국': 95000, '수도권': 50000, '지방': 45000,
    '서울': 18700, '경기': 25500, '인천': 5800,          # 수도권 50,000 분할(합 정확히 50,000)
    '부산': 6000, '울산': 2000, '경남': 6000, '대구': 5000, '경북': 5000,
    '광주': 2700, '전남': 3000, '대전': 2200, '충남': 3500, '충북': 2700,
    '전북': 2500, '강원': 2600,
    '세종': 600, '제주': 1200,                            # 추정치(백 단위 반올림)
}
EST = {'서울', '경기', '인천', '세종', '제주'}            # 기준표에 없어 추정한 값 — 화면에 표시할 것
AGG = ('전국', '수도권', '지방')                          # 집계 3종(시도 순위에서 제외)
ORDER = list(REF_Q)                                       # 표의 열 순서

REGION = {z: ('수도권' if z in ('서울', '경기', '인천') else '지방') for z in REF_Q}
REGION.update({'전국': '전국', '수도권': '수도권', '지방': '지방'})

# ── 산식 상수 ───────────────────────────────────────────────────────────────
LEAD_Q = 12          # 착공 → 준공 12분기(3년). 실측 최적값.
CONV = 0.958         # 착공 대비 준공 전환율. 전국 연간 12개월 완비 연도 평균.
BACKLOG_WINDOW = 16  # 과거 재고 창 4년 (2026-08-02 사용자 결정, 앵커·상한 없음)
# ⚠️ 마지막 컷은 -0.5가 아니라 **0.0**이다(2026-08-02 변경). 향후 16분기 물가차감
# 실질 상승률이 비율 0에서 손익분기라서다(0 아래 실질 -0.3~-1.2% · 0~0.5 +0.13% ·
# 0.5~1.0 +2.58% · 1.0+ +10.22%). 옛 make_zone_pages.GRADE_CUTS 주석 참조.
GRADE_CUTS = (1.5, 1.0, 0.5, 0.0)
GRADE_KEYS = ('g4', 'g3', 'g2', 'g1', 'g0')
GRADE_LABS = {'g4': '매우 부족', 'g3': '부족', 'g2': '다소 부족',
              'g1': '균형', 'g0': '공급 여유'}


def qidx(y, q):
    """(연, 분기) → 정수 인덱스. 분기 산술을 한 축에서 하려고 쓴다."""
    return y * 4 + q - 1


def qparts(i):
    return i // 4, i % 4 + 1


def qkey(i):
    y, q = qparts(i)
    return '%dQ%d' % (y, q)


def qlabel(i, per='q'):
    """기간 표기 — 월 '17.1' / 분기 '17Q4' / 연 '2017' (2026-08-06 확정)."""
    y, q = qparts(i)
    if per == 'y':
        return str(y)
    return '%02dQ%d' % (y % 100, q)


def mlabel(y, m):
    return '%02d.%d' % (y % 100, m)


def _series(stats, key, region):
    """월별 시리즈 → {분기 인덱스: (합, 월 수)}.

    None은 0으로 센다(위 ⚠️ 참조). 월 수를 같이 돌려주는 건 마지막 분기가
    덜 찼는지 판별하기 위해서다 — 덜 찬 분기를 실적으로 쓰면 그 지역만
    공급이 낮게 잡혀 부족이 부풀려진다.
    """
    s = (stats.get(key) or {})
    ser = (s.get('series') or {}).get(region)
    if ser is None:
        return {}
    out = {}
    for dt, v in zip(s.get('dates') or [], ser):
        y, m = int(dt[:4]), int(dt[5:7])
        i = qidx(y, (m - 1) // 3 + 1)
        a, n = out.get(i, (0, 0))
        out[i] = (a + (v or 0), n + 1)
    return out


def quarterly(stats, key, region, full_only=True):
    """{분기 인덱스: 값}. full_only면 3개월이 다 찬 분기만."""
    return {i: a for i, (a, n) in _series(stats, key, region).items()
            if not full_only or n == 3}


def last_full_quarter(stats, key='준공', region='전국'):
    q = quarterly(stats, key, region)
    return max(q) if q else None


def demol_q(stats, region):
    """분기당 아파트 멸실. 원자료가 시도 연간이라 4로 나눈다.

    ⚠️ '주택멸실'(계)을 쓰면 안 된다 — 단독이 절반이라 아파트 재고에서 과대 차감된다.
    """
    ser = ((stats.get('아파트멸실') or {}).get('series') or {}).get(region)
    v = [x for x in (ser or []) if x is not None]
    return (v[-1] / 4.0) if v else 0.0


def unsold_latest(stats, region):
    """가장 최근 미분양 호수와 그 시점. (호수, 'YYYY.MM') — 없으면 (None, None).

    미분양은 **순위 산식에 넣지 않는다**(결과값이라 재고에서 차감하면 부호가
    반대고 이중계상된다 — 기존 원칙). 여기서 뽑는 건 화면에 같이 놓을 맥락이다:
    판정이 '부족'인데 미분양이 쌓인 곳은 지을 데가 없어서가 아니라 안 팔려서
    안 짓는 것일 수 있다.
    """
    s = stats.get('미분양') or {}
    ser = (s.get('series') or {}).get(region) or []
    dates = s.get('dates') or []
    for i in range(len(ser) - 1, -1, -1):
        if ser[i] is not None:
            return ser[i], (dates[i] if i < len(dates) else None)
    return None, None


def grade(ratio):
    c = GRADE_CUTS
    if ratio >= c[0]: return 'g4'
    if ratio >= c[1]: return 'g3'
    if ratio >= c[2]: return 'g2'
    if ratio >= c[3]: return 'g1'
    return 'g0'


def calc(stats):
    """20개 지역의 누적 순부족.

        I_now = Σ_{최근 16분기} (준공 − 멸실 − 적정)
        미래공급 = Σ_{k} 착공(k − 12분기) × 0.958
        누적순부족 = 적정 × H − 미래공급 − I_now

    ⚠️ 창의 기준점은 '오늘'이 아니라 **준공 실적의 마지막 완결 분기(L)** 다.
    오늘을 쓰면 아직 안 끝난 분기의 준공이 0으로 들어가 재고가 한 분기치 적정만큼
    깎인다. L을 쓰면 과거는 실적으로만, 미래는 L+1부터로 깔끔하게 갈린다.

    H는 착공 자료가 닿는 데까지 — 착공 마지막 분기 S에 대해 H = S + 12 − L.
    지금은 정확히 12분기(3년)이고, 분기가 지날 때마다 유지된다.
    """
    L = last_full_quarter(stats, '준공', '전국')
    S = last_full_quarter(stats, '착공', '전국')
    if L is None or S is None:
        raise ValueError('준공·착공 시리즈가 비어 있다')
    H = S + LEAD_Q - L
    if H <= 0:
        raise ValueError('미래 시야가 0 이하다 (착공 %s, 준공 %s)' % (qkey(S), qkey(L)))
    out, missing = [], []
    un_prd = None
    for z in ORDER:
        ref = REF_Q[z]
        dn = quarterly(stats, '준공', z)
        st = quarterly(stats, '착공', z)
        if not dn or not st:
            # ⚠️ 조용히 넘기면 그 지역이 표·페이지·sitemap에서 통째로 사라진다.
            # update_adv_data의 sido 가드가 '지역 수 감소'를 잡지만, 왜 줄었는지는
            # 여기서만 알 수 있다. 이 프로젝트에서 조용한 소거로 세 번 사고가 났다.
            missing.append(z)
            continue
        dq = demol_q(stats, z)
        inow = sum(dn.get(i, 0) - dq - ref for i in range(L - BACKLOG_WINDOW + 1, L + 1))
        fut = sum(st.get(i - LEAD_Q, 0) * CONV for i in range(L + 1, L + H + 1))
        need = ref * H
        tot = need - fut - inow
        ratio = tot / need if need else 0.0
        g = grade(ratio)
        un, un_p = unsold_latest(stats, z)
        if un_p:
            un_prd = un_p
        # 미분양이 분기 적정물량의 몇 배인가. 판정이 '부족' 쪽인데 이 값이 1을
        # 넘으면 두 신호가 어긋난 것 — 화면에 ⚠로 드러낸다.
        um = (un / float(ref)) if (un is not None and ref) else None
        out.append({
            'z': z, 'region': REGION[z], 'agg': z in AGG, 'est': z in EST,
            'ref': ref, 'inow': round(inow), 'fut': round(fut), 'need': need,
            'tot': round(tot), 'ratio': round(ratio, 4), 'grade': g,
            'unsold': (None if un is None else round(un)),
            'um': (None if um is None else round(um, 3)),
            'uwarn': bool(um is not None and um >= 1.0 and g in ('g4', 'g3', 'g2')),
        })
    if missing:
        import sys as _s
        print('⚠️ sido_zones: 준공·착공 시리즈가 없어 빠진 지역 %d곳 — %s '
              '(STATS 부분 응답 의심. 이 지역들은 표·페이지·sitemap에서 사라진다)'
              % (len(missing), ', '.join(missing)), file=_s.stderr)
    return {'L': qkey(L), 'S': qkey(S), 'H': H,
            'lead': LEAD_Q, 'conv': CONV, 'window': BACKLOG_WINDOW,
            'unsold_prd': un_prd, 'missing': missing, 'zones': out}


def zone_order(rows):
    """등급 내림차순 → 같은 등급 안에서는 순부족 큰 순. 집계 3종은 제외.

    ⚠️ 홈과 지역 페이지가 같은 순서를 써야 한다. 예전에 홈은 ratio로, 페이지는
    등급으로 정렬해 44곳 중 38곳의 순위가 어긋난 적이 있다(2026-08-03).
    """
    r = [x for x in rows if not x.get('agg')]
    return sorted(r, key=lambda x: (GRADE_KEYS.index(x['grade']), -x['tot']))


def _load_stats(path=None):
    import io, json, os
    if path is None:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'data-rest.json')
    return json.load(io.open(path, encoding='utf-8'))['STATS']


if __name__ == '__main__':
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    r = calc(_load_stats())
    print('실적 끝 %s · 착공 끝 %s · 미래 %d분기(%.1f년)'
          % (r['L'], r['S'], r['H'], r['H'] / 4.0))
    print()
    print('%-6s %11s %10s %10s %7s  %s' % ('지역', '누적순부족', '과거재고', '미래공급', '수요대비', '판정'))
    for x in [y for y in r['zones'] if y['agg']] + zone_order(r['zones']):
        print('%-6s %11s %10s %10s %7.2f  %s%s'
              % (x['z'], format(x['tot'], ','), format(x['inow'], ','), format(x['fut'], ','),
                 x['ratio'], GRADE_LABS[x['grade']], ' *추정' if x['est'] else ''))
