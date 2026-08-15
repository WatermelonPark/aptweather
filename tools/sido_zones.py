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
# 기준표에 없어 추정한 값. 지역별 배지로는 **표시하지 않는다** — "세대수 비중으로
# 나눴다" 같은 내부 방법론이라 일반 독자가 못 읽는다(2026-08-08 사용자,
# make_sido_pages.build_page 참조). 공시는 홈 '산출 방법'의 적정물량 항목이
# 문장으로 맡는다. payload의 'est'는 sido_zones의 콘솔 표(`*추정`)가 쓴다.
# ⚠️ 여기 주석은 "화면에 표시할 것"이라고 적혀 있었으나 그런 화면은 없었다 —
# 지침으로 읽고 배지를 다시 만들지 말 것(2026-08-15 리뷰).
EST = {'서울', '경기', '인천', '세종', '제주'}
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
# 창 너머 인허가 경고(pwarn)의 문턱. 1.0이 아니라 0.95인 게 핵심이다 —
# 수도권이 99.98%(실측)라 1.0으로 자르면 매달 켜졌다 꺼졌다 하고, 깜빡이는
# 경고는 읽는 사람이 그냥 무시한다. 리터럴로 흩어 두면 "정리" 커밋에 조용히
# 1.0으로 되돌아가므로 상수로 잠근다(test_pwarn_threshold_avoids_knife_edge).
PWARN_CUT = 0.95
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


def has_any(stats, key, region):
    """그 지역 시리즈에 None 아닌 값이 하나라도 있나.

    ⚠️ quarterly()가 비어 있지 않다는 것만으로는 부족하다. 전 기간이 None이어도
    _series는 (0, 3)을 만들어 분기 키가 생기므로 `if not dn` 가드를 통과하고,
    그 지역은 준공 0 = 완전 공급절벽으로 계산돼 **순위 1위로 올라온다**.
    KOSIS 지역명 개편(강원특별자치도·전북특별자치도 전례)으로 merge_basic의
    지역 필터에 걸려 그 지역만 계속 None으로 append되면 실제로 도달한다
    (2026-08-07 감사). 진짜 0(대구 2023년 하반기 착공)과는 구분해야 한다 —
    그건 값이 0이 아니라 KOSIS가 '-'로 준 것이고 여기서는 None이 아니다.
    """
    ser = ((stats.get(key) or {}).get('series') or {}).get(region)
    return any(v is not None for v in (ser or []))


def last_full_quarter(stats, key='준공', region='전국'):
    q = quarterly(stats, key, region)
    return max(q) if q else None


def demol_q(stats, region):
    """{연도: 분기당 아파트 멸실}과 폴백값. 원자료가 시도 연간이라 4로 나눈다.

    ⚠️ '주택멸실'(계)을 쓰면 안 된다 — 단독이 절반이라 아파트 재고에서 과대 차감된다.
    ⚠️ 예전엔 **최신 1개 연도**를 재고창 16분기 전체에 썼다. 창(2022Q3~2026Q2) 중
    10분기는 실측이 있는데도 버린 것이라, 광주처럼 2024년이 0이면 2022년 2,796호가
    통째로 사라지고 경남은 1.0 컷 바로 옆에서 등급이 뒤집혔다(2026-08-07 감사).
    연도가 맞으면 그 해 값을, 없으면 가장 가까운 해 값을 쓴다.
    """
    s = stats.get('아파트멸실') or {}
    ser = (s.get('series') or {}).get(region) or []
    dates = s.get('dates') or []
    by = {}
    for d, v in zip(dates, ser):
        if v is not None:
            by[int(str(d)[:4])] = v / 4.0
    return by


def demol_of(by, year):
    """그 해 멸실. 없으면 가장 가까운 연도(미래는 최신, 과거는 최초)로 채운다."""
    if not by:
        return 0.0
    if year in by:
        return by[year]
    return by[min(by, key=lambda y: (abs(y - year), y))]


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


