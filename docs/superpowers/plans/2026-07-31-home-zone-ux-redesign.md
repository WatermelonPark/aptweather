# 홈·존 페이지 UX 재기획 구현 계획

> ## ✅ 실행 완료 · 배포됨 (2026-08-03 검증)
>
> Task 1~6 산출물이 모두 실재하고 **라이브 사이트에 반영 완료**(origin/main과 라이브 index.html 해시 일치).
>
> **검증 근거(2026-08-03 실측)**: `tools/tests/test_grade.py`·`GRADE_CUTS`(Python)·`scGrade()`(JS 미러)·
> `check_dual_calc`의 등급 대조·지역 선택기(`agong_myzone` localStorage)·`sw.js` 버전 전부 실재.
> `pytest tools/tests/` **140 passed**, 미러 검증 **44곳 전원 일치**(등급 `grade` 포함).
>
> ⚠️ 아래 체크박스는 단계별 실행 로그가 아니라 **산출물 실측 검증에 근거해 사후 표기**한 것이다.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 실수요자 타깃으로 홈(내 지역 먼저 + 등급 그룹 순위)과 존 페이지(등급 판정 → 근거 → 타임라인 6섹션)를 재구성하고, localStorage 기반 내 지역 저장·재방문 카드를 붙인다.

**Architecture:** 등급은 `순부족 ÷ 4년 필요량` 비율의 절대 컷 5단계. 계산·등급 함수는 Python(`tools/make_zone_pages.py`)·JS(`index.html`) 이중구현 미러이며 `tools/check_dual_calc.py`가 값+등급을 대조한다. 존 페이지는 빌드 타임 정적 생성(45개), 홈은 SPA. 스펙: `docs/superpowers/specs/2026-07-31-home-zone-ux-redesign-design.md`.

**Tech Stack:** Python 3(표준 라이브러리만) · 바닐라 JS(프레임워크 없음) · pytest · Node(미러 검증용)

## Global Constraints

- 새 색 도입 금지 — 기존 토큰만: `#a93226 #c0392b #b9770e #5e6f74 #3a7bd5 #1a5276 var(--muted)` (app.css `.sc-tier` 팔레트)
- '암산' 워딩 금지. 서비스 용어(순부족·러닝재고·적정물량) 대신 유저 언어(필요한 집·밀린 것·들어올 집) — 단 방법론 폴드 안에서는 용어 사용 가능
- 등급 옆에는 항상 "공급 기준 · 가격 예측 아님" 캡션
- Python↔JS 미러: 두 구현을 항상 같은 태스크에서 같이 고친다. 검증은 `python tools/check_dual_calc.py`
- 모든 Python 실행은 `PYTHONIOENCODING=utf-8` 환경변수와 함께 (cp949 콘솔 깨짐 방지)
- 새 페이지·새 데이터 소스·발행 채널 추가 금지
- 커밋 메시지 끝: `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

---

### Task 1: 등급 함수 + 분해값 반환 (Python)

**Files:**
- Modify: `tools/make_zone_pages.py` (ANCHOR 상수부 근처, `running_shortage()`, `calc()`)
- Test: `tools/tests/test_grade.py` (신규)

**Interfaces:**
- Produces: `GRADE_CUTS = (1.5, 1.0, 0.5, -0.5)`, `GRADES` 5-튜플 목록, `grade(tot, need4) -> dict(k,label,color,desc,ratio)`, `running_shortage(..., full=False)` — `full=True`면 `{'tot','inow','demand','supplyw'}` dict 반환, `calc()`의 각 row에 `need4`(refq×share×16), `inow`, `fsupw`, `gr`(grade dict) 필드 추가
- Consumes: 기존 `running_shortage`/`calc` (현행 시그니처 유지 — `full` 생략 시 동작 불변)

- [x] **Step 1: 실패하는 테스트 작성** — `tools/tests/test_grade.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import make_zone_pages as M

def test_grade_cuts_and_boundaries():
    # 컷: (1.5, 1.0, 0.5, -0.5), 경계는 상위 등급 포함(>=)
    assert M.grade(150, 100)['k'] == 'g4'      # 정확히 150% -> 매우 부족
    assert M.grade(149, 100)['k'] == 'g3'
    assert M.grade(100, 100)['k'] == 'g3'      # 정확히 100% -> 부족
    assert M.grade(99, 100)['k'] == 'g2'
    assert M.grade(50, 100)['k'] == 'g2'       # 정확히 50% -> 다소 부족
    assert M.grade(49, 100)['k'] == 'g1'
    assert M.grade(-50, 100)['k'] == 'g1'      # 정확히 -50% -> 균형
    assert M.grade(-51, 100)['k'] == 'g0'      # 그 미만 -> 공급 여유
    assert M.grade(0, 0)['k'] == 'g1'          # need4=0 방어: ratio 0 -> 균형

def test_grade_labels_and_colors():
    g = M.grade(200, 100)
    assert g['label'] == '매우 부족' and g['color'] == '#a93226'
    assert abs(g['ratio'] - 2.0) < 1e-9
    assert M.grade(-100, 100)['label'] == '공급 여유'

