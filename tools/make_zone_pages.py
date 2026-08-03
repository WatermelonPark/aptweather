# -*- coding: utf-8 -*-
"""생활권별 공급 리포트 페이지 생성 — /zone/<생활권>/index.html

data.js의 ADV(livezone·occupancy·permits·bubble)와 STATS(전세가율·주택멸실)를 읽어
아공맵 점수 산출 근거를 서술형으로 풀어쓴 정적 페이지를 생활권 수만큼 만든다.
홈의 요약 카드가 "무슨 말인지 모르겠다"는 문제를 풀고, 검색 유입(SEO) 창구가 된다.

사용:  python tools/make_zone_pages.py         # 생성 + sitemap 갱신
"""
import io, os, re, json, sys, datetime
import html as html_mod
from urllib.parse import quote

# 같은 폴더의 update_adv_data(존 정의 단일 소스)를 임포트하기 위한 경로 — 모듈 로드
# 시 1회만. 예전엔 _lz_members가 호출마다 insert해 존 44곳 렌더에 44번 쌓였다.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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
    """미래 공급 가중: 액면 그대로(1.0). k=미래 몇 분기 뒤(1..).

    ⚠️ 2026-08-02 감쇠 폐지. 되살리려면 아래를 먼저 반박할 것 —
    tools/tests/test_make_zone_pages.py::test_conf_is_flat이 이 값을 잠그고 있다.

    옛 값은 1.0 - (k-1)/20 (16분기 뒤 0.25, 16분기 평균 0.625)이었다. 근거가
    코드·커밋 어디에도 없었고(DEFICIT_CAP과 달리 검증 도구도 문서도 없음),
    다음 세 가지가 확인되면서 폐지했다.

    ① 비대칭: 수요는 16분기 전부 100%(Σrefq)인데 공급만 평균 62.5%로 깎여
       순부족이 구조적으로 부풀었다. 전국 미래 예정 1,375,145 → 901,085세대.
       빼고 재보니 44존 중 등급 12곳·순위 27곳이 바뀌었다(부산·대전세종은 부호 반전).
    ② 실측: HUB 원시 레코드의 useInsptSchedDay(예정) vs useInsptDay(실제)를
       쌍으로 잰 결과(춘천·평택·강남 등, n=215) 중앙값 지연 0개월·평균 +1.4개월,
       86%가 ±2개월 안. 허가·착공을 통과한 물량은 **지연될 뿐 사라지지 않는다** —
       감쇠(물량 소거)가 아니라 시점 이동이 맞는 모델이다.
    ③ 장기 구간은 방향까지 반대: 미래 파이프라인은 +14분기까지 두께가 거의
       평평하고 +15~16에서만 꺾인다. 그 꺾임은 '아직 등록 안 된 물량'이라
       이미 과소계상인데, 옛 conf는 바로 거기를 0.30·0.25로 또 깎았다.

    한계도 같이 남긴다: 준공 건의 43%는 예정일 자체가 없어 표본에서 빠졌고,
    hub_permits.json 스냅샷이 1주치뿐이라 DEFICIT_CAP처럼 예측력 백테스트를
    돌리지 못했다. 1년쯤 쌓이면 실현율을 직접 재서 곡선으로 대체할 수 있다.
    그때도 '감쇠'가 아니라 '시점 이동'이 먼저 검토돼야 한다.
    """
    return 1.0


ANCHOR = 2010 * 4  # 2010Q1
FUT_HORIZON = 16  # 4년(기준표 3년룰 + 준공예정 실측 ~4년). conf 폐지(2026-08-02) 후
                  # 먼 미래에 대한 유보는 오직 이 지평선으로만 표현한다 — "4년을 보되
                  # 마지막 해는 4분의 1만 센다"보다 "몇 년까지 보는가" 하나가 정직하다.
BACKLOG_WINDOW = 16  # 과거 재고를 몇 분기 거슬러 볼지(4년). 옛 DEFICIT_CAP(누적 상한)을
                     # 대체한다 — 창이 곧 상한이라 별도 클램프가 필요 없다.

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

# ── 서울 확산 관계 (2026-08-03 실측) ─────────────────────────────────────────
# 사용자 가설("인천도 서울과 동조하는데 시차가 1년 반쯤 난다")을 검증한 결과다.
# 방법: 분기 잔차 수익률(전국 평균 제거)의 서울 대비 시차별 상관 + 존 라벨
# 순열검정 400회. 유의수준 10%에서 살아남은 곳만 싣는다.
#   동행 — L=0에서 유의하고 L=6보다 큼: 성남 +0.72(p.02) 광명 +0.51(p.04) 용인 +0.44(p.08)
#   확산 — L=6에서 유의하고 L=0보다 큼: 남양주 +0.48(p.03) 인천 +0.47(p.04) 부천 +0.41(p.10)
# 나머지 15곳은 어느 시차에서도 유의하지 않아 아무 말도 하지 않는다.
#
# ⚠️ 시차 '길이'는 공시하지 않는다. 최적 L이 창마다 흔들리고(인천 6/1/2/6),
# 전반 중앙값 0 → 후반 7로 계통적으로 늘어난다(21곳 중 16곳). 즉 확산은 실재하되
# 속도가 변한다 — "18개월" 같은 상수를 화면에 쓰면 곧 틀린 말이 된다.
# 대조군: 서울 자기상관 L=6은 +0.24로, 확산권의 +0.41~0.48은 단순 관성 이상이다.
# 재현: 이 파일 상단 주석의 절차를 zone_ref_fit2.Fitter로 그대로 돌리면 된다.
SEOUL_SYNC = {
    '성남권': 'co', '광명권': 'co', '용인권': 'co',
    '남양주권': 'lag', '인천권': 'lag', '부천권': 'lag',
}

# 등급 컷 — 순부족 ÷ 4년 필요량. 2026-08-02에 마지막 컷을 -0.5 → 0으로 옮겼다.
#
# 근거(실측): 금리 잔잔 구간의 존-분기 표본을 부족비율로 묶고 향후 16분기
# **물가 차감 실질** 상승률을 봤다(ECOS 901Y009 총지수). 명목으로는 전 구간이
# +5~17%로 다 오르지만, 물가를 빼면 갈린다:
#     비율 <0      → 실질 -0.3 ~ -1.2%   (n=182)
#     0 ~ 0.5      → 실질 +0.13%         (n=417)
#     0.5 ~ 1.0    → 실질 +2.58%         (n=501)
#     1.0 이상     → 실질 +10.22%        (n=29)
# 즉 실질 손익분기가 0이다. 옛 -0.5 컷은 실질 하락 구간(-0.60%)까지 '균형'으로
# 불렀다. 0/0.5/1.0이 데이터가 지지하는 경계고, 더 촘촘한 컷(0.8/0.3)은 표본이
# 지지하지 않아 채택하지 않았다.
#
# ⚠️ 한계: 검증에 쓴 과거 부족비율은 **재고 성분만**으로 계산했다. 라이브 tot에는
# 미래 준공예정(sched)이 들어가는데 과거 시점의 sched 빈티지가 없다. 컷을 검증한
# 지표와 화면 지표가 완전히 같지는 않다.
GRADE_CUTS = (1.5, 1.0, 0.5, 0.0)
GRADE_ORDER = ('g4', 'g3', 'g2', 'g1', 'g0')


def zone_order(rows):
    """화면에 나열하는 표준 순서 — 등급(비율) 그룹 → 그룹 안은 절대 세대수 큰 순.

    홈(index.html renderScoreSec)·/zone/ 허브·존 페이지의 "N위"가 **모두 이 하나의
    순서**를 쓴다. 2026-08-01 사용자 지적: 같은 지표인데 화면마다 그룹핑·정렬이 달라
    혼란스럽다 — 리스트 범위(홈 23행=수도권 통합 / 허브 44곳=개별)는 역할에 따라
    달라도, 묶는 기준과 줄 세우는 기준은 같아야 한다.
    ⚠️ index.html renderScoreSec의 GORDER + `b.tot-a.tot` 정렬과 반드시 동치.
    """
    return sorted(rows, key=lambda x: (GRADE_ORDER.index(x['gr']['k']), -x['tot']))
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