def permit_trail12(stats, region):
    """최근 12개월 인허가 합. (호, 'YYYY.MM') — 계산 불가면 (None, None).

    인허가는 **순위 산식에 넣지 않는다**(삽을 안 뜬 계획이 섞여 착공 기반 대비
    1.29~1.68배 부푼다 — 재편 때 실측). 여기서 뽑는 건 화면에 같이 놓을
    **창 너머 신호**다: 판정은 앞으로 3년(착공이 닿는 데까지)을 보는데, 인허가는
    3~4년 뒤 입주라 판정 창 밖의 공급을 미리 보여준다. 등급은 '다소 부족'인데
    시장에서는 '역대급 부족'이라 말하는 온도차가 정확히 이 창 차이였다(2026-08-11
    사용자 — 등급은 실측 앵커라 두고, 부족한 시야를 이 줄이 나른다).

    ⚠️ 인허가 계열은 '호 (연내 누계)' — 1월마다 리셋된다. 최근 12개월 =
    올해 최신 누계 + (작년 12월 누계 − 작년 같은 달 누계). 이 셋 중 하나라도
    없으면 None을 돌려주고 배지를 접는다(반쪽 계산으로 오탐을 내지 않는다).
    """
    s = stats.get('인허가') or {}
    ser = (s.get('series') or {}).get(region) or []
    dates = s.get('dates') or []
    last = None
    for i in range(len(ser) - 1, -1, -1):
        if ser[i] is not None:
            last = i
            break
    if last is None:
        return None, None
    ym = dates[last]
    y, m = ym.split('.')
    py = str(int(y) - 1)
    idx = {d: j for j, d in enumerate(dates)}
    pieces = [ser[last]]
    for key in (py + '.12', py + '.' + m):
        j = idx.get(key)
        v = ser[j] if (j is not None and j < len(ser)) else None
        if v is None:
            return None, None
        pieces.append(v)
    return pieces[0] + pieces[1] - pieces[2], ym


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
    # ⚠️ H는 데이터 가용성에서 유도된다. 착공표(DT_MLTM_5387)가 준공표보다 한 달만
    # 늦게 들어와도 S가 한 분기 밀려 H=11이 되고, 재고창은 16분기 고정이라 더 작은
    # need로 나뉘어 **실공급 변화 0인데 전 지역 ratio가 통째로 올라간다**
    # (2026-08-07 감사). H가 정상값(LEAD_Q)과 다르면 드러낸다.
    if H != LEAD_Q:
        import sys as _s
        print('⚠️ sido_zones: 미래 시야가 %d분기다(정상 %d) — 착공 %s vs 준공 %s. '
              '재고창은 16분기 고정이라 need만 줄어 전 지역 비율이 함께 움직인다.'
              % (H, LEAD_Q, qkey(S), qkey(L)), file=_s.stderr)
    if H <= 0:
        raise ValueError('미래 시야가 0 이하다 (착공 %s, 준공 %s)' % (qkey(S), qkey(L)))
    out, missing = [], []
    un_prd = None
    for z in ORDER:
        ref = REF_Q[z]
        dn = quarterly(stats, '준공', z)
        st = quarterly(stats, '착공', z)
        if not dn or not st or not has_any(stats, '준공', z) or not has_any(stats, '착공', z):
            # ⚠️ 조용히 넘기면 그 지역이 표·페이지·sitemap에서 통째로 사라진다.
            # update_adv_data의 sido 가드가 '지역 수 감소'를 잡지만, 왜 줄었는지는
            # 여기서만 알 수 있다. 이 프로젝트에서 조용한 소거로 세 번 사고가 났다.
            missing.append(z)
            continue
        dby = demol_q(stats, z)
        inow = sum(dn.get(i, 0) - demol_of(dby, qparts(i)[0]) - ref
                   for i in range(L - BACKLOG_WINDOW + 1, L + 1))
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
        #
        # ⚠️ 등급을 이 값으로 깎지 않는다(2026-08-15 마케팅 요청 #3 검토 결론).
        # "제주는 부족 1위인데 미분양도 1위 아니냐"는 물음은 타당하지만, 감쇠가
        # 판정을 낫게 하는지는 별개다. 17시도 × 20년 월별 패널(n≈3,600)로 쟀다:
        #   미분양(지역 평균 대비) vs 이전 12개월 가격변동  r = -0.31
        #   미분양               vs 이전 24개월 가격변동  r = -0.32
        #   미분양               vs 이후 12개월 가격변동  r = -0.07
        #   미분양               vs 이후 24개월 가격변동  r = +0.07
        # 미분양은 **이미 벌어진 하락의 흉터**지 앞으로의 신호가 아니다. 뒤를 보는
        # 상관은 뚜렷한데 앞을 보는 상관은 0이고, 24개월에선 부호가 뒤집힌다.
        # 3년 앞 공급을 재는 등급에 이걸 섞으면 지나간 가격을 미래 판정에 넣는 것이다.
        # (현 시점 단면만 보면 r=-0.42까지 나오는데, 그게 바로 이 후행성의 그림자다 —
        #  '예측력'으로 오독하기 쉬운 자리라 수치를 남긴다.)
        # 대신 어긋남은 uwarn으로 드러낸다 — 숨기지 않되 순위는 건드리지 않는다.
        um = (un / float(ref)) if (un is not None and ref) else None
        # 창 너머 신호: 최근 12개월 인허가 ÷ 적정연간. 인허가는 부풀려지는 지표라
        # (착공 기반 대비 1.29~1.68배) 그런데도 적정에 못 미치면 3년 창이 끝난
        # 뒤의 공급은 확실히 얇다 — 보수적 기준이라 오탐이 없다. 문턱은 0.95:
        # 100% 언저리(수도권 99.98% 실측)가 매달 켜졌다 꺼졌다 하면 경고가 무시된다.
        pm, _ = permit_trail12(stats, z)
        pmr = (pm / float(ref * 4)) if (pm is not None and ref) else None
        out.append({
            'z': z, 'region': REGION[z], 'agg': z in AGG, 'est': z in EST,
            'ref': ref, 'inow': round(inow), 'fut': round(fut), 'need': need,
            'tot': round(tot), 'ratio': round(ratio, 4), 'grade': g,
            'unsold': (None if un is None else round(un)),
            'um': (None if um is None else round(um, 3)),
            'uwarn': bool(um is not None and um >= 1.0 and g in ('g4', 'g3', 'g2')),
            'pm12': (None if pm is None else round(pm)),
            'pmr': (None if pmr is None else round(pmr, 3)),
            'pwarn': bool(pmr is not None and pmr < PWARN_CUT),
        })
    # ── 집계 항등식 자가검사 ────────────────────────────────────────────────
    # 부분 결측은 missing 가드에 안 걸린다. 한 지역의 특정 월만 None이면 그 지역만
    # 공급이 낮게 잡히는데 지역 수는 그대로라 아무도 모른다. 전국은 별도 시리즈라
    # 영향을 안 받으므로, Σ시도와 전국을 대조하면 그 어긋남이 드러난다
    # (2026-08-07 감사에서 경기 3개월 None으로 11,698호 차이를 실측).
    warn = []
    byz = {x['z']: x for x in out}

    def _cmp(label, ssum, nat, k):
        if nat and abs(ssum - nat) > max(50, abs(nat) * 0.001):
            warn.append('%s %s: 합 %s vs %s (차 %s)'
                        % (label, k, format(int(ssum), ','), format(int(nat), ','),
                           format(int(ssum - nat), ',')))
    if '전국' in byz:
        for k in ('inow', 'fut', 'tot'):
            _cmp('전국', sum(byz[z][k] for z in ORDER if z not in AGG and z in byz),
                 byz['전국'][k], k)
    # ⚠️ 집계행 자체(수도권·지방)도 대조해야 한다. Σ는 시도만 도니까 '수도권' 열의
    # 착공이 통째로 빠져도 위 검사는 통과한다 — 실측으로 fut가 143,419호 어긋나고
    # tot가 41% 틀린 채 무경고 배포됐다(2026-08-07 감사).
    CAP = ('서울', '경기', '인천')
    if '수도권' in byz and all(z in byz for z in CAP):
        for k in ('inow', 'fut', 'tot'):
            _cmp('수도권', sum(byz[z][k] for z in CAP), byz['수도권'][k], k)
    if '지방' in byz and '전국' in byz and '수도권' in byz:
        for k in ('inow', 'fut', 'tot'):
            _cmp('지방', byz['전국'][k] - byz['수도권'][k], byz['지방'][k], k)
    if warn:
        import sys as _s
        _msg = ('sido_zones: 집계 항등식이 깨졌다 — 어느 지역의 시리즈에 부분 결측이 '
                '있을 수 있다(전국은 별도 시리즈라 영향을 안 받는다).')
        print('⚠️ ' + _msg + chr(10) + '  ' + (chr(10) + '  ').join(warn),
              file=_s.stderr)
    if missing:
        import sys as _s
        print('⚠️ sido_zones: 준공·착공 시리즈가 없어 빠진 지역 %d곳 — %s '
              '(STATS 부분 응답 의심. 이 지역들은 표·페이지·sitemap에서 사라진다)'
              % (len(missing), ', '.join(missing)), file=_s.stderr)
    return {'L': qkey(L), 'S': qkey(S), 'H': H,
            'lead': LEAD_Q, 'conv': CONV, 'window': BACKLOG_WINDOW,
            'unsold_prd': un_prd, 'missing': missing, 'agg_warn': warn, 'zones': out}