def test_running_shortage_full_breakdown():
    # full=True: 분해값 dict. 세 항의 재조합이 tot과 정확히 일치해야 한다
    # (존 페이지 근거 3줄 = 필요 - 들어올것 - 재고, 합이 히어로 숫자와 같아야 신뢰 유지)
    cur = 2026 * 4 + 2
    refq = 50
    sched = {'2026Q4': 50}
    d = M.running_shortage({}, sched, {}, refq, cur, horizon=16,
                           weight_demand=False, full=True)
    assert set(d) == {'tot', 'inow', 'demand', 'supplyw'}
    assert d['demand'] == 16 * refq                      # 800
    assert d['supplyw'] == 50.0                          # conf(1)*50
    assert d['inow'] == -M.DEFICIT_CAP * refq            # 하한 -800
    assert d['tot'] == d['demand'] - d['supplyw'] - d['inow'] == 1550.0
    # full 생략 시 기존과 동일한 float
    s = M.running_shortage({}, sched, {}, refq, cur, horizon=16, weight_demand=False)
    assert s == d['tot']

def test_calc_rows_carry_grade_fields():
    adv, sts = M.load()
    rows = M.calc(adv, sts)
    r = rows[0]
    for k in ('need4', 'inow', 'fsupw', 'gr'):
        assert k in r, k
    assert abs(r['need4'] - r['refq'] * r['share'] * 16) < 1e-6
    # 재조합 정합: tot = demand(=need4) - supplyw - inow
    assert abs(r['tot'] - (r['need4'] - r['fsupw'] - r['inow'])) < 1e-6
    assert r['gr']['k'] in ('g0', 'g1', 'g2', 'g3', 'g4')
```

- [x] **Step 2: 실패 확인**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tools/tests/test_grade.py -q`
Expected: FAIL — `AttributeError: module 'make_zone_pages' has no attribute 'grade'`

- [x] **Step 3: 구현** — `tools/make_zone_pages.py`의 `DEFICIT_CAP = 16` 줄 바로 아래에 추가:

```python
# ── 등급 판정 (2026-07-31 UX 재기획) ─────────────────────────────
# 기준값 = 순부족(tot) ÷ 4년 필요량(refq*share*16). 경계는 상위 등급 포함(>=).
# 절대 컷 고정 — 상대평가는 전국이 과잉이어도 같은 수의 '부족'을 만들어 왜곡한다.
# 색은 app.css .sc-tier 팔레트 재사용(새 색 도입 금지).
# ⚠️ index.html의 scGrade()와 반드시 동치(이중구현 미러) — check_dual_calc가 대조한다.
GRADE_CUTS = (1.5, 1.0, 0.5, -0.5)
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
```

`running_shortage()` 시그니처를 `def running_shortage(done, sched, demol, refq, cur_q, horizon=20, weight_demand=True, full=False):`로 바꾸고, 마지막 `return fut - I_now`를 다음으로 교체:

```python
    tot = fut - I_now
    if full:
        # 존 페이지 '왜 이 판정인가' 근거 3줄용 분해값.
        # 항등식: tot == demand - supplyw - inow (weight_demand=False 기준.
        # True(A안)면 fut가 이미 가중 결합이라 분해가 성립하지 않는다 — 라이브는 False).
        return {'tot': tot, 'inow': I_now, 'demand': demand_sum, 'supplyw': supply_weighted}
    return tot
```

`calc()`의 `tot = running_shortage(...)` 호출부(147행 부근)를 다음으로 교체:

```python
        if inv_path:
            _rs = running_shortage(zdone, zsched, zdemol, refq * share, cur_q,
                                   horizon=horizon, weight_demand=weight_demand, full=True)
            tot = _rs['tot']
        else:
            _rs = None
            tot = tot_fallback
```

같은 함수의 `out.append(dict(...))`에 필드 4개 추가 (기존 키 뒤에):

```python
        need4 = refq * share * 16
        out.append(dict(z=z, ps=ps, share=share, need=need, dA=dA, dB=dB, dC=dC, tot=tot,
                        fsup=fsup, fq=H, flag=flag, lo=lo, hi=hi, loan=loan, pv=pv, plo=plo,
                        dY=dY, refq=refq, band=band, inv_path=inv_path,
                        need4=need4,
                        inow=(_rs['inow'] if _rs else 0.0),
                        fsupw=(_rs['supplyw'] if _rs else 0.0),
                        gr=grade(tot, need4)))
```

(기존 append의 실제 키 목록을 유지한 채 `need4·inow·fsupw·gr`만 더한다 — 위는 형태 예시이며 기존 키를 지우지 말 것.)

⚠️ 수도권 **합계 행**도 잊지 말 것: `calc()` 뒤쪽의 `agg` 조립부(`agg['share'] = sum(...)` 185행 부근)에서 `need4·inow·fsupw`를 구성 존 합으로 더하고, `agg['gr'] = grade(agg['tot'], agg['need4'])`를 넣는다 — `zone/수도권/` 허브 페이지 히어로가 `r['gr']`를 읽는다. `test_calc_rows_carry_grade_fields`에 합계 행 검증 한 줄 추가:

```python
    hub = [x for x in rows if x.get('subs')]
    if hub:
        assert 'gr' in hub[0] and abs(
            hub[0]['need4'] - sum(c['need4'] for c in hub[0]['subs'])) < 1e-6
```

- [x] **Step 4: 통과 확인**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tools/tests/ -q`
Expected: 전체 PASS (기존 123 + 신규 4)

- [x] **Step 5: 커밋**

```bash
git add tools/make_zone_pages.py tools/tests/test_grade.py
git commit -m "등급 판정 grade()/GRADE_CUTS + running_shortage 분해값 반환(full=True)"
```

---

### Task 2: JS 미러 (scGrade + 분해값) + check_dual_calc 등급 대조

**Files:**
- Modify: `index.html` (`scTier` 함수 근처 2296행 부근, `runningShortage` 2306행 부근, `scCalc` 반환부 2360행 부근)
- Modify: `tools/check_dual_calc.py` (grab 목록 47-50행 부근, 대조 루프 86-90행 부근)

**Interfaces:**
- Consumes: Task 1의 `GRADE_CUTS`/`GRADES`/`grade()` 값 정의 (JS에 동일 상수 복제)
- Produces: JS `scGrade(tot, need4) -> {k,label,color,desc,ratio}`, `runningShortage(...)`가 `{tot,inow,demand,supplyw}` 객체 반환, `scCalc()` 각 row에 `need4·inow·fsupw·gr` 추가. check_dual_calc가 `need4·gr.k`까지 대조

- [x] **Step 1: index.html 수정** — `function scTier(v){...}` 바로 아래에 추가:

```js
/* 등급 판정 — tools/make_zone_pages.py grade()와 반드시 동치(미러). 컷·라벨·색 동일. */
var GRADE_CUTS=[1.5,1.0,0.5,-0.5];
var GRADES=[
  ['g4','매우 부족','#a93226','앞으로 4년, 필요한 집이 크게 모자랍니다'],
  ['g3','부족','#c0392b','공급이 수요를 못 따라갑니다'],
  ['g2','다소 부족','#b9770e','부족하지만 심하진 않습니다'],
  ['g1','균형','#5e6f74','필요한 만큼 들어오고 있습니다'],
  ['g0','공급 여유','#1a5276','입주가 몰려 있어 세입자·매수자에게 유리한 시기가 옵니다']];
function scGrade(tot,need4){
  var r=need4?tot/need4:0, g=GRADES[GRADES.length-1];
  for(var i=0;i<GRADE_CUTS.length;i++){if(r>=GRADE_CUTS[i]){g=GRADES[i];break;}}
  return {k:g[0],label:g[1],color:g[2],desc:g[3],ratio:r};
}
```

`runningShortage`를 분해값 객체 반환으로 교체 (기존 함수 전체 대체):

```js
function runningShortage(done,sched,demol,refq,curQ,horizon){
  horizon=horizon||16; var I=0, lo=-DEFICIT_CAP*refq;
  for(var i=ANCHOR;i<=curQ;i++){ var qk=_qkey(i); I=Math.max(lo, I+((done[qk])||0)-((demol[qk])||0)-refq); }
  var demandSum=0, supplyWeighted=0;
  for(var k=1;k<=horizon;k++){ var w=_conf(k); if(w<=0)break; demandSum+=refq; supplyWeighted+=w*((sched[_qkey(curQ+k)])||0); }
  /* 분해값 포함 반환 — Python running_shortage(full=True) 미러. tot==demand-supplyw-inow */
  return {tot:(demandSum-supplyWeighted)-I, inow:I, demand:demandSum, supplyw:supplyWeighted};
}
```

`scCalc()`의 호출부 `const tot=invPath?runningShortage(...):tot_fallback;`를:

```js
    const _rs=invPath?runningShortage(zdone,zsched,zdemol,refq*share,curQ):null;
    const tot=_rs?_rs.tot:tot_fallback;
    const need4=refq*share*16;
```

로 바꾸고, 반환 객체(`return {z:z.z,...}`)에 `,need4:need4,inow:(_rs?_rs.inow:0),fsupw:(_rs?_rs.supplyw:0),gr:scGrade(tot,need4)`를 추가.

- [x] **Step 2: check_dual_calc 확장** — `tools/check_dual_calc.py`:

grab 목록에 (rsh 줄 위에) 추가:

```python
    sgrade = grab(r'var GRADE_CUTS=.*?\nfunction scGrade\([^)]*\)\{.*?\n\}', 'scGrade')