def running_shortage(done, sched, demol, refq, cur_q, horizon=FUT_HORIZON,
                     weight_demand=True, full=False):
    # 기본 horizon은 FUT_HORIZON(16)이다. 예전 기본값은 20이었는데, 그때는 conf가
    # k=21에서 0이 돼 루프가 알아서 끊겼기 때문에 티가 안 났다. conf 폐지(2026-08-02)로
    # 그 브레이크가 사라져 기본값이 그대로 드러난다 — 20이면 수요를 4분기치 더 세서
    # 순부족이 부풀었다. 라이브(calc)는 원래 horizon=16을 명시로 넘기고 JS 미러도
    # ||16이라 영향은 없었지만, 기본값이 둘이면 언젠가 갈린다.
    """준공 기반 러닝재고 순부족.

    I_now = 최근 BACKLOG_WINDOW분기(4년) 동안의 (준공 - 멸실 - refq) 단순 합.
    0에서 시작하므로 '과거 4년'이 문자 그대로 참이다.
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

    ⚠️ conf 폐지(2026-08-02, _conf 참조) 이후 두 안은 **수치가 같다** — conf≡1.0이면
    Σconf*(refq-s) == Σrefq - Σconf*s. 분기를 남겨둔 건 conf를 되살릴 경우를 위한
    골격일 뿐이니, "A안/B안 중 뭘 쓰지" 같은 판단은 지금 필요 없다(라이브는 B안).
    """
    # M1: full(분해값 반환)은 항등식 tot == demand - supplyw - inow 성립을 전제로
    # 문서화돼 있는데, 그 항등식은 weight_demand=False(B안)에서만 성립한다(A안은
    # fut가 이미 conf 가중 결합이라 demand_sum/supply_weighted로 쪼갤 수 없다).
    # 두 플래그가 동시에 True인 호출은 분해값이 조용히 틀린 채 나가므로 여기서 막는다.
    if full and weight_demand:
        # -O에서도 살아있어야 하는 계약이라 assert가 아니라 예외로 던진다(리뷰 M4).
        raise ValueError('분해값(full=True)은 B안(weight_demand=False)에서만 유효하다')
    # 과거 재고 = **최근 BACKLOG_WINDOW분기(4년)만** 0에서 시작해 누적. 상한도 앵커도
    # 없다. 2026-08-02 사용자 결정.
    #
    # 이력: 2010Q1 앵커 + 아래로만 하한(-CAP) → 대칭 상한(±CAP) → 4년 창.
    # 앵커 방식은 상한이 값만 묶고 기억은 안 지워서, 최근 4년이 똑같은 두 지역도
    # 옛 이력에 따라 오늘 값이 달랐다(시작점을 4년 전으로 옮기면 등급 27/44곳 변동).
    # 그래서 '과거 4년'이라는 화면 문구가 사실과 달랐다.
    #
    # 창으로 바꾼 게 단순하기만 한 게 아니라 **예측력도 낫다**(금리 잔잔 29분기,
    # 존 라벨 순열검정 p<0.01): 향후 8분기 +0.144 → +0.167, 16분기 +0.236 → +0.280.
    # 8년 창(8Q +0.190/16Q +0.278)과도 대등해 굳이 긴 기억을 살 이유가 없다.
    # 재현: tools/zone_floor_cap.py의 objective를 창 변형으로 돌린 값.
    #
    # 창이 상한을 대신한다 — 16분기 창은 정의상 -16*refq보다 더 부족해질 수 없어
    # 옛 DEFICIT_CAP이 하던 일을 구조가 한다(파라미터 하나 감소).
    I = 0.0
    for idx in range(cur_q - BACKLOG_WINDOW + 1, cur_q + 1):
        qk = _qkey(idx)
        I += done.get(qk, 0) - demol.get(qk, 0) - refq
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
    # 아파트멸실(KOSIS DT_MLTM_5416 itm=아파트, 시도 연간) — 러닝재고의 멸실 항.
    # HUB 철거멸실관리대장은 2020년에서 끊겨(전 기간 누적 189,939 < KOSIS 2024
    # 한 해 85,069) 4년 창(2022Q4~) 안이 전부 0이었다 — 재건축으로 사라진 집이
    # 재고에 그대로 남아 부족이 과소평가됐다(2026-08-03 배선). '주택멸실'(계)을
    # 쓰면 안 된다: 단독이 절반이라 아파트 재고에서 과대 차감된다.
    ADM = sts.get('아파트멸실') or {}
    ADM_DATES = ADM.get('dates') or []
    ADM_SER = ADM.get('series') or {}
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
        # 멸실: 시도 연간 아파트멸실 × 세대 비중(share) ÷ 4분기 균등. 창의 마지막
        # 두 해(2025~26)는 아직 미발표라 최근 3개년 평균을 이월한다(사용자 결정).
        # ⚠️ share는 시도 안분 비중(풀 재배선 전 값) — 멸실은 행정 통계라 시도
        # 잣대가 맞다. running_shortage 계약대로 zone-level 절대값을 만들어 넘긴다.
        # ⚠️ index.html scCalc()와 반드시 동치(이중구현 미러 — check_dual_calc 대조).
        # 계열이 없으면(구버전 data.js) 옛 HUB demol로 폴백 — 사실상 창 안 0이다.
        zdemol = {}
        _adv_ = ADM_SER.get(ps)
        if _adv_ and ADM_DATES:
            _ym = {ADM_DATES[i]: _adv_[i] for i in range(len(ADM_DATES))
                   if i < len(_adv_) and _adv_[i] is not None}
            _tail = [v for _, v in sorted(_ym.items())][-3:]
            _avg3 = (sum(_tail) / len(_tail)) if _tail else 0.0
            for _k in range(BACKLOG_WINDOW):
                _qi = cur_q - _k
                _ann = _ym.get(str(_qi // 4), _avg3)
                zdemol[_qkey(_qi)] = _ann * share / 4.0
        else:
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
        # 재고 궤적 5칸(지금·1~4년 뒤). 존 페이지와 홈이 같은 값을 써야 하는데,
        # zsched 전량(존당 151분기)을 홈 페이로드에 실을 수 없어 여기서 접는다.
        # ⚠️ index.html scCalc()의 seq와 반드시 동치(check_dual_calc 대조 대상).
        seq = [(_rs['inow'] if _rs else 0)]
        if _rs:
            _i = _rs['inow']
            for k in range(1, 17):
                _i += zsched.get(_qkey(cur_q + k), 0) - zrefq
                if k % 4 == 0:
                    seq.append(_i)
        else:
            seq += [0] * 4
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
                        zsched=zsched, seq=seq,
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
    # ⚠️ zrefq(분기 적정물량)를 빠뜨리면 롤업이 첫 구성원(서울권) 값을 그대로
    # 물려받는다 — 수도권 기준선이 17,627(서울권 몫)로 찍혀 22곳 합계 막대들이
    # 죄다 그 위로 솟았다(2026-08-02 사용자 지적). need4 = zrefq×16 관계가
    # 롤업에서만 깨져 있었다. 합산 대상에 반드시 포함할 것.
    for k in ('need', 'dA', 'dB', 'dC', 'tot', 'fsup', 'need4', 'inow', 'fsupw', 'zrefq'):
        agg[k] = sum(c[k] for c in caps)
    # 궤적도 시점별로 합산한다 — 빠뜨리면 롤업이 첫 구성원(서울권) 궤적을 물려받는다
    # (zrefq를 빠뜨렸을 때와 같은 종류의 버그, 2026-08-02 6b6b5fc 참조).
    agg['seq'] = [sum(c['seq'][i] for c in caps) for i in range(5)]
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


def signed_u(v):
    """signed()에 단위까지 — 숫자만 있으면 무엇의 개수인지 안 읽힌다(2026-08-01)."""
    return signed(v) + '세대'


UNIT_WINDOW = 48   # 단지 목록 창(개월): 앞으로 4년 · 지난 4년. 상위 N개 캡 대신
                   # 시간 창으로 자른다(옛 top-20은 2005년 준공 대단지가 밀고 들어왔다).


def render_units_2sec(units, today=None):
    """permits.units[zone](또는 수도권처럼 소속 존 합산) → 2섹션 HTML.

    "앞으로 들어올 단지"(sched)와 "최근 들어온 단지"(done) 2섹션.

    머리말 합계는 '총 N세대'다(2026-08-02 사용자 문구 확정). 이게 참이려면 units가
    전량이어야 하는데, 같은 날 UNITS_CAP을 폐지해 그렇게 됐다 — units 세대 합 ==
    done_q+sched_q 합이 정의상 성립한다(test_aggregate_keeps_every_unit_sorted_by_household).
    ⚠️ 캡을 되살리면 이 문구가 즉시 거짓이 된다. 바로 위 '언제 들어오나' 차트의
    총량과 나란히 놓여 있어 어긋나면 버그로 읽힌다(2026-08-01 대구권 55,693 vs 15,020).

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
    esc = lambda s: (html_mod.unescape(str(s)).replace('&', '&amp;').replace('<', '&lt;')
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
    # D2블록 ×2). 예전엔 (이름, 세대, 연월)이 같으면 한 건을 **버렸는데**, 그러면
    # 목록 합계가 차트(sched_q 전량 합산)와 어긋난다 — 대구권에서 18건 12,441세대가
    # 증발했다(2026-08-03). 두 줄로 보여도 신뢰가 깎이고 합계가 안 맞아도 깎인다는
    # 사용자 판단에 따라, 버리지 않고 **합쳐서 한 줄**로 만든다: 세대수는 합산하고
    # ×N 표기를 남긴다. 진짜 이중등록이든 별개 블록이든 모델(sched_q)은 이미 둘 다
    # 세고 있으므로, 목록도 둘 다 세는 것이 모델·차트와 유일하게 일관된 선택이다.
    def _fold(us):
        seen, out = {}, []
        for u in us:
            k = (u[0], u[1], u[2] if len(u) > 2 else None)
            if k in seen:
                f = seen[k]
                f[1] += u[1]        # 세대 합산
                f[3] += 1           # 접힌 건수
                continue
            f = [u[0], u[1], u[2] if len(u) > 2 else None, 1]
            seen[k] = f
            out.append(f)
        return out
    sched, done = _fold(sched), _fold(done)
    if not sched and not done:
        return ''

    def _row(u, suffix_fmt, none_label):
        name, hh, ym = u[0], u[1], u[2]
        n = u[3] if len(u) > 3 else 1
        label = (suffix_fmt % ym.replace('-', '.')) if ym else none_label
        # 접힌 건은 ×N을 붙이고 세대수는 합산값이다 — title에 이유를 남겨 "같은
        # 단지가 왜 한 줄에 세대수가 두 배냐"는 오독을 막는다.
        fold = (' <i class="ux" title="같은 이름·시기로 %d건 등록(동·블록 분리 등) — 세대수는 합계">×%d</i>'
                % (n, n)) if n > 1 else ''
        return ('<tr><td class="uname" title="%s">%s%s</td><td class="num">%s</td>'
                '<td class="num">%s</td></tr>' % (esc(name), esc(name), fold, num(hh), label))

    def sched_row(u):
        return _row(u, '%s 예정', '미정')

    def done_row(u):
        return _row(u, '%s 준공', '준공일 미상')

    # 머리말 '총 N세대'는 접기(_fold)가 합산 방식이라 차트 총량과 정의상 같다 —
    # UNITS_CAP 폐지(전량 수집) + 버리지 않는 접기, 두 조건이 모두 필요하다.
    # 어느 하나라도 되돌리면 두 숫자가 어긋난 채 나란히 놓인다.
    hh_sum = lambda us: sum((u[1] or 0) for u in us)
    parts = []
    if sched:
        rows = ''.join(sched_row(u) for u in sched)
        parts.append(
            '<section><div class="wrap">\n'
            '  <h2>앞으로 들어올 단지 <span class="ucnt">향후 4년 · %d개 단지 · 총 %s세대</span></h2>\n'
            '  <div class="ulist"><table class="utable2">\n'
            '    <thead><tr><th>단지명</th><th>세대수</th><th>준공예정</th></tr></thead>\n'
            '    <tbody>%s</tbody>\n'
            '  </table></div>\n'
            '</div></section>\n' % (len(sched), num(hh_sum(sched)), rows))
    if done:
        rows = ''.join(done_row(u) for u in done)
        parts.append(
            '<section><div class="wrap">\n'
            '  <h2>최근 들어온 단지 <span class="ucnt">지난 4년 · %d개 단지 · 총 %s세대</span></h2>\n'
            '  <div class="ulist"><table class="utable2">\n'
            '    <thead><tr><th>단지명</th><th>세대수</th><th>준공</th></tr></thead>\n'
            '    <tbody>%s</tbody>\n'
            '  </table></div>\n'
            '</div></section>\n' % (len(done), num(hh_sum(done)), rows))
    return ''.join(parts)


CSS = """b,strong{font-weight:600}
  tr.rollup td{border-top:1.5px solid var(--ink);color:var(--muted)}
  tr.rollup .sub{font-size:11.5px;color:var(--muted)}
  .num .pct{display:block;font-size:10.5px;font-weight:500;font-style:normal;color:var(--muted);line-height:1.35;margin-top:1px}
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
button.cta{width:100%;max-width:400px;border:0;cursor:pointer;font-family:inherit;
 display:flex;align-items:center;justify-content:center;gap:8px}
button.cta.sub{border:1.5px solid var(--ink)}
.zshare{padding:4px 0 28px}
.zshare .zs-lead{font-size:13.5px;color:var(--muted);text-align:center;margin-bottom:10px}
.zlist{display:flex;flex-wrap:wrap;gap:7px;margin-top:6px}
.zlist a{font-size:12.5px;font-weight:600;text-decoration:none;color:var(--ink2);background:#fff;
 border:1px solid var(--line);border-radius:3px;padding:5px 9px}
.note{font-size:13.5px;color:var(--muted);line-height:1.75}
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
 /* ⚠️ 위 스택 규칙은 열 많은 비교표를 위한 것이다. 단지 목록(.utable2)은 3열뿐이라
    좁은 화면에서도 표로 읽히는데, 함께 스택되는 바람에 단지 하나가 3줄이 돼 목록이
    세 배로 길어졌다(2026-08-01 모바일 지적 — PC는 1줄). 여기서만 표로 되돌린다. */
 .utable2{display:table}
 .utable2 thead{display:table-header-group}
 .utable2 tbody{display:table-row-group}
 .utable2 tr{display:table-row;border-bottom:0;padding:0}
 .utable2 td{display:table-cell;padding:8px 9px;border-bottom:1px solid var(--line);
  text-align:right;font-size:13px}
 .utable2 tbody tr:last-child td{border-bottom:0}
 .utable2 td:nth-child(1){text-align:left;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .utable2 th:nth-child(1){width:50%}
 .utable2 th:nth-child(2){width:22%}
 .utable2 th:nth-child(3){width:28%}
}
.qwrap{background:#fff;border:1px solid var(--line);border-top:0;padding:12px 14px 10px}
.qtitle{font-size:12px;color:var(--muted);margin-bottom:8px}
/* 막대 안 숫자·분기 라벨이 nowrap이라 칸이 줄지 못한다 — 16분기가 들어오면 폭이
   화면을 넘어 페이지 전체가 가로로 늘어났다(2026-08-01 모바일 지적). 칸 최소폭을
   주고 넘치면 이 상자 안에서만 가로로 스크롤시킨다. */
.qchart{overflow-x:auto;overflow-y:hidden;-webkit-overflow-scrolling:touch;scrollbar-width:thin}
/* 기준선을 얹으려면 막대들과 같은 좌표계가 필요하다 — 가로 스크롤 폭 전체를 덮도록
   안쪽 래퍼를 두고 여기에 절대배치한다. */
/* 왼쪽 눈금 자리 — 기준선 라벨이 막대를 가리지 않게 띄워 둔다(실측: 흰 배경
   라벨이 막대 3개를 덮었다). 실제 차트의 y축 라벨 영역과 같은 역할. */
.q-inner{position:relative;display:flex;align-items:flex-end;gap:2px;min-width:100%;
 padding-top:2px;padding-left:46px;border-bottom:1px solid var(--line)}
/* 16분기를 한 화면에 — flex-basis 0으로 균등 분할하고 최소폭을 두지 않는다.
   스크롤시켜 놓으면 '빈 분기가 많다'는 이 그래프의 요점이 화면 밖으로 밀린다. */
.q-col{flex:1 1 0;min-width:0;display:flex;flex-direction:column;justify-content:flex-end;
 align-items:center;gap:2px;background:none;border:0;padding:0;font:inherit;cursor:pointer}
.q-col:focus-visible{outline:2px solid var(--ink);outline-offset:1px}
.q-col.on .q-bar{outline:1.5px solid var(--ink);outline-offset:1px}
/* 누른 분기의 값 — 차트 위 한 줄에 띄운다(막대마다 숫자를 박으면 16칸에 안 들어간다) */
.seq{margin:0 0 14px}
.seq-msg{font-size:14px;font-weight:600;color:var(--ink);margin-bottom:7px}
.seq-row{display:flex;gap:6px;max-width:320px}
.seq-c{flex:1 1 0;text-align:center}
.seq-c i{display:block;height:7px;border-radius:2px;background:#cfd8d4}
.seq-c.on i{background:#c0392b}
.seq-c span{display:block;font-size:11px;color:var(--muted);margin-top:4px}
.seq-c.on span{color:var(--ink2);font-weight:600}
.qwrap{position:relative}
.q-tip{position:absolute;pointer-events:none;background:var(--ink);color:#fff;padding:7px 10px;
 border-radius:3px;font-size:12px;line-height:1.5;white-space:nowrap;z-index:3;transform:translate(-50%,-100%)}
.q-tip b{font-weight:700}
.q-tip span{color:#c4cec9;font-weight:400}
/* 회색 막대는 '들어올 공급'이라는 뜻을 못 나른다. 사이트 컨벤션대로 공급=파랑.
   폭은 22px 칸에 16px — 예전 36px는 너무 뚱뚱해 한눈에 안 들어왔다(2026-08-02). */
.q-bar{width:100%;max-width:13px;background:#3a7bd5}
/* ⚠️ block+고정높이 필수. inline <span>이면 라벨을 솎아 빈 칸이 된 열은 높이가 0이라
   그 열의 막대만 14px 아래로 내려앉고, 막대들이 공통 바닥선을 잃는다 — 기준선과의
   위아래 비교가 통째로 틀어진다(2026-08-02 실측으로 발견: 51px 막대가 40px 선
   아래로 표시됐다). 라벨 유무와 무관하게 같은 자리를 차지해야 한다. */
.q-l{display:block;height:12px;font-size:9.5px;color:var(--muted);white-space:nowrap;
 margin-top:2px;line-height:12px}
/* 분기 적정물량 기준선. 데이터가 아니라 잣대라 색은 중립(ink2) — 빨강을 쓰면
   '부족' 데이터 색과 헷갈린다. 라벨은 선 위 오른쪽에 붙인다. */
.q-ref{position:absolute;left:0;right:0;border-top:1px dashed var(--ink2);pointer-events:none}
/* 라벨은 왼쪽 — 45존 중 37곳이 16분기라 가로 스크롤이 생기는데, 오른쪽에 두면
   스크롤하기 전엔 보이지 않는다(2026-08-02 실측). 흰 배경으로 막대 위에 얹는다. */
.q-ref i{position:absolute;left:0;bottom:-6px;font-style:normal;font-size:9.5px;
 color:var(--ink2);white-space:nowrap}
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
/* 제목 옆 인라인이면 '향후 4년 · 29개 단지 · 총 29,184세대'가 h2 안에서 어색하게
   접힌다(2026-08-02 사용자). 아래 줄로 내리면 구조적으로 다른 섹션의 .note
   부제와 같은 역할이 되므로 크기·색도 .note에 맞춘다 — 키우려면 .note와 함께. */
.ux{font-style:normal;font-size:11px;color:var(--muted);font-weight:600;
 background:#eef1ef;border-radius:2px;padding:1px 4px;margin-left:4px;cursor:help}
.ucnt{display:block;font-size:13.5px;color:var(--muted);font-weight:400;
 line-height:1.75;margin:5px 0 0}
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
.utable2 @media(max-width:560px){.utable2{font-size:12.5px}}
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
/* 홈 순위 행(.sc-lab/.sc-val/.sc-tier)의 어법을 그대로 가져온다 — 이름 13.5/600 ink,
   값 13.5/600 등급색·tabular, 판정은 표와 같은 .tag 배지.
   ⚠️ 예전엔 color·text-decoration이 없어 브라우저 기본 링크색(파랑/방문 보라)과
   밑줄이 그대로 나왔다(2026-08-01 지적). 카드 전체가 링크일 땐 반드시 죽일 것. */
.near{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
.n-card{border:1px solid var(--line);background:#fff;padding:11px 12px;
 display:flex;flex-direction:column;align-items:flex-start;gap:5px;
 text-decoration:none;color:var(--ink)}
.n-card:hover{border-color:var(--ink)}
.n-card:visited{color:var(--ink)}
.n-card b{font-size:13.5px;font-weight:600;color:var(--ink)}
.n-card .n-v{font-size:13.5px;font-weight:600;font-variant-numeric:tabular-nums}
/* 판정 배지는 허브 표와 같은 .tag 어법. 이 클래스는 그동안 HUB_TPL에만 있어서
   존 페이지에서 쓰면 스타일 없이 16px 맨몸으로 나온다 — 정의를 여기에도 둔다. */
.tag{font-size:11.5px;font-weight:600;padding:2px 7px;border-radius:0;white-space:nowrap}
.tag.g4{background:#fdecea;color:#a93226}
.tag.g3{background:#fbeee9;color:#c0392b}
.tag.g2{background:#faf3e7;color:#b9770e}
.tag.g1{background:#edf0ee;color:#5e6f74}
.tag.g0{background:#e9f0f7;color:#1a5276}
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
# 소속 시군구만 골라 단순 산술평균해 보여준다(세대 가중 아님 — 화면 카피도 '시군구 평균').
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
    # sys.path는 모듈 로드 시 1회만 손댄다 — 예전엔 여기서 매 호출 insert해
    # 존 44곳 렌더에 경로가 44번 쌓였다(2026-08-01 리뷰 M9).
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

    # 아래 그래프가 월간 매매·전세·월세 3계열이므로 숫자도 같은 3개로 맞춘다.
    # 예전엔 주간매매+월간매매+월간전세를 섞어 놓아, 같은 '매매'가 두 기준으로 두 번
    # 나오고 월세는 그래프에만 있었다(2026-08-01 사용자 지적).
    # 기준 월은 세 칩이 공유하므로 칩마다 반복하지 않고 소제목에 한 번만 적는다 —
    # '이번 달' 접두어도 뺐다. 모바일에서 줄바꿈이 과했던 주범.
    def chip(lab, ser):
        if not ser:
            return ''
        _p, v = ser[-1]
        col = '#a93226' if v > 0 else ('#1a5276' if v < 0 else 'var(--muted)')
        return ('<span class="px-c">%s <b style="color:%s">%+.2f%%</b></span>'
                % (lab, col, v))

    now = ''.join([chip(lab, mo.get(k) or []) for k, lab, _c in SERIES])
    _base = next((ser[-1][0] for k, _l, _c in SERIES for ser in [mo.get(k) or []] if ser), '')

    # ── 24개월 지수 흐름(마지막=100 기준 역산) ──
    # ⚠️ 계열마다 길이가 다를 수 있다(월세는 나중에 붙은 계열이라 짧을 수 있음).
    # 월을 x축의 단일 기준으로 삼고 각 계열을 그 축에 맞춰 채운다 — 예전엔 계열별
    # enumerate 인덱스로 그려서, 짧은 계열이 왼쪽으로 밀리고 툴팁도 다른 달 값을
    # 가리켰다(2026-08-01 리뷰 M1. 현재는 44존 전부 24개월 동일이라 미발현이었다).
    months = sorted({p_ for k, _, _ in SERIES for p_, _ in (mo.get(k) or [])})[-24:]
    mi = {m: i for i, m in enumerate(months)}
    lines = []
    for k, _, _ in SERIES:
        ser = [(p_, v) for p_, v in (mo.get(k) or []) if p_ in mi]
        if len(ser) < 6:
            lines.append(None)
            continue
        lvl, cur = {}, 100.0
        for p_, v in reversed(ser):
            lvl[p_] = cur
            cur = cur / (1 + v / 100)
        # 축 기준으로 정렬 — 값이 없는 달은 None(선을 끊는다)
        lines.append([lvl.get(m) for m in months])
    live = [(SERIES[i], l) for i, l in enumerate(lines) if l]
    if not live:
        return ('<div class="pidx"><h3>이 지역 아파트값은 지금 어떤가</h3>'
                '<p class="px-sub">한국부동산원 가격지수 · 생활권 평균</p>'
                '<div class="px-now">%s</div></div>' % now)

    vals = [v for _, l in live for v in l if v is not None]
    lo, hi = min(vals), max(vals)
    pad = max((hi - lo) * 0.12, 0.4)
    lo, hi = lo - pad, hi + pad
    # 축 여백·글자는 2026-08-02에 키웠다. viewBox 좌표라 화면에선 컨테이너 폭에
    # 비례해 줄어든다 — 모바일에서 10px는 사실상 안 읽혔다. 라벨 폭이 늘어난 만큼
    # 좌측(L)·하단(B) 여백도 같이 늘려야 잘리지 않는다.
    W, H = 640.0, 214.0
    L, R, T, B = 52.0, 10.0, 12.0, 30.0
    AXF = 12.5           # 축 글자 크기(viewBox 단위)
    n = max(len(months), 2)

    def X(i):
        return L + (W - L - R) * i / (n - 1)

    def Y(v):
        return T + (H - T - B) * (1 - (v - lo) / (hi - lo))

    g = []
    # y 그리드 3줄 + 라벨. 지수 절대값(94, 101…)은 읽는 사람에게 의미가 없다 —
    # 최근값=100 정규화라 (v-100)이 곧 '지금 대비 몇 %'다(2026-08-02 사용자 요청).
    for t in (0.0, 0.5, 1.0):
        v = lo + (hi - lo) * t
        y = Y(v)
        g.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#e6eae8"/>'
                 % (L, y, W - R, y))
        g.append('<text x="%.1f" y="%.1f" font-size="%.1f" fill="#8a969b" text-anchor="end">%s</text>'
                 % (L - 7, y + AXF * 0.34, AXF,
                    ('%+.0f%%' % (v - 100)) if abs(v - 100) >= 0.5 else '0%'))
    # 100 기준선(현재 수준)
    if lo < 100 < hi:
        g.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#c4cec9" '
                 'stroke-dasharray="3 3"/>' % (L, Y(100), W - R, Y(100)))
    # x 눈금: 반년 간격(1월·7월) + 마지막. 예전엔 1월만 찍어 2년 창에서 라벨이
    # 두 개뿐이었다 — 어느 구간을 보고 있는지 가늠이 안 됐다.
    last_i = len(months) - 1
    for i, m in enumerate(months):
        half = m.endswith('-01') or m.endswith('-07')
        if not (half or i == last_i):
            continue
        # 마지막 라벨과 붙는 눈금은 건너뛴다(겹쳐 읽히면 둘 다 못 읽는다)
        if half and i != last_i and (last_i - i) * (W - L - R) / max(n - 1, 1) < 46:
            continue
        g.append('<text x="%.1f" y="%.1f" font-size="%.1f" fill="#8a969b" '
                 'text-anchor="%s">%s</text>'
                 % (X(i), H - 8, AXF, 'end' if i == last_i else 'middle', m))
    for (k, lab, col), l in live:
        pts = ' '.join('%.1f,%.1f' % (X(i), Y(v))
                       for i, v in enumerate(l) if v is not None)
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
    def _tipvals(k):
        d = dict(mo.get(k) or [])
        return [round(d[m], 2) if m in d else None for m in months]

    tip = {'m': months,
           's': [{'k': lab, 'c': col, 'v': _tipvals(k)}
                 for (k, lab, col), _ in live]}
    svg = ('<svg viewBox="0 0 %d %d" role="img" aria-label="%s 아파트 매매·전세·월세 지수 흐름" '
           'data-tip=\'%s\'>%s</svg>'
           % (int(W), int(H), zone,
              json.dumps(tip, ensure_ascii=False).replace("'", '&#39;'), ''.join(g)))
    legend = ''.join('<span class="px-lg"><i style="background:%s"></i>%s</span>' % (col, lab)
                     for (k, lab, col), _ in live)
    # 소제목은 출처·기준만 남긴다. '그래프를 짚으면 그 달 수치'는 사용법 안내라 뺐다
    # — 가이드 문구는 UI로 풀 문제다(디자인 원칙). 기준 월도 칩마다 반복하지 않고 여기 한 번.
    return ('<div class="pidx"><h3>이 지역 아파트값은 지금 어떤가</h3>'
            '<p class="px-sub">한국부동산원 가격지수 · 생활권 평균 · %s · 최근값=100</p>'
            '<div class="px-now">%s</div>'
            '<div class="px-lgs">%s</div>%s'
            '<div class="px-tip" hidden></div>'
            '<a class="px-more" href="/#stats">전국 시황 통계 자세히 보기 →</a>'
            '</div>' % (_base, now, legend, svg))

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
        # 순위 = 표준 순서(zone_order) 상의 위치 — 홈·허브의 나열 순서와 같은 값이다.
        rk = [i for i, x in enumerate(zone_order(allrows), 1) if x['z']['z'] == nm]
        ranktxt = ('생활권 %d곳 중 %d위' % (len(allrows), rk[0])) if rk else ''
        rank_no = rk[0] if rk else 0
    span = ('%s~%s' % (z.get('q0'), z.get('q1'))) if z.get('span') else '예정 없음'

    # 재고 궤적(지금·1~4년 뒤 부족 여부)은 calc()가 r['seq']로 실어 보낸다 — 홈
    # scCalc도 같은 5개 값을 쓴다(zsched 전량은 페이로드가 커서 못 보낸다).
    _seq = r.get('seq') or [r['inow']] * 5
    _labs = ('지금', '1년', '2년', '3년', '4년')
    _short = [i for i, v in enumerate(_seq) if v < 0]
    # ⚠️ 부족 칸이 연속이라는 보장이 없다. 울산권처럼 ●●○○● 로 오가는 존이 있어
    # _labs[_short[-1]+1] 같은 접근은 IndexError를 낸다(2026-08-02 실제 크래시).
    _last = len(_seq) - 1
    _flip_late = _last in _short and 0 not in _short      # 여유 → 부족
    _flip_early = _last not in _short and 0 in _short     # 부족 → 여유

    # ── ① 판정 히어로 — 5등급 배지 + 자연어 판정문 (2026-07-31 UX 재기획) ──
    # 저장 버튼 없음 — 2026-07-31 사용자 결정: 명시적 '저장' 대신 페이지를 보면
    # 조용히 기억(암묵 저장, 하단 save_js). 홈 히어로가 이 값을 읽는다.
    # 문구는 등급(크기)만이 아니라 **시점**도 말한다(2026-08-02 사용자). 대구권은
    # 등급이 '균형'인데 1년 뒤 부족으로 뒤집혀서, "필요한 만큼 들어오고 있습니다"가
    # 바로 아래 시퀀스와 모순처럼 읽혔다. 전환이 있는 존만 갈아끼운다.
    if 0 < len(_short) < len(_seq):
        if _flip_late:
            hero_desc = '%s 뒤부터 모자라기 시작합니다' % _labs[_short[0]]
        elif _flip_early:
            hero_desc = '지금은 모자라지만 %s 뒤 풀립니다' % _labs[_short[-1] + 1]
        else:
            hero_desc = '시기에 따라 모자랐다 풀렸다 합니다'
    else:
        hero_desc = gr['desc']
    hero_html = (
        '<span class="zg-badge" style="background:%s1a;color:%s">%s</span>\n'
        '<h1>%s, %s</h1>\n'
        '<p class="zg-cap">공급 기준 · %s 데이터 · %s</p>\n'
        % (gr['color'], gr['color'], gr['label'], nm, hero_desc, prd, ranktxt))

    # ── ② 왜 이 판정인가 — 근거 3줄. 세 줄의 합이 히어로 순부족과 정확히 일치
    # (need4/inow/fsupw만 사용 — tot == need4 - fsupw - inow 항등식이 Task 1
    # 테스트로 보장된다). 여유 존(tot<0)은 "여유"로 문구 분기.
    backlog = -r['inow']          # 양수면 '밀린 집', 음수면 '쌓인 재고'
    # 2026-07-31 사용자 피드백: '필요한 집'(미래)과 '밀린 것'(과거)은 시간 방향이
    # 반대인데 라벨에 안 드러나고, 상한 도달 존은 숫자까지 같아(둘 다 4년치) 버그처럼
    # 보였다. → 과거→미래 시간순으로 재배열하고 각 줄에 [과거]/[앞으로 4년] 시간
    # 칩을 달아 방향을 명시한다. 서사: "이미 이만큼 밀렸는데, 앞으로 이만큼 더
    # 필요하고, 들어올 건 이것뿐".
    # 창 방식(2026-08-02)이라 '지난 4년'이 문자 그대로 참이다 — 4년 전 0에서 시작해
    # 준공-멸실-적정을 그대로 더한 값이다. '최대 4년치' 같은 완곡한 표현이 필요 없다.
    b_lab, b_sub = ('그동안 밀린 집', '지난 4년 누적 · 실측') if backlog >= 0 \
              else ('그동안 쌓인 집', '지난 4년 누적 · 실측')
    if backlog >= 0 and abs(backlog - r['need4']) < 1:
        b_sub = ('과거 누적 · 4년치 상한 도달 — 실제로는 더 밀렸습니다'
                 '(그래서 아래 ‘필요한 집’과 숫자가 같습니다)')
    # 필요한 집 출처: 풀 소속 존은 풀 이름·구성·풀 내 세대 비중으로 표기.
    if r.get('pool'):
        need_src = '%s 풀(%s) 세대의 %d%%' % (
            r['pool'], '·'.join(m[:-1] for m in POOLS[r['pool']]),
            round((r['pshare'] or 0) * 100))
    elif nm == ps:
        # 롤업(수도권)은 자기 자신이 시도라 "수도권 세대의 94%"가 자기참조로 읽혔다.
        # 2026-08-02 사용자 결정: 생활권에 편입되지 않은 시군구(가평·연천 등 17곳,
        # 약 72만 세대)는 아공맵의 '수도권' 정의에서 **아예 뺀다**. 그러면 남은
        # 22곳이 정의상 전부라 커버리지 %를 말할 대상이 없어진다 — 숫자를 100%로
        # 고쳐 쓰는 게 아니라 주장을 걷어낸다. 각 존의 zrefq는 그대로다(시도
        # 적정물량을 세대 비중으로 나눈 값이라, 분모를 22곳으로 좁히면 refq도 같은
        # 비율로 좁아져 서로 상쇄된다 — 빠진 시군구 수요를 22곳에 얹지 않는다).
        need_src = '생활권 %d곳 합계 · 추정' % len(r.get('subs') or [])
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
    # ── 재고 궤적 5칸 (2026-08-02 사용자 요청) ──────────────────────────────
    # 순부족 하나로는 '얼마나'만 보이고 '언제'가 안 보인다. 지금/1·2·3·4년 뒤
    # 재고 부호를 5칸으로 찍으면 같은 값이라도 모양이 갈린다 — 대구권은 지금
    # 여유인데 1년 뒤 부족으로 뒤집히고(○●●●●), 화성권은 4년 내내 부족이다(●●●●●).
    # ⚠️ 개수가 아니라 순서를 보여준다. 남양주(●●●○○ 해소)와 울산(●●○○● 출렁)은
    # 부족 칸 수가 같지만 이야기가 정반대다 — 합치면 그 차이가 사라진다.
    # ⚠️ 별(★)은 쓰지 않는다. 타깃이 내집 마련 실수요자라 ★는 '추천'으로 읽히는데,
    # 여기서 칸이 차는 건 나쁜 소식이다.
    # 계산(_seq/_short/_labs/_last/_flip_*)은 히어로 위에서 이미 끝났다 — 제목과
    # 이 시퀀스가 같은 값을 써야 서로 다른 말을 하지 않는다.
    if not _short:
        _msg = '4년 내내 공급이 넉넉합니다'
    elif len(_short) == len(_seq):
        _msg = '4년 내내 부족합니다'
    elif _flip_early:
        _msg = '지금은 부족하지만 %s 뒤 풀립니다' % _labs[_short[-1] + 1]
    elif _flip_late:
        _msg = '%s 뒤부터 부족으로 바뀝니다' % _labs[_short[0]]
    else:
        _msg = '시기에 따라 부족과 여유를 오갑니다'
    seq_html = (
        '<div class="seq"><div class="seq-msg">%s</div><div class="seq-row">%s</div></div>'
        % (_msg, ''.join(
            '<div class="seq-c%s"><i></i><span>%s</span></div>'
            % (' on' if v < 0 else '', _labs[i]) for i, v in enumerate(_seq))))
    why_html = (
        '<section><div class="wrap"><h2>왜 이 판정인가</h2>'
        '%s%s'
        '<div class="why3">'
        '<div class="w-row"><span class="w-lab"><em class="w-tag">과거</em>%s<i>%s</i></span><b>%s%s</b></div>'
        '<div class="w-row"><span class="w-lab"><em class="w-tag">앞으로 4년</em>필요한 집<i>%s</i></span><b>+%s</b></div>'
        '<div class="w-row"><span class="w-lab"><em class="w-tag">앞으로 4년</em>들어올 집<i>준공예정 실측 · 액면 그대로</i></span><b>−%s</b></div>'
        '</div>%s</div></section>' % (
            verdict_html, seq_html,
            b_lab, b_sub, ('+' if backlog >= 0 else '−'), num(abs(backlog)),
            # 롤업은 need_src가 이미 완결된 문장이라 '= X 몫' 꼬리를 붙이지 않는다
            # ("수도권 세대의 94% = 수도권 몫"이 자기참조로 읽혔다 — 2026-08-02).
            need_src if nm == ps else ('%s = %s 몫 · 추정' % (need_src, nm)),
            num(r['need4']),
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
    # ⚠️ 예전엔 `byq[q] > 0`으로 걸러 **공급 0인 분기를 아예 안 그렸다**. 45존 중 39곳이
    # 그랬고, 화성권은 16분기 중 3개만 그려져 그 3개가 적정선 위로 솟는 바람에
    # '매우 부족'인데 공급이 넘치는 것처럼 보였다(2026-08-02 사용자 지적).
    # 빈 분기가 곧 부족이므로 지평선 16분기를 빠짐없이 그린다.
    qs = [_qkey(_curq + k) for k in range(1, FUT_HORIZON + 1)]
    qv = {q: byq.get(q, 0) for q in qs}          # 없는 분기 = 0(그게 부족이다)
    def qlabel(q):
        return q[2:4] + 'Q' + q[5]
    if qs:
        mxq = max(qv.values()) or 1
        peakq = max(qs, key=lambda q: qv[q])
        # 기준선(분기 적정물량 zrefq)을 함께 그린다 — 막대만 있으면 '많다/적다'를
        # 잴 자가 없다. 눈금은 px로 고정한다: 적정선이 최대 막대보다 높을 수도 있어
        # (공급 가뭄 지역) 축 상한을 둘 중 큰 값으로 잡아야 선이 화면 안에 남는다.
        PLOT_H = 72          # 막대 영역 높이(px)
        LABEL_H = 14         # 막대 아래 분기 라벨(.q-l) 높이 — 기준선 offset의 기준
        qref = r.get('zrefq') or 0
        scale = max(mxq, qref) or 1
        # 막대 농도는 균일하다. 예전엔 _conf(k)를 농도에 실어 '먼 분기일수록 옅게'
        # 그렸는데, conf 폐지(2026-08-02)로 먼 분기를 덜 세지 않으니 옅게 그리면
        # 화면이 모델에 없는 감쇠를 말하게 된다. 같은 값은 같은 농도로 그린다.
        # 분기 라벨은 연초(Q1)와 첫 칸만 — 16개를 다 쓰면 겹쳐서 못 읽는다.
        # 막대 위 숫자는 16칸에 다 못 넣는다 → 누르면(모바일)·올리면(PC) 값을 띄운다.
        # data-*에 값을 실어두고 아래 스크립트가 읽는다.
        cols = ''.join(
            '<button type="button" class="q-col" data-q="%s" data-v="%s" '
            'aria-label="%s %s세대"><div class="q-bar" style="height:%dpx"></div>'
            '<span class="q-l">%s</span></button>' % (
                qlabel(q), num(qv[q]), qlabel(q), num(qv[q]),
                int(round(qv[q] / scale * PLOT_H)),
                # 연초(Q1)만 — 첫 칸을 억지로 붙이면 바로 옆 Q1과 겹쳐 못 읽는다
                qlabel(q) if q.endswith('Q1') else '')
            for q in qs)
        if qref:
            cols += ('<div class="q-ref" style="bottom:%dpx">'
                     '<i>적정 %s</i></div>'
                     % (LABEL_H + int(round(qref / scale * PLOT_H)), num(qref)))
        # 합계는 여기서만 보여준다 — 단지 목록(상위 N곳)과 헷갈리지 않게 '전체'로 명시.
        # 2026-08-01 리뷰 I1은 ②'들어올 집'(당시 conf 가중)과 여기 '전체'(원시 합)가
        # 최대 36% 어긋나 보인다는 지적이었고, 그때는 가중 후 값을 괄호로 병기해 이었다.
        # conf 폐지(2026-08-02)로 두 값이 같아져 병기가 불필요해졌다 — 같은 숫자를
        # 두 번 쓰면 오히려 다른 뜻으로 읽힌다. 어긋나면 그건 이제 진짜 버그다.
        qchart_html = ('<div class="qwrap"><div class="qtitle">분기별 입주 예정 물량 (세대) '
                       '<b style="color:var(--ink)">· 전체 %s세대</b></div>'
                       '<div class="q-tip" hidden></div>'
                       '<div class="qchart"><div class="q-inner">%s</div></div></div>'
                       % (num(sum(qv.values())), cols))
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
        # ⚠️ 원본(건축HUB)이 이미 '무등산자이&amp;어울림'처럼 실체참조로 들어온다.
        # 그대로 escape하면 &amp;amp;가 돼 화면에 '&amp;'가 노출된다(2026-08-01 사용자 지적).
        # unescape 후 escape하면 멱등이라 원본이 어느 쪽이든 한 번만 이스케이프된다.
        _esc = lambda s: (html_mod.unescape(str(s)).replace('&', '&amp;').replace('<', '&lt;')
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
        '<div class="card"><b>가격을 맞히는 지표는 아니다</b><span>2010년 이후 44개 생활권 실측에서, 금리가 크게 움직인 시기엔 공급의 영향이 거의 보이지 않았고, 금리가 잔잔한 시기에도 공급이 적었던 곳이 이후 2년간 평균 2%%p 남짓 더 올랐을 뿐입니다.</span></div>\n'
        '<div class="card"><b>공급은 3년 전에 결정된다</b><span>오늘 인허가받은 아파트는 3년쯤 뒤에 입주합니다. 즉 지금 보이는 입주예정 물량은 이미 확정된 미래이고, 바꿀 수 없습니다.</span></div>\n'
        '<div class="card"><b>순위는 비율, 숫자는 절대량</b><span>등급·순위는 필요량 대비 부족 비율로 매깁니다. 화면의 세대수는 절대량이라 순위와 순서가 다를 수 있습니다.</span></div>\n'
        '</div></details>')
    methodology_details_html = (
        origin_fold_html + calc_fold_html + compo_fold_html + caution_fold_html +
        '<a class="cta" href="/cycle/">사이클 리포트 읽기 →</a>')
    # 이천·평택 공시(2026-08-01 사용자 결정): 이 두 곳은 수도권 가격 사이클과
    # 독립적으로 움직이는 것으로 실측됐지만(잔차 동조 0.14 이하), 자체 적정물량
    # 역산이 표본 부족(금리쇼크 저점 제외 시 전환점 1개)으로 불가해 수도권 안분을
    # 유지한다 — 그 사실을 숨기지 않고 명시한다.
    indep_note = ''
    # 서울과의 위상 관계(동행/확산) — 유의한 6곳만. 시차 길이는 안 쓴다(위 주석).
    _sync = SEOUL_SYNC.get(nm)
    if _sync == 'lag':
        indep_note += ('<p class="note"><b>서울과의 관계</b>: %s 가격은 서울에 '
                       '<b>뒤이어</b> 움직이는 경향이 실측됩니다. 서울이 이미 방향을 '
                       '바꾼 뒤에도 이곳은 아직 반영 전일 수 있습니다. 다만 시차 길이는 '
                       '시기마다 달라(최근일수록 길어지는 추세) 몇 개월이라고 못박지 '
                       '않습니다.</p>' % nm)
    elif _sync == 'co':
        indep_note += ('<p class="note"><b>서울과의 관계</b>: %s 가격은 서울과 '
                       '<b>거의 같은 시점에</b> 움직이는 것으로 실측됩니다.</p>' % nm)
    if nm in INDEP_ZONES:
        indep_note += ('<p class="note"><b>이 지역만의 참고</b>: %s 가격은 수도권 사이클과 '
                      '독립적으로 움직이는 것으로 실측됐습니다. 위 \'필요한 집\'은 수도권 기준 '
                      '배분값이라 실제 지역 수요와 다를 수 있습니다 — 다음 가격 전환점이 '
                      '확인되면 이 지역만의 값으로 다시 계산할 예정입니다.</p>' % nm)
    # 면책은 푸터 한 곳에만. 남은 건 '이 지표를 어떻게 읽나'라는 해석 안내라
    # 별도 섹션·별도 접힘을 만들지 않고 아래 '주의할 점' 접힘의 첫 카드로 넣었다
    # (접힘이 5개로 늘면 그 자체가 또 다른 소음이다).
    # ⚠️ 제목을 없애지 말 것. 면책 정리(80a26b7) 때 <h2>이 숫자의 한계</h2>를 걷었더니
    # 방법론 접힘 4개(어디서 왔나·어떻게 계산했나·어디를 묶었나·주의할 점)가 제목 없이
    # 떠 있는 섹션이 됐다(2026-08-02 데이터 세션이 회귀로 잡음). 면책 문구는 푸터로
    # 옮기는 게 맞았지만 '이 묶음이 무엇인지'를 말하는 제목까지 지운 건 과했다.
    # 새 제목은 면책이 아니라 내용 그대로 — 접힘들이 실제로 답하는 것이 산출과 한계다.
    limits_html = (
        '<section><div class="wrap"><h2>산출 방법과 한계</h2>%s%s</div></section>'
        % (indep_note, methodology_details_html))

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

    # ── 공유. 지역 단톡방이 이 리포트의 자연 유통 경로라, 공유를 한 번의 탭으로
    # 만든다. 카카오 SDK는 싣지 않는다 — 존 페이지는 SEO 랜딩이라 가벼워야 하고,
    # Web Share API를 쓰면 모바일에서 카톡을 포함한 네이티브 공유 시트가 열려
    # 결과가 같으면서 스크립트가 0바이트다. 링크만 전달되면 카톡이 og:image
    # (share/zone-<이름>.png)를 읽어 지역명 카드를 띄운다.
    # 데스크톱엔 share API가 없는 경우가 많아 클립보드로 폴백한다.
    share_html = (
        '<section class="zshare"><div class="wrap">'
        '<p class="zs-lead">이 지역에 관심 있는 사람에게 보내보세요</p>'
        '<button class="cta sub" onclick="shareZone()">'
        '<svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true">'
        '<path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round" d="M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7M12 3v13M8 7l4-4 4 4"/>'
        '</svg>%s 리포트 공유하기</button>'
        '</div></section>' % nm)

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
                    '<span class="n-v" style="color:%s">%s</span>'
                    '<span class="tag %s">%s</span></a>'
                    % (x['z']['z'], x['z']['z'], x['gr']['color'], signed_u(x['tot']),
                       x['gr']['k'], x['gr']['label'])
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
            # 분기 막대 → 값 읽기. 누르면 그 분기 값을 차트 위 한 줄에 띄운다.
            # 기본은 물량이 가장 많은 분기를 미리 띄워 빈 줄이 안 보이게 한다.
            '<script>(function(){var wrap=document.querySelector(".qwrap");if(!wrap)return;'
            'var tip=wrap.querySelector(".q-tip"),cols=wrap.querySelectorAll(".q-col");'
            'if(!tip||!cols.length)return;'
            'function hide(){tip.hidden=true;cols.forEach(function(c){c.classList.remove("on")});}'
            'function show(b){cols.forEach(function(c){c.classList.toggle("on",c===b)});'
            'tip.innerHTML=b.dataset.q+" <span>입주 예정</span> <b>"+b.dataset.v+"</b><span>세대</span>";'
            'tip.hidden=false;'
            'var wr=wrap.getBoundingClientRect(),br=b.getBoundingClientRect();'
            'var x=br.left-wr.left+br.width/2,y=br.top-wr.top-6;'
            'tip.style.left="0px";tip.style.top="0px";'
            'var tw=tip.offsetWidth;'
            'x=Math.max(tw/2+2,Math.min(x,wr.width-tw/2-2));'
            'tip.style.left=x+"px";tip.style.top=y+"px";}'
            'cols.forEach(function(c){'
            # 터치는 합성 mouseenter가 click보다 먼저 온다 — click을 토글로 두면
            # 첫 탭이 show 직후 hide로 상쇄돼 두 번 눌러야 했다(2026-08-02 실기기).
            # click은 무조건 show, hover는 마우스 포인터일 때만.
            'c.addEventListener("click",function(e){e.stopPropagation();show(c)});'
            'c.addEventListener("pointerenter",function(e){'
            'if(!e.pointerType||e.pointerType==="mouse")show(c);});'
            'c.addEventListener("focus",function(){show(c)});});'
            'wrap.addEventListener("mouseleave",hide);'
            'document.addEventListener("click",function(e){'
            'if(!wrap.contains(e.target))hide();});})();</script>'
            '<script>(function(){var w=document.querySelector(".pidx");if(!w)return;'
            'var svg=w.querySelector("svg"),tip=w.querySelector(".px-tip");'
            'if(!svg||!tip)return;var d;try{d=JSON.parse(svg.getAttribute("data-tip"))}catch(e){return}'
            'var mk=svg.querySelector(".px-mk"),vl=svg.querySelector(".px-vline"),'
            'dots=svg.querySelectorAll(".px-dot"),lines=svg.querySelectorAll("polyline"),'
            'hits=svg.querySelectorAll(".px-hit");'
            'var step=hits.length?parseFloat(hits[0].getAttribute("width")):1;'
            'function pts(p){return p.getAttribute("points").split(" ").filter(Boolean).map(function(s){'
            'var a=s.split(",");return [parseFloat(a[0]),parseFloat(a[1])]})}'
            'var P=[].map.call(lines,pts);'
            # 결측이 있으면 polyline 점 배열과 월 인덱스가 어긋난다 — x는 히트영역
            # 중심에서 얻고, 각 계열 점은 그 x에 가장 가까운 것을 쓴다(리뷰 M1).
            'function hx(i){var r=hits[i];return parseFloat(r.getAttribute("x"))+parseFloat(r.getAttribute("width"))/2}'
            'function near(pp,x){var b=null,bd=1e9;for(var j=0;j<pp.length;j++){'
            'var d=Math.abs(pp[j][0]-x);if(d<bd){bd=d;b=pp[j]}}return (bd<=step/1.5)?b:null}'
            'function show(i){var x=hx(i);mk.style.display="";'
            'vl.setAttribute("x1",x);vl.setAttribute("x2",x);'
            'for(var k=0;k<dots.length;k++){var pt=P[k]?near(P[k],x):null;'
            'if(!pt){dots[k].style.display="none";continue}'
            'dots[k].style.display="";dots[k].setAttribute("cx",pt[0]);dots[k].setAttribute("cy",pt[1])}'
            'var h="<b>"+d.m[i]+"</b>";'
            'for(var s=0;s<d.s.length;s++){var v=d.s[s].v[i];if(v==null)continue;'
            'h+="<br><i style=\\"background:"+d.s[s].c+"\\"></i>"+d.s[s].k+" "+(v>0?"+":"")+v.toFixed(2)+"%"}'
            'tip.innerHTML=h;tip.hidden=false;tip.style.opacity=1;'
            'var ys=[].filter.call(dots,function(d){return d.style.display!=="none"})'
            '.map(function(d){return +d.getAttribute("cy")});'
            'var vy=ys.length?Math.min.apply(null,ys):0;'
            'var b=svg.getBoundingClientRect(),wb=w.getBoundingClientRect(),'
            'x=b.left-wb.left+hx(i)/svg.viewBox.baseVal.width*b.width,'
            'y=b.top-wb.top+vy/svg.viewBox.baseVal.height*b.height;'
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
<meta property="og:image" content="%(site)s/share/zone-%(enc)s.png">
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
%(share)s
%(nav)s

<footer><div class="wrap">
  <b>아공맵</b> — 아파트 · 공급량 · 투자지도<br>
  <a href="/">agongmap.co.kr</a> · <a href="/about/">아공맵 소개</a> · 자료: 한국부동산원 입주예정물량 · 국토교통부 주택건설실적 · 행정안전부 주민등록인구 · 한국은행
  <div class="disc">공공 데이터를 가공한 참고 자료이며 투자자문이 아닙니다. 투자 판단과 책임은 이용자에게 있습니다.</div>
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
function shareZone(){
  var nm='%(nm)s';
  var u=location.origin+location.pathname+'?utm_source=zone_share&utm_medium=viral&utm_campaign=zone';
  var t=nm+' 아파트 공급 분석 — 아공맵';
  var x=nm+'에 필요한 집과 앞으로 들어올 집, 국가 통계로 확인해보세요.';
  try{gtag('event','share',{content_type:'zone',method:navigator.share?'web_share':'copy',zone:nm});}catch(e){}
  if(navigator.share){navigator.share({title:t,text:x,url:u}).catch(function(){});return;}
  var b=document.querySelector('.zshare button');
  function done(m){if(!b)return;var o=b.innerHTML;b.textContent=m;setTimeout(function(){b.innerHTML=o;},2000);}
  if(navigator.clipboard&&navigator.clipboard.writeText){
    navigator.clipboard.writeText(t+'\\n'+u).then(function(){done('링크가 복사됐어요');})
      .catch(function(){done('복사 실패 — 주소창을 복사하세요');});
  }else{done('복사 실패 — 주소창을 복사하세요');}
}
</script>
%(save_js)s

</body>
</html>""" % dict(
        title=title, desc=desc, site=SITE, nm=nm, enc=quote(nm), tname=tname, tcol=tcol, disp=disp,
        ranktxt=ranktxt, prd=prd, fq=r['fq'],
        hero=hero_html, why=why_html, timeline=timeline_html, units=units_sec_html,
        flag=flag_html, limits=limits_html, near=near_html, nav=nav_html, save_js=save_js,
        share=share_html,
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
  <h2>전국 생활권 44곳</h2>
  <p>홈 순위표와 <b>같은 기준</b>(등급으로 묶고, 그 안은 세대수 큰 순)으로 나열합니다.
    홈은 양끝(가장 모자란 곳·가장 남는 곳)만 보여주고, 여기서는 44곳을 모두 폅니다.<br>
    생활권 이름을 누르면 판정 근거(밀린 것·필요한 집·들어올 집)와 분기별 입주 일정,
    그 지역 아파트값 흐름까지 볼 수 있습니다.</p>
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
  <a href="/">agongmap.co.kr</a> · <a href="/about/">아공맵 소개</a> · 자료: 한국부동산원 입주예정물량 · 국토교통부 주택건설실적 · 행정안전부 주민등록인구<br>
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
    # 수도권 롤업 행 폐지(2026-08-03). 예전엔 순위 밖 소계로 끼워 넣었는데,
    # 롤업 안에서 상계가 일어나 서울권 등급을 눌러(단독 +1.03 부족 → 롤업 +0.52
    # 다소 부족) 홈·허브에서 함께 걷어냈다. 이제 44곳 개별만 선다.
    # 정렬 = zone_order(표준 순서) — 홈·존 페이지 'N위'와 같은 하나의 기준.
    live = zone_order(pages)
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
            '<td class="num" style="color:%s">%s</td>'
            '<td><span class="tag %s">%s</span></td></tr>'
            % (i + 1, nm, nm, gr['color'], signed_u(r['tot']), gr['k'], gr['label']))
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
    # 수도권 롤업 폐지(2026-08-03) — 안에서 상계가 일어나 서울권이 한 등급
    # 내려가고 화성권(매우 부족)이 통째로 묻혔다. 행정구역대로 개별만 세운다.
    # make_capital()은 make_naver_post 등 다른 소비자가 있어 함수는 남긴다.
    pages = list(rows)
    zcodes = zone_sgg_codes(adv)
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