def supply_rows(stats):
    """통계 탭 '입주물량'과 /moveins/가 쓸 분기 시계열 — **홈 표와 같은 소스**.

    ⚠️ 2026-08-07까지 이 자리는 odcloud 입주예정(ADV.occupancy)이었다. 그래서
    같은 서울 2027Q2를 홈은 2,107세대, 통계 탭은 1,073세대로 보여줬고(2배),
    기준선도 적정물량(REF_Q)·적정밴드(band)·ref 셋이 공존해 제주가 동시에
    '매우 부족'이자 '밴드 상단 초과'였다(2026-08-07 감사). 소스를 하나로 합친다.

    과거는 준공 실적, 미래는 착공을 LEAD_Q분기 뒤로 밀어 ×CONV. e=1이 미래 표시.
    """
    L = last_full_quarter(stats, '준공', '전국')
    S = last_full_quarter(stats, '착공', '전국')
    if L is None or S is None:
        return None
    regs = [z for z in ORDER]
    dn = {z: quarterly(stats, '준공', z) for z in regs}
    st = {z: quarterly(stats, '착공', z) for z in regs}
    start = qidx(2017, 1)
    rows = []
    for i in range(start, S + LEAD_Q + 1):
        fut = i > L
        v = []
        for z in regs:
            if fut:
                # ⚠️ 분기마다 반올림하면 소비자가 그걸 다시 더해 홈과 갈린다 —
                # '2026년 전국 입주물량'이 /moveins/ 215,875 · 통계 탭 215,876 ·
                # 홈 215,877로 셋이 달랐다(2026-08-08 감사). 표시 직전에 한 번만
                # 반올림하도록 소수 한 자리로 넘긴다(페이로드 영향은 무시할 수준).
                # ⚠️ 자리수를 줄이면 x.5로 굳어 **이중 반올림**이 된다 —
                # 1자리로 뒀더니 36529.498 → 36529.5 → 화면 36,530으로 홈(36,529)과
                # 갈렸다(2026-08-08 감사, 1,000칸 중 11칸). 3자리면 그 경계가 안 생긴다.
                v.append(round(st[z].get(i - LEAD_Q, 0) * CONV, 3))
            else:
                v.append(dn[z].get(i, 0))
        r = {'p': qkey(i), 'v': v}
        if fut:
            r['e'] = 1
        rows.append(r)
    return {'regions': regs, 'rows': rows, 'ref': dict(REF_Q),
            'note': ('분기별 아파트 공급 — 과거는 국토교통부 준공 실적, '
                     '%s 이후는 착공 실적을 %d년 뒤로 밀어 추정(전환율 %.3f). '
                     '기준선은 분기 적정물량이며 홈 공급표와 같은 값이다.'
                     % (qkey(L + 1), LEAD_Q // 4, CONV))}


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