```

`src` 템플릿의 `%s` 나열에 `sgrade` 추가(qkey·conf와 같은 방식으로 조립부 `% (...)`에 삽입), JS 출력행을:

```js
const out = scCalc().map(z => ({z: z.z, dA: z.dA, dB: z.dB, dC: z.dC, tot: z.tot, need4: z.need4, gk: z.gr.k}));
```

로 교체. Python 대조 루프의 키 목록을 `('dA','dB','dC','tot','need4')`로 확장하고, 그 아래 등급 대조를 추가:

```python
        if M.grade(py[z]['tot'], py[z]['need4'])['k'] != js[z]['gk']:
            bad.append((z, 'grade', py[z]['gr']['k'], js[z]['gk']))
```

(주의: `py[z]['gr']['k']`와 `js[z]['gk']` 비교 — 숫자 비교 아님, TOL 미적용.)

- [x] **Step 3: 미러 검증**

Run: `PYTHONIOENCODING=utf-8 python tools/check_dual_calc.py`
Expected: `✅ 두 구현이 모든 생활권에서 일치한다` (need4·grade 포함)

- [x] **Step 4: 커밋**

```bash
git add index.html tools/check_dual_calc.py
git commit -m "scGrade/runningShortage 분해값 JS 미러 + check_dual_calc 등급 대조"
```

---

### Task 3: 존 페이지 6섹션 재구성

**Files:**
- Modify: `tools/make_zone_pages.py` — `build_page()` (428행~) 및 히어로/섹션 HTML 조립부, CSS 블록(파일 상단 스타일 문자열)

**Interfaces:**
- Consumes: Task 1의 `r['gr']`, `r['need4']`, `r['inow']`, `r['fsupw']`
- Produces: 새 페이지 구조(아래 순서). 기존 조각 재사용 — `qchart_html`(분기 차트), 단지 목록 테이블, `sublist`(다른 생활권), 방법론 폴드

- [x] **Step 1: 히어로 교체** — `build_page()` 안에서 `tname, tcol = tier(r['tot'])` 대신 `gr = r['gr']`를 쓰고, 히어로 HTML을 다음 구조로 교체:

```python
    gr = r['gr']
    hero_html = (
        '<span class="zg-badge" style="background:%s1a;color:%s">%s</span>\n'
        '<h1>%s, %s</h1>\n'
        '<p class="zg-cap">공급 기준 · 가격 예측 아님 · %s 데이터 · %s</p>\n'
        '<button class="zg-save" onclick="agongSaveZone()">내 지역으로 저장</button>\n'
        % (gr['color'], gr['color'], gr['label'], nm, gr['desc'], prd, ranktxt))
```

(`%s1a`는 색상 hex 뒤 alpha `1a`≈10% 배경. 기존 히어로의 `head_line`/`disp` 큰 숫자는 ②로 이동.)

- [x] **Step 2: 근거 3줄 섹션** — 게이지 섹션(`필요한 집 vs 들어올 집`)을 다음으로 교체. **세 줄의 합이 히어로 순부족과 일치**하도록 `need4·fsupw·inow`만 사용:

```python
    backlog = -r['inow']          # 양수면 '밀린 것', 음수면 '쌓인 재고'
    b_lab, b_sub = ('그동안 밀린 것', '2010년부터 못 지은 만큼 · 최대 4년치') if backlog >= 0 \
              else ('그동안 쌓인 것', '2010년부터 남은 만큼 · 재고')
    why_html = (
        '<section><div class="wrap"><h2>왜 이 판정인가</h2>'
        '<div class="why3">'
        '<div class="w-row"><span class="w-lab">필요한 집<i>%s 세대의 %d%% = %s 몫 · 4년치 · 추정</i></span><b>%s</b></div>'
        '<div class="w-row"><span class="w-lab">%s<i>%s · 실측</i></span><b>%s%s</b></div>'
        '<div class="w-row"><span class="w-lab">들어올 집<i>준공예정 실측 · 먼 미래는 낮춰 반영</i></span><b>−%s</b></div>'
        '<div class="w-sum" style="color:%s">순부족 %s세대 = 필요 %s 밀림 − 들어올 것</div>'
        '</div>'
        '<p class="note">부족은 재고처럼 쌓입니다 — 몇 해 모자란 지역은 한 해 물량이 몰려도 메워지지 않습니다.</p>'
        '</div></section>' % (
            ps, round(r['share'] * 100), nm, num(r['need4']),
            b_lab, b_sub, ('+' if backlog >= 0 else '−'), num(abs(backlog)),
            num(r['fsupw']),
            gr['color'], num(r['tot']), ('+' if backlog >= 0 else '−')))
```

(정합 검증: `need4 + backlog − fsupw == tot`이 Task 1 테스트로 보장됨. 여유 존은 순부족이 음수 — `num()` 대신 `signed()` 표기로 "N세대 여유" 문구 분기: `r['tot'] < 0`이면 요약줄을 `'여유 %s세대' % num(-r['tot'])`로.)

- [x] **Step 3: 섹션 재배열** — 페이지 조립부에서 순서를 다음으로 고정:

1. 판정 히어로 (Step 1)
2. 왜 이 판정인가 (Step 2)
3. 언제 들어오나 — 기존 `qchart_html` 재사용, 제목만 "언제 들어오나"로. 최대 분기를 찾아 `qs`에서 `max(byq[q])`인 막대에 강조 클래스 부여, 아래 한 줄: 부족 존(`r['tot']>0`)이면 `'가장 몰리는 분기는 %s — 그래도 필요량에는 못 미칩니다'`, 여유 존이면 `'입주가 가장 몰리는 %s 전후가 세입자·매수자에게 유리합니다'`
4. 어느 단지가 들어오나 — 기존 '앞으로/최근' 두 목록을 `<details>` 하나로 감싸 기본 접힘: `<details class="z-units"><summary>단지별로 보기 (앞으로 N곳 · 최근 N곳)</summary>` + 기존 두 테이블 그대로
5. 이 숫자의 한계 — 신설 (아래 카피 그대로) + 기존 `breakdown_sec_html`/`calc_detail_html`(방법론)을 이 섹션 안 `<details>`로 흡수:

```python
    limits_html = (
        '<section><div class="wrap"><h2>이 숫자의 한계</h2>'
        '<p class="note">가격을 맞히는 지표가 아닙니다. 2010년 이후 44개 생활권으로 직접 확인한 결과, '
        '금리가 크게 움직인 시기에는 공급이 가격에 준 영향이 거의 보이지 않았습니다. '
        '금리가 잔잔했던 시기에는 공급이 적었던 곳이 이후 2년간 평균 2%p 남짓 더 올랐을 뿐입니다. '
        '이 페이지는 <b>이 동네 공급 사정</b>으로만 읽어주세요.</p>'
        '%s</div></section>' % methodology_details_html)
```

6. 주변과 비교하면 — 기존 `sublist`/'다른 생활권'을 미니 카드로: 같은 `ps`(시도) 존들을 `allrows`에서 골라 최대 4곳, 각 카드에 등급 배지+순부족:

```python
    near = [x for x in allrows if x['ps'] == ps and x['z']['z'] != nm][:4]
    near_html = ('<section><div class="wrap"><h2>주변과 비교하면</h2><div class="near">' +
                 ''.join('<a class="n-card" href="/zone/%s/"><b>%s</b>'
                         '<span class="n-g" style="color:%s">%s</span><i>%s</i></a>'
                         % (x['z']['z'], x['z']['z'], x['gr']['color'], x['gr']['label'],
                            signed(x['tot']))
                         for x in near) + '</div></div></section>')
```

- [x] **Step 4: 저장 CTA 스크립트** — 각 존 페이지 하단 스크립트에 추가 (빌드 타임에 값 주입):

```python
    save_js = (
        '<script>function agongSaveZone(){try{'
        'localStorage.setItem("agong_myzone",JSON.stringify({z:%s,savedAt:%s,'
        'last:{tot:%d,rank:%d,grade:%s,seen:%s}}));'
        'var b=document.querySelector(".zg-save");if(b){b.textContent="저장됨 \\u2713 홈에서 확인";b.onclick=function(){location.href="/";};}'
        '}catch(e){}}</script>'
        % (json.dumps(nm, ensure_ascii=False), json.dumps(str(today)),
           round(r['tot']), rank_no, json.dumps(gr['label'], ensure_ascii=False),
           json.dumps(str(today))))
```

(`rank_no`는 `ranktxt` 계산에서 이미 구한 순위 정수를 변수로 보존해 사용. 수도권 합계 페이지(`subs` 존재)는 저장 버튼을 렌더하지 않는다 — 개별 생활권만 저장 대상.)

- [x] **Step 5: CSS 추가** — `make_zone_pages.py` 상단 스타일 문자열에:

```css
.zg-badge{display:inline-block;padding:5px 12px;font-weight:700;font-size:14px;border-radius:2px}
.zg-cap{color:var(--muted);font-size:12px;margin:6px 0 0}
.zg-save{margin-top:12px;padding:9px 18px;border:1px solid var(--line);background:#fff;cursor:pointer;font-weight:600}
.why3 .w-row{display:flex;justify-content:space-between;align-items:baseline;padding:9px 0;border-bottom:1px solid var(--line)}
.why3 .w-lab i{display:block;font-style:normal;color:var(--muted);font-size:11.5px}
.why3 .w-sum{padding:11px 0 0;font-weight:700}
.near{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
.n-card{border:1px solid var(--line);padding:10px 12px;display:block}
.n-card .n-g{display:block;font-size:12px;font-weight:700;margin-top:2px}
.n-card i{font-style:normal;color:var(--muted);font-size:12px}
.q-col.q-max .q-bar{outline:2px solid currentColor}
```

- [x] **Step 6: 재생성 + 육안 확인**

Run: `PYTHONIOENCODING=utf-8 python tools/make_zone_pages.py`
Expected: `zone pages: 45개 + 허브 1개 생성`. 이어서 `zone/서울권/index.html`을 열어(브라우저 프리뷰) ①~⑥ 순서, 근거 3줄 합계=히어로 숫자, 저장 버튼 동작(localStorage 기록) 확인. 여유 존(`zone/평택권/`)도 열어 "여유" 문구 분기 확인.

- [x] **Step 7: 테스트 + 커밋**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tools/tests/ -q` → 전체 PASS

```bash
git add tools/make_zone_pages.py zone/ sitemap.xml
git commit -m "존 페이지 6섹션 재구성 — 등급 히어로·근거 3줄·타임라인·접힘 단지·한계·주변 비교"
```

---

### Task 4: 홈 재구성 — 등급 그룹 순위 + 섹션 재배열

**Files:**
- Modify: `index.html` — 홈 섹션 HTML(157-206행 부근), `renderScoreSec()`(2384행~), `app.css`(.sc-tier 부근 713행~)

**Interfaces:**
- Consumes: Task 2의 `scCalc()` row `gr·need4`, `scGrade()`
- Produces: 등급 그룹 헤더가 있는 순위 리스트. `window.__SCZ`(zones 배열) 유지 — Task 5가 사용

- [x] **Step 1: 순위 리스트를 등급 그룹으로** — `renderScoreSec()`의 `units` 정렬 뒤, 렌더를 그룹 단위로 교체:

```js
  // 집계 유닛(수도권 1행 포함)에도 등급 — 합산 tot/need4로 판정
  units.forEach(u=>{u.need4=u.zones.reduce((s,z)=>s+(z.need4||0),0);u.gr=scGrade(u.tot,u.need4);});
  const order=['g4','g3','g2','g1','g0'];
  document.getElementById('score-wrap').innerHTML=order.map(gk=>{
    const list=units.filter(u=>u.gr.k===gk);
    if(!list.length)return '';
    const g=list[0].gr;
    return '<div class="sc-ghead" style="color:'+g.color+'">'+g.label+' <i>'+list.length+'곳</i></div>'
      +list.map(u=>{ /* 기존 행 렌더 코드 그대로, 단 sc-tier 칩을 등급 칩으로 */
        // ... 기존 bar/flag 코드 유지 ...
        return '<a class="sc-row" href="/zone/'+encodeURIComponent(u.name)+'/">' /* 기존과 동일 */
          +'<span class="sc-tier '+u.gr.k+'">'+u.gr.label+'</span><span class="sc-go">›</span></a>';
      }).join('');
  }).join('');
```

(기존 행 렌더 코드는 그대로 두고 `scTier(u.tot)` 참조만 `u.gr`로 바꾼다. `scTier` 함수 자체는 삭제 — 다른 참조가 없음을 `grep scTier`로 확인 후.)

- [x] **Step 2: 등급 칩 CSS** — `app.css`의 `.sc-tier.t4` 블록들 아래에 추가(기존 t1~t4 클래스는 유지해도 무해하나 참조가 사라지면 함께 삭제):

```css
.sc-tier.g4{background:#fdecea;color:#a93226}
.sc-tier.g3{background:#fbeee9;color:#c0392b}
.sc-tier.g2{background:#faf3e7;color:#b9770e}
.sc-tier.g1{background:#edf0ee;color:#5e6f74}
.sc-tier.g0{background:#e9f0f7;color:#1a5276}
.sc-ghead{font-weight:700;font-size:13px;margin:14px 0 4px;padding-bottom:3px;border-bottom:2px solid currentColor}
.sc-ghead i{font-style:normal;font-weight:400;color:var(--muted);font-size:11.5px}
```

- [x] **Step 3: 섹션 카피·순서 정리** — `index.html` 홈 HTML에서:

1. `#sec-score`의 `<h2>`를 `전국 한눈에 — 어디가 모자라고 어디가 남나`로 교체
2. `sc-how` 폴드 본문(구 dA/dB/dC 설명 — 낡음)을 교체:

```html
아파트는 짓는 데 3~4년 걸려, 지금 공사 중인 물량으로 4년 뒤까지 내다볼 수 있습니다.
행정구역이 아니라 실제 생활권 단위로, <b>필요한 집</b>(세대수 기준 추정)과
<b>그동안 밀린 것 + 들어올 집</b>(국토부 건축HUB 단지별 실측, 멸실 차감)을 견줘
세대수로 계산합니다. 등급은 필요량 대비 부족 비율의 절대 구간입니다.
공급 기준이며 가격 예측이 아닙니다 — 금리가 크게 움직이면 공급 신호는 가격에 묻힙니다.
```

3. 섹션 순서를 퀴즈(172행)와 주간지도(183행) 블록 맞바꿈 → 최종: score → 주간 → 퀴즈 → 사이클+신뢰
4. 사이클(190-196행)과 신뢰(197-206행) 섹션을 하나의 `<section class="home-sec hs-alt">`로 합치고 각각 h3로 강등, 본문 각 1문장으로 압축

- [x] **Step 4: 브라우저 확인 + 커밋**

프리뷰(`agongmap` 서버)에서: 그룹 헤더 5개(빈 등급 생략) 표시, 각 행 등급 칩, 콘솔 에러 0 확인.

```bash
git add index.html app.css
git commit -m "홈 순위 등급 그룹핑 + 산출 방법 카피 현행화 + 섹션 재배열"
```

---

### Task 5: 지역 선택기 + 내 지역 카드 + localStorage

**Files:**
- Modify: `index.html` — 히어로 아래 새 섹션 + JS (renderScoreSec 근처), `app.css`

**Interfaces:**
- Consumes: `window.__SCZ`(scCalc rows — Task 4가 유지), `scGrade`, 존 페이지가 쓰는 같은 키 `agong_myzone`(Task 3 Step 4와 스키마 동일)
- Produces: `renderMyZone()` — 로드 시 실행. 첫 방문=선택기, 재방문=내 지역 카드

- [x] **Step 1: HTML 골격** — 히어로 `</header>` 바로 다음, `#sec-score` 앞에 삽입:

```html
<section class="home-sec" id="sec-myzone"><div class="wrap">
  <h2 id="mz-title">우리 동네 아파트, 앞으로 모자랄까 남을까</h2>
  <div id="mz-body"></div>
</div></section>
```

- [x] **Step 2: JS** — `renderScoreSec()` 정의 아래에 추가:

```js
/* ── 내 지역 (localStorage: agong_myzone — 존 페이지 저장 버튼과 스키마 공유) ── */
const MYZONE_KEY='agong_myzone';
function mzGet(){try{const d=JSON.parse(localStorage.getItem(MYZONE_KEY));return (d&&d.z)?d:null;}catch(e){return null;}}
function mzSet(d){try{localStorage.setItem(MYZONE_KEY,JSON.stringify(d));}catch(e){}}
function mzClear(){try{localStorage.removeItem(MYZONE_KEY);}catch(e){}}
function renderMyZone(){
  const body=document.getElementById('mz-body'),title=document.getElementById('mz-title');
  const zones=window.__SCZ;
  if(!body||!zones||!zones.length){const s=document.getElementById('sec-myzone');if(s)s.style.display='none';return;}
  const saved=mzGet();
  const row=saved?zones.find(z=>z.z===saved.z):null;
  if(saved&&!row){mzClear();}          // 생활권 개편 등으로 사라진 존 → 첫 방문 상태
  if(row){
    const rank=zones.slice().sort((a,b)=>b.tot-a.tot).findIndex(z=>z.z===row.z)+1;
    const g=row.gr;
    let diff='';
    if(saved.last&&typeof saved.last.tot==='number'&&saved.last.seen!==undefined){
      const d=Math.round(row.tot-saved.last.tot);
      if(d!==0)diff='<span class="mz-diff" style="color:'+(d>0?'#a93226':'#1a5276')+'">지난 방문보다 '
        +(d>0?'부족 +':'부족 −')+Math.abs(d).toLocaleString()+'세대 '+(d>0?'▲':'▼')+'</span>';
      else diff='<span class="mz-diff" style="color:var(--muted)">지난 방문과 같음</span>';
    }
    title.textContent='내 지역';
    body.innerHTML='<div class="mz-card">'
      +'<div class="mz-head"><b>'+row.z+'</b>'
      +'<span class="sc-tier '+g.k+'">'+g.label+'</span></div>'
      +'<p class="mz-desc">'+g.desc+'</p>'
      +'<p class="mz-meta">순위 '+rank+'위 / '+zones.length+'곳 · 공급 기준 · 가격 예측 아님 '+diff+'</p>'
      +'<div class="mz-actions"><a class="home-cta" href="/zone/'+encodeURIComponent(row.z)+'/">자세히 보기</a>'
      +'<button class="mz-change" onclick="mzClear();renderMyZone();track(\'myzone\',{a:\'change\'})">지역 바꾸기</button></div>'
      +'</div>';
    mzSet({z:row.z,savedAt:saved.savedAt||new Date().toISOString().slice(0,10),
           last:{tot:Math.round(row.tot),rank:rank,grade:g.label,seen:new Date().toISOString().slice(0,10)}});
    return;
  }
  // 첫 방문: 시도 → 생활권 2단 선택기 + 전국 요약 한 줄
  const lack=zones.filter(z=>z.gr.k==='g4'||z.gr.k==='g3').length;
  const byps={};zones.forEach(z=>{(byps[z.psido]=byps[z.psido]||[]).push(z);});
  const sidos=Object.keys(byps);
  body.innerHTML='<p class="mz-sum">지금 전국 '+zones.length+'곳 중 <b>'+lack+'곳이 공급 부족</b>입니다. 우리 동네부터 확인해 보세요.</p>'
    +'<div class="mz-sido">'+sidos.map(s=>'<button class="mz-chip" onclick="mzPick(this,\''+s+'\')">'+s+'</button>').join('')+'</div>'
    +'<div class="mz-zones" id="mz-zones"></div>';
}
function mzPick(btn,ps){
  document.querySelectorAll('.mz-sido .mz-chip').forEach(b=>b.classList.toggle('on',b===btn));
  const zones=(window.__SCZ||[]).filter(z=>z.psido===ps);
  document.getElementById('mz-zones').innerHTML=zones.map(z=>
    '<button class="mz-chip zone" onclick="mzSave(\''+z.z+'\')">'+z.z+' <span class="sc-tier '+z.gr.k+'">'+z.gr.label+'</span></button>').join('');
  track('myzone',{a:'sido',v:ps});
}
function mzSave(nm){
  const zones=window.__SCZ||[],row=zones.find(z=>z.z===nm);
  if(!row)return;
  const rank=zones.slice().sort((a,b)=>b.tot-a.tot).findIndex(z=>z.z===nm)+1;
  mzSet({z:nm,savedAt:new Date().toISOString().slice(0,10),
         last:{tot:Math.round(row.tot),rank:rank,grade:row.gr.label,seen:new Date().toISOString().slice(0,10)}});
  renderMyZone();track('myzone',{a:'save',v:nm});
}
```

그리고 초기 라우팅 블록의 `renderScoreSec();` 다음 줄에 `renderMyZone();` 추가.

주의: 첫 저장 직후 `renderMyZone()` 재호출 시 `saved.last.tot`이 방금 값이라 diff가 "지난 방문과 같음"으로 뜬다 — 첫 저장에서는 `diff=''`가 되도록 `mzSave`에서 세션 플래그(`window.__MZ_JUST=1`)를 세우고 카드 렌더에서 플래그 있으면 diff 생략, 렌더 후 플래그 해제.

- [x] **Step 3: CSS** — `app.css`에:

```css
.mz-card{border:1px solid var(--line);padding:16px 18px}
.mz-head{display:flex;align-items:center;gap:10px;font-size:19px}
.mz-desc{margin:6px 0 2px;font-weight:600}
.mz-meta{color:var(--muted);font-size:12.5px;margin:0}
.mz-diff{font-weight:700;margin-left:6px}
.mz-actions{display:flex;gap:10px;margin-top:12px;align-items:center}
.mz-change{background:none;border:0;color:var(--muted);text-decoration:underline;cursor:pointer}
.mz-sum{margin:0 0 10px}
.mz-sido,.mz-zones{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
.mz-chip{border:1px solid var(--line);background:#fff;padding:7px 12px;cursor:pointer;font-size:13.5px}
.mz-chip.on{border-color:#1a5276;color:#1a5276;font-weight:700}
.mz-chip.zone{display:inline-flex;align-items:center;gap:6px}
```

- [x] **Step 4: 브라우저 확인 (두 상태)**

프리뷰에서: (a) localStorage 비운 뒤 → 선택기 표시 → 시도 클릭 → 존 클릭 → 카드로 전환(diff 없음) 확인. (b) 콘솔에서 `localStorage.setItem('agong_myzone', JSON.stringify({z:'서울권',savedAt:'2026-07-24',last:{tot:400000,rank:1,grade:'매우 부족',seen:'2026-07-24'}}))` 주입 후 새로고침 → "지난 방문보다 부족 +N ▲" 표시 확인. (c) 존재하지 않는 존(`z:'없는권'`) 주입 → 선택기로 폴백 확인. 콘솔 에러 0.

- [x] **Step 5: 커밋**

```bash
git add index.html app.css
git commit -m "지역 선택기 + 내 지역 카드 + localStorage 재방문 변화 표시"
```

---

### Task 6: 캐시 버전 + 최종 통합 검증

**Files:**
- Modify: `sw.js` (6행 VERSION)

**Interfaces:**
- Consumes: Task 1~5 전부

- [x] **Step 1: sw.js 버전**

```js
const VERSION = 'v39'; // 홈·존 UX 재기획 — 등급 판정·내 지역 카드·존 6섹션
```

- [x] **Step 2: 전체 검증 시퀀스**

```bash
PYTHONIOENCODING=utf-8 python -m pytest tools/tests/ -q          # 전체 PASS
PYTHONIOENCODING=utf-8 python tools/check_dual_calc.py           # 값+need4+등급 44곳 일치
PYTHONIOENCODING=utf-8 python tools/make_zone_pages.py           # 45개 재생성
PYTHONIOENCODING=utf-8 python tools/split_data.py                # data-core.js 동기화
```

브라우저: 홈 첫 방문/재방문 2상태, 존 페이지 부족 존(서울권)·여유 존(평택권) 각 1개, 모바일 뷰포트(375px)로 선택기·카드·근거 3줄 줄바꿈 확인, 콘솔 에러 0.

- [x] **Step 3: 커밋**

```bash
git add -A
git commit -m "홈·존 UX 재기획 통합 — sw.js v39, 존 페이지 재생성"
```

- [x] **Step 4: 스펙 대비 최종 점검** — 스펙의 6개 섹션 각각에 대응 구현이 있는지 확인: 등급 규칙(Task 1·2) / 홈 첫·재방문(Task 4·5) / 존 6섹션(Task 3) / localStorage 스키마(Task 3 Step 4 = Task 5 Step 2 동일 키·형태) / 카피 원칙(Task 3·4 본문) / 검증(Task 6). 미충족 발견 시 해당 태스크로 돌아가 보완 후 재검증.
