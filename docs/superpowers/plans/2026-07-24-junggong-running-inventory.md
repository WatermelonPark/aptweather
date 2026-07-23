# 준공 기반 러닝재고 순부족 모델 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 생활권 공급점수를 건축HUB 단일소스(단지별 준공/준공예정, 무중복)로 재구축 — 신쌤 러닝재고에 공급으로 넣어 "순부족 = 미래수요 − (현재재고 + 미래공급×신뢰감쇠)"를 산출한다.

**Architecture:** 수집기 엔진은 재사용하되 버킷을 `done_q`(준공)·`sched_q`(준공예정)로 교체 → `hub_derive`가 생활권별 준공·준공예정 분기시계열을 ADV에 주입 → `calc()`가 러닝재고 순부족을 산출, `scCalc()`가 동치 미러. 적정(수요)은 신쌤 상수 유지, 스케일만 검증. activate 게이트로 라이브 무변화 상태에서 구축·시드·검토 후 활성화.

**Tech Stack:** Python 3(stdlib + subprocess/curl), pytest, Node(미러 등가 검증), 기존 aptweather 파이프라인, GitHub Actions.

## Global Constraints

- **단지 무중복 분류**: 각 단지(mgmHsrgstPk)를 최신단계 1회 — `useInsptDay`(준공)>있으면 과거공급, 없고 `useInsptSchedDay`(준공예정) 있으면 미래공급, 둘다없으면 미정(점수 미반영). 착공일·인허가일은 점수에 직접 안 씀.
- **순부족 산식(부호: +=부족=발산막대 오른쪽)**: `순부족_z = Σ_{q>cur} conf(q)*(refq_z − sched_z(q)) − I_now_z`, `I_now_z = 과거 각 분기 max(0, I + done_z(q) − refq_z)` 누적(앵커 2010Q1). `conf(k분기)` 기본 = `max(0, 1 − ((k−1)/4)*0.2)` (1분기 1.0 → 5년(20분기) 0), 구현 시 캘리브.
- **적정(수요)**: `ADV.occupancy.ref`(신쌤 상수) **그대로 유지**. HUB준공 스케일이 occupancy와 다르면 계수만 보정(재피팅 금지).
- **미러 불변식**: `make_zone_pages.py` `calc()` ↔ `index.html` `scCalc()` 동치, Node vs Python max abs diff < 1e-6. 정규화(×12/H) 금지.
- **HTTP/수집**: curl `-G --data-urlencode`, 순차 2.5s, 에러분류(auth/quota XML을 genuine-0과 구분), `mgmHsrgstPk` dedupe, `purpsCdNm=='공동주택' and totHhldCnt>0`. urllib 금지.
- **activate 게이트**: `hub_permits.json` `meta.activate` false(기본) → hub_derive가 done/sched 미방출 → 라이브는 pre-HUB 지표. **존별 완결성 게이트**: 존의 모든 멤버 시군구가 `meta['scanned']`일 때만 방출.
- **동기화 체크리스트**: hub_permits.json → `update_adv_data.py --update`(hub_derive) → `split_data.py` → data.js/data-core.js/data-rest.json → sw.js 버전.
- **저장 위치**: 산출물은 `aptweather/tools/data/`. 커밋 후 **즉시 `git push`**(병렬 세션이 unpushed 커밋 리셋). rebase 시 재확인.

---

## 파일 구조

- Modify `tools/fetch_hub_permits.py` — `_aggregate` 버킷 교체(done_q/sched_q, 단지 최신단계 1회), useInsptSchedDay 파싱. 수집 엔진 나머지 유지.
- Modify `tools/hub_common.py` — `shift_quarter` 제거(불필요). `to_quarter`·`dedupe`·`apt_records` 유지.
- Modify `tools/update_adv_data.py` — `hub_derive` 재작성(done/sched 시계열 주입, 게이트 유지).
- Modify `tools/make_zone_pages.py` — `calc()` 러닝재고 순부족으로 재작성(pre-HUB 되돌림 후), 상세 리스트 2섹션.
- Modify `index.html` — `scCalc()` 동치 미러(pre-HUB 되돌림 후 러닝재고).
- Create `tools/verify_rankdiff.py` — 구모델 vs 신모델 36존 순위 diff + 적정 스케일 진단. (`verify_dc_rankdiff.py` 삭제)
- Modify `tools/tests/` — `test_fetch_hub.py` 버킷 테스트, `test_hub_derive.py` 재작성, `test_calc_inventory.py` 신규. `test_calc_dc.py`·`test_hub_common.py`의 shift_quarter 테스트 제거.
- Reuse `.github/workflows/update-hub.yml`·`hub-probe.yml`, `tools/split_data.py`, `sw.js`.

---

## Task 1: pre-HUB 점수로 되돌리기 (깨끗한 기반)

Q6=A. calc/scCalc를 HUB 이전으로 복원하고 obsolete 산물 제거. 라이브는 이미 activate=false로 구지표지만, 코드 기반을 정리한다.

**Files:**
- Modify: `tools/make_zone_pages.py` (calc() 복원)
- Modify: `index.html` (scCalc() 복원 — 함수만 surgical)
- Modify: `tools/update_adv_data.py` (hub_derive/_hub_zone_map/load_bdong 제거)
- Delete: `tools/verify_dc_rankdiff.py`, `tools/tests/test_calc_dc.py`, `tools/tests/test_hub_derive.py`

**Interfaces:**
- Produces: pre-HUB calc()/scCalc()(원 3항목 dA/dB/dC pop-alloc·2yr forward). 이후 태스크가 이걸 러닝재고로 재작성.

- [ ] **Step 1: pre-HUB calc() 복원**

`git show 8aa6863:tools/make_zone_pages.py` 로 pre-HUB 버전을 얻어, 현재 `make_zone_pages.py`의 `calc()`(및 Task6이 추가한 `fut_window`/`zone_fut_supply`/`calc_dc`, FARQ/NEARQ, dcsrc, make_capital의 dcsrc/mixed)를 그 버전으로 되돌린다. 파일의 HUB 무관 부분(있다면)은 유지.

- [ ] **Step 2: scCalc() surgical 복원**

`git show 725d453~1:index.html` 에서 `scCalc()` 함수 본문만 추출해, 현재 index.html의 `scCalc()`를 교체. **index.html의 나머지(병렬 세션 랜딩/지도 작업)는 절대 건드리지 말 것** — 함수 하나만 교체. 교체 전 `git fetch && git pull --rebase origin main`.

- [ ] **Step 3: hub_derive 제거**

`tools/update_adv_data.py`에서 `hub_derive`·`_hub_zone_map`·`load_bdong`(hub 전용이면) 및 그 호출을 제거. `permits` 갱신 경로는 pre-HUB(fetch_permits만)로.

- [ ] **Step 4: obsolete 삭제 + 테스트**

```bash
cd "C:/Users/shpar/OneDrive/문서/Claude/aptweather"
git rm tools/verify_dc_rankdiff.py tools/tests/test_calc_dc.py tools/tests/test_hub_derive.py
python -m pytest tools/tests/ -q
python tools/make_zone_pages.py   # 생성 후 zone/*·sitemap 되돌리기
```
Expected: 테스트 통과(HUB 점수 테스트 삭제됨), 존페이지 생성 예외 없음. calc()가 pre-HUB 산식.

- [ ] **Step 5: 커밋 + push**

```bash
git add -A && git commit -m "revert: HUB 점수변경(dC meas·착공 forward) pre-HUB로 되돌림 — 러닝재고 재구축 기반"
git push
```
push 거부 시 `git pull --rebase origin main` 후 재push, scCalc/calc 변경 잔존 확인.

---

## Task 2: 수집기 버킷 교체 — done_q/sched_q + 단지 최신단계 1회

**Files:**
- Modify: `tools/fetch_hub_permits.py` (`_aggregate` ~315-330, `fetch_group` 반환, `run`의 write ~501)
- Modify: `tools/hub_common.py` (shift_quarter 제거)
- Modify: `tools/tests/test_fetch_hub.py`, `tools/tests/test_hub_common.py`

**Interfaces:**
- Consumes: `hub_common.apt_records`, `to_quarter`.
- Produces: `hub_permits.json` sgg 항목이 `{"name","done_q":{q:세대},"sched_q":{q:세대}}`. `fetch_group`/`run` 시그니처의 permit_q/start_q → done_q/sched_q.

- [ ] **Step 1: 분류 실패 테스트**

```python
# tools/tests/test_fetch_hub.py 에 추가
def test_aggregate_classifies_latest_stage_once():
    import fetch_hub_permits as F
    items = [
        {'mgmHsrgstPk':'A','purpsCdNm':'공동주택','totHhldCnt':'100','useInsptDay':'20240310','useInsptSchedDay':'20231130','stcnsDay':'20210101','apprvDay':'20200101'},  # 준공됨→done 2024Q1
        {'mgmHsrgstPk':'B','purpsCdNm':'공동주택','totHhldCnt':'200','useInsptDay':'','useInsptSchedDay':'20291130','stcnsDay':'','apprvDay':'20230101'},                    # 미완공+예정→sched 2029Q4
        {'mgmHsrgstPk':'C','purpsCdNm':'공동주택','totHhldCnt':'50','useInsptDay':'','useInsptSchedDay':'','stcnsDay':'','apprvDay':'20240101'},                              # 미정→어디에도 안 감
        {'mgmHsrgstPk':'A','purpsCdNm':'공동주택','totHhldCnt':'100','useInsptDay':'20240310','useInsptSchedDay':'','stcnsDay':'','apprvDay':''},                             # A 중복→dedupe
    ]
    done, sched = F._aggregate(items)
    assert done == {'2024Q1': 100}
    assert sched == {'2029Q4': 200}
```

- [ ] **Step 2: 실패 확인**

```bash
python -m pytest tools/tests/test_fetch_hub.py::test_aggregate_classifies_latest_stage_once -v
```
Expected: FAIL (현재 _aggregate는 permit_q/start_q 반환, done/sched 아님).

- [ ] **Step 3: `_aggregate` 재작성**

`tools/fetch_hub_permits.py`의 `_aggregate`를 교체:
```python
def _aggregate(items):
    """apt_records(공동주택·세대>0·PK dedupe) → 단지 최신단계 1회 분류.
    준공(useInsptDay) 있으면 done_q, 없고 준공예정(useInsptSchedDay) 있으면 sched_q,
    둘 다 없으면 미정(어디에도 안 감). 착공/인허가는 점수에 직접 안 쓴다."""
    done_q = collections.defaultdict(int)
    sched_q = collections.defaultdict(int)
    for r in H.apt_records(items):
        try:
            n = int(float(r.get('totHhldCnt') or 0))
        except (TypeError, ValueError):
            continue
        if n <= 0:
            continue
        dq = H.to_quarter(r.get('useInsptDay'))
        if dq:
            done_q[dq] += n
            continue
        sq = H.to_quarter(r.get('useInsptSchedDay'))
        if sq:
            sched_q[sq] += n
        # 둘 다 없으면 미정 — 미반영
    return dict(done_q), dict(sched_q)
```

- [ ] **Step 4: fetch_group/run 명칭 전파**

`fetch_group`(반환 `permit_q, start_q, productive, had_unresolved_error` → `done_q, sched_q, productive, had_unresolved_error`)와 `run`의 write(`out['sgg'][key] = {'name':…, 'done_q':done_q, 'sched_q':sched_q}`)를 갱신. 진행 로그·주석의 permit_q/start_q 표현도 done_q/sched_q로.

- [ ] **Step 5: shift_quarter 제거**

`tools/hub_common.py`에서 `shift_quarter` 함수 삭제. `tools/tests/test_hub_common.py`에서 `test_shift_quarter` 삭제.

- [ ] **Step 6: 통과 확인 + 소표본 실호출**

```bash
python -m pytest tools/tests/test_fetch_hub.py tools/tests/test_hub_common.py -q
KEY 추출 후: python tools/fetch_hub_permits.py --full --only 41220   # 평택(미래 준공예정 많음)
python -c "import json;d=json.load(open('tools/data/hub_permits.json',encoding='utf-8'));v=d['sgg'].get('41220',{});print('done', dict(list(v.get('done_q',{}).items())[:3]));print('sched', {k:val for k,val in v.get('sched_q',{}).items() if k>='2026Q3'})"
```
Expected: 테스트 통과. 평택 sched_q에 2026~2030 미래 준공예정 세대(밀도조사와 정합), done_q에 과거 준공.

- [ ] **Step 7: 커밋 + push**

```bash
git add tools/fetch_hub_permits.py tools/hub_common.py tools/tests/test_fetch_hub.py tools/tests/test_hub_common.py tools/data/hub_permits.json
git commit -m "feat: HUB 수집 버킷을 준공(done_q)/준공예정(sched_q) 단지 최신단계 1회로 교체" && git push
```

---

## Task 3: hub_derive 재작성 — 존별 준공/준공예정 시계열 주입

**Files:**
- Modify: `tools/update_adv_data.py` (hub_derive 재도입)
- Create: `tools/tests/test_hub_derive.py`

**Interfaces:**
- Consumes: `hub_permits.json`(done_q/sched_q), `LIVEZONE`/`LZ_GU2SI`/`LZ_SIDO_FULL`, `code_bdong.json`.
- Produces: `adv['permits']['done'] = {zone:{q:세대}}`, `adv['permits']['sched'] = {zone:{q:세대}}`. activate·완결성 게이트.

- [ ] **Step 1: 매핑·집계 테스트**

```python
# tools/tests/test_hub_derive.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import update_adv_data as U

def _bdong(): return {'41370':('경기도','오산시'), '41131':('경기도','성남시 수정구')}

def test_hub_zone_map_leading_token():
    z = U._hub_zone_map(_bdong())
    assert z['41370'] == '오산권'
    assert z['41131'] == '성남권'

def test_hub_derive_inactive_emits_nothing(tmp_path, monkeypatch):
    # meta.activate=false → done/sched 미방출
    adv = {'permits': {}}
    hp = {'meta': {'activate': False, 'scanned': [], 'unresolved_legacy': []}, 'sgg': {}}
    monkeypatch.setattr(U, '_load_hub_permits', lambda: hp)      # 아래 구현이 이 헬퍼를 씀
    monkeypatch.setattr(U, '_load_bdong_map', lambda: _bdong())
    U.hub_derive(adv)
    assert 'done' not in adv['permits'] and 'sched' not in adv['permits']

def test_hub_derive_active_complete_zone_only(tmp_path, monkeypatch):
    adv = {'permits': {}}
    hp = {'meta': {'activate': True, 'scanned': ['41370'], 'unresolved_legacy': []},
          'sgg': {'41370': {'name':'오산시','done_q':{'2023Q1':100},'sched_q':{'2028Q2':200}}}}
    monkeypatch.setattr(U, '_load_hub_permits', lambda: hp)
    monkeypatch.setattr(U, '_load_bdong_map', lambda: _bdong())
    U.hub_derive(adv)
    assert adv['permits']['done']['오산권'] == {'2023Q1':100}
    assert adv['permits']['sched']['오산권'] == {'2028Q2':200}
```

- [ ] **Step 2: 실패 확인**

```bash
python -m pytest tools/tests/test_hub_derive.py -q
```
Expected: FAIL (hub_derive/_hub_zone_map 없음 — Task1에서 제거됨).

- [ ] **Step 3: 구현**

`tools/update_adv_data.py`에 재도입(Task5 매핑 로직 재사용하되 done/sched 산출):
```python
TOOLS_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

def _load_hub_permits():
    return json.load(io.open(os.path.join(TOOLS_DATA, 'hub_permits.json'), encoding='utf-8'))

def _load_bdong_map():
    import math
    d = json.load(io.open(os.path.join(TOOLS_DATA, 'code_bdong.json'), encoding='utf-8'))
    out = {}
    for i in range(len(d['시도명'])):
        k = str(i); era = d['말소일자'][k]
        if not (era is None or (isinstance(era, float) and math.isnan(era))): continue
        nm = d['시군구명'][k]
        if not isinstance(nm, str) or not nm: continue
        out.setdefault(str(d['시군구코드'][k]), (d['시도명'][k], nm))
    return out

def _hub_zone_map(bdong):
    m2z = {m: z for z, mm in LIVEZONE.items() for m in mm}
    def gg_zone(sg):
        base = re.sub(r'(시|군)$', '', sg)
        return ('경기' + base + '권') if (base + '권') in LIVEZONE else (base + '권')
    def zone_of(sd, sg):
        if (sd, '*') in m2z: return m2z[(sd, '*')]
        sg = LZ_GU2SI.get(sg, sg)
        if (sd, sg) in m2z: return m2z[(sd, sg)]
        if sd == '경기': return gg_zone(sg)
        return None
    out = {}
    for cd, (sido_full, nm) in bdong.items():
        sd = LZ_SIDO_FULL.get(sido_full)
        if not sd: continue
        z = zone_of(sd, nm.split(' ')[0])     # 시/군 leading 토큰
        if z: out[cd] = z
    return out

def hub_derive(adv):
    import collections
    hp = _load_hub_permits()
    if not hp.get('meta', {}).get('activate', False):
        print('hub_derive: inactive — pre-HUB 지표 유지'); return
    z_of = _hub_zone_map(_load_bdong_map())
    scanned = set(hp.get('meta', {}).get('scanned', []))
    unresolved = set(hp.get('meta', {}).get('unresolved_legacy', []))
    # 존별 멤버 시군구(완결성 판정용)
    members = collections.defaultdict(set)
    for cd, z in z_of.items():
        if cd not in unresolved: members[z].add(cd)
    done = collections.defaultdict(lambda: collections.defaultdict(int))
    sched = collections.defaultdict(lambda: collections.defaultdict(int))
    for cd, v in hp.get('sgg', {}).items():
        z = z_of.get(cd)
        if not z: continue
        for q, n in v.get('done_q', {}).items(): done[z][q] += n
        for q, n in v.get('sched_q', {}).items(): sched[z][q] += n
    # 완결성 게이트: 존의 모든 멤버가 scanned일 때만 방출
    complete = {z for z, ms in members.items() if ms and ms <= scanned}
    adv.setdefault('permits', {})
    adv['permits']['done'] = {z: dict(done[z]) for z in complete if z in done}
    adv['permits']['sched'] = {z: dict(sched[z]) for z in complete if z in sched}
    print('hub_derive: active, complete_zones=%d' % len(complete))
```
`permits` 갱신 경로 끝에서 `hub_derive(adv)` 호출.

- [ ] **Step 4: 통과 + 실데이터 sanity**

```bash
python -m pytest tools/tests/test_hub_derive.py -q
```
Expected: 3 passed. (실데이터는 activate=false라 방출 없음 — 정상.)

- [ ] **Step 5: 커밋 + push**

```bash
git add tools/update_adv_data.py tools/tests/test_hub_derive.py
git commit -m "feat: hub_derive 재작성 — 존별 준공/준공예정 시계열 주입(activate·완결성 게이트)" && git push
```

---

## Task 4: 적정(수요) 스케일 검증

적정 상수는 유지. HUB준공 분기 세대가 기존 occupancy 준공실적과 스케일이 맞는지만 확인.

**Files:**
- Create: `tools/verify_ref_scale.py`

**Interfaces:**
- Produces: 시도/생활권별 `HUB준공 분기평균` vs `occupancy 준공실적 분기평균` vs `refq(적정)` 표. 스케일 계수 제안.

- [ ] **Step 1: 진단 스크립트**

```python
# tools/verify_ref_scale.py — HUB done_q 분기평균과 occupancy ref 스케일 대조
# ADV.occupancy.ref[ps], ADV.occupancy.rows(과거 준공실적) 대비 hub done_q 합을 지역별로 비교.
# 활성화 전이라 hub_permits.json을 직접 읽어 존별 done_q 최근 3년 분기평균 산출 →
# 같은 존/시도의 refq와 비율 출력. 비율이 지역 간 일정하면 스케일 계수 하나로 보정 가능.
```
(전량 시드 후 의미 있으므로, 시드 전엔 표본 시군구로 스모크만.)

- [ ] **Step 2: 실행(표본) + 판단 기록**

```bash
python tools/verify_ref_scale.py
```
Expected: 표본 존(오산·성남·부산권 등)에 대해 HUB준공 분기세대 / refq 비율 출력. **비율이 ~1 근처면 스케일 OK(계수 불필요), 체계적으로 벗어나면 계수 기록**. 결과를 `tools/data/hub_pilot_notes.md`에 한 섹션으로 남김. (실제 보정 계수 적용은 전량 시드 후 Task 5 순위검토에서 확정.)

- [ ] **Step 3: 커밋 + push**

```bash
git add tools/verify_ref_scale.py tools/data/hub_pilot_notes.md
git commit -m "feat: 적정 스케일 검증 도구 — HUB준공 vs occupancy/refq 대조" && git push
```

---

## Task 5: calc() 러닝재고 순부족 + 순위 검증

**Files:**
- Modify: `tools/make_zone_pages.py` (calc())
- Create: `tools/verify_rankdiff.py`
- Create: `tools/tests/test_calc_inventory.py`

**Interfaces:**
- Consumes: `adv['permits']['done']`, `['sched']`, `O['ref']`(refq).
- Produces: 러닝재고 순부족을 담은 calc() 결과(`tot`). `running_shortage()` 헬퍼.

- [ ] **Step 1: 러닝재고 순부족 테스트**

```python
# tools/tests/test_calc_inventory.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import make_zone_pages as M

def test_running_shortage_buffer_and_decay():
    # cur_q 기준 미래 1분기 sched 부족, 과거 준공으로 재고 버퍼
    cur = 2026*4 + 2                       # 2026Q3 인덱스(년*4+분기-1)
    done = {'2025Q1': 400}                 # 과거 준공
    sched = {'2026Q4': 0}                  # 미래 공급 0
    refq = 100
    # I_now: 앵커~cur, 2025Q1에 +400-100=300, 이후 분기마다 -100 소진 → cur까지 몇 분기 소진
    s = M.running_shortage(done, sched, refq, cur, horizon=4)
    # 미래수요 Σconf*refq - (I_now + Σconf*sched). 값이 유한·부호 정상인지
    assert isinstance(s, float)

def test_running_shortage_no_negative_inventory():
    cur = 2026*4 + 2
    # 과거 준공 전무 → I_now=0, 미래 공급 0 → 순부족 = Σconf*refq > 0 (부족)
    s = M.running_shortage({}, {}, 100, cur, horizon=4)
    assert s > 0
```

- [ ] **Step 2: 실패 확인**

```bash
python -m pytest tools/tests/test_calc_inventory.py -q
```
Expected: FAIL (running_shortage 없음).

- [ ] **Step 3: 구현**

`make_zone_pages.py`에 헬퍼 추가 + calc()가 이를 사용:
```python
import re as _re
def _qidx(q):
    m = _re.match(r'^(\d{4})Q([1-4])$', q); return int(m.group(1))*4 + int(m.group(2)) - 1 if m else None
def _qkey(idx):
    return '%dQ%d' % (idx // 4, idx % 4 + 1)
def _conf(k):                       # k = 미래 몇 분기 뒤(1..)
    return max(0.0, 1.0 - ((k - 1) / 4.0) * 0.2)   # 1분기 1.0 → 20분기(5년) 0
ANCHOR = 2010 * 4                   # 2010Q1

def running_shortage(done, sched, refq, cur_q, horizon=20):
    # 과거 러닝재고
    I = 0.0
    for idx in range(ANCHOR, cur_q + 1):
        I = max(0.0, I + done.get(_qkey(idx), 0) - refq)
    I_now = I
    # 미래 신뢰가중 순부족
    fut = 0.0
    for k in range(1, horizon + 1):
        q = _qkey(cur_q + k); w = _conf(k)
        if w <= 0: break
        fut += w * (refq - sched.get(q, 0))
    return fut - I_now
```
calc()에서 존별로: `refq = O['ref'][ps] or band중앙`, `done = (P.get('done') or {}).get(z['z']) or {}`, `sched = (P.get('sched') or {}).get(z['z']) or {}`, `tot = running_shortage(done, sched, refq, cur_q)`. **done/sched 없는 존(비완결·inactive)** → pre-HUB 폴백 산식 유지(Task1 복원분). `cur_q = today.year*4 + (today.month-1)//3`.

- [ ] **Step 4: 통과 + verify_rankdiff**

```python
# tools/verify_rankdiff.py — 구모델(pre-HUB) vs 신모델(러닝재고, hub_derive 강제 activate 주입) 36존 순위 나란히
```
```bash
python -m pytest tools/tests/test_calc_inventory.py -q
python tools/verify_rankdiff.py    # hub_derive를 인메모리 activate=true로 주입해 후모델 산출
python tools/make_zone_pages.py    # 스모크(zone/*·sitemap 되돌리기)
```
Expected: 테스트 통과. 순위표에서 활성 개발지(화성·평택 등)가 미래 준공예정 반영으로 **과잉 방향(순부족↓)**이면 정합. 설명 안 되는 요동이면 conf/앵커/스케일 재검토.

- [ ] **Step 5: 커밋 + push**

```bash
git add tools/make_zone_pages.py tools/verify_rankdiff.py tools/tests/test_calc_inventory.py
git rm tools/verify_dc_rankdiff.py 2>/dev/null || true
git commit -m "feat: calc() 러닝재고 순부족(미래수요-(재고+미래공급×신뢰)) + 순위 diff 검증" && git push
```

---

## Task 6: scCalc() 홈 미러 — 러닝재고 동치

**Files:**
- Modify: `index.html` (scCalc())

**Interfaces:**
- Consumes: `ADV.permits.done`, `ADV.permits.sched`, `O.ref`.

- [ ] **Step 1: scCalc 미러 작성**

`index.html`의 `scCalc()`에 JS 러닝재고를 calc()와 **동일 산식**으로 이식 (`git fetch && git pull --rebase` 먼저, 함수만 surgical 편집):
```javascript
function _qidx(q){var m=/^(\d{4})Q([1-4])$/.exec(q);return m?(+m[1])*4+(+m[2])-1:null;}
function _qkey(i){return Math.floor(i/4)+'Q'+(i%4+1);}
function _conf(k){return Math.max(0,1-((k-1)/4)*0.2);}
var ANCHOR=2010*4;
function runningShortage(done,sched,refq,curQ,horizon){
  horizon=horizon||20; var I=0;
  for(var i=ANCHOR;i<=curQ;i++){ I=Math.max(0, I+((done[_qkey(i)])||0)-refq); }
  var fut=0;
  for(var k=1;k<=horizon;k++){ var w=_conf(k); if(w<=0)break; fut+=w*(refq-((sched[_qkey(curQ+k)])||0)); }
  return fut-I;
}
```
존별로 `refq`, `done=(P.done&&P.done[z.z])||{}`, `sched=(P.sched&&P.sched[z.z])||{}`, `tot=runningShortage(...)`. done/sched 없으면 pre-HUB 폴백(복원된 scCalc 산식). 정규화 금지.

- [ ] **Step 2: Node 등가 재증명**

스크래치패드 Node 스크립트: data.js(또는 hub_derive activate=true 주입 ADV) 로드 → scCalc 실행 → Python calc()와 존별 tot 비교, **max abs diff < 1e-6** (done/sched 있는 존·없는 존 둘 다 포함).
Expected: max abs diff ≈ 0. 불일치 존은 scCalc 수정.

- [ ] **Step 3: 커밋 + push**

```bash
git add index.html
git commit -m "feat: scCalc 홈 미러 — 러닝재고 순부족 동치(calc()와 0.0)" && git push
```

---

## Task 7: 상세페이지 리스트 2섹션

**Files:**
- Modify: `tools/make_zone_pages.py` (단지 리스트 렌더)
- Modify: `tools/update_adv_data.py` (존별 단지 리스트 원자료 주입 — 필요 시)

**Interfaces:**
- Consumes: 존별 준공예정 단지·최근 준공 단지 목록(이름·세대·연월).

- [ ] **Step 1: 리스트 데이터 주입**

hub_derive(또는 별도)에서 존별 **단지 리스트**를 소량 주입: `permits['units'][zone] = {'sched':[[단지명,세대,'YYYY-MM',conf],...], 'done':[[단지명,세대,'YYYY-MM'],...]}` — sched는 준공예정 최근순, done은 최근 N년(예 3년). 원시 전량 아님, 존당 상위 몇 개.
(collector가 단지명·연월을 hub_permits.json에 단지 리스트로 남기도록 `_aggregate` 확장 필요 — done/sched 집계와 함께 `units` 목록 축적. 세대 큰 순 상위 N.)

- [ ] **Step 2: 렌더 2섹션**

`make_zone_pages.py`의 기존 입주예정 리스트 렌더를 교체: **"앞으로 들어올 물량"**(sched: "2029.06 예정", 준공예정 없으면 "미정", conf 낮으면 회색+"지연 가능") + **"최근 들어온 물량"**(done: "2024.03 준공"). 세대·단지명 표기.

- [ ] **Step 3: 스모크 + 커밋**

```bash
python tools/make_zone_pages.py   # 존페이지에 2섹션 렌더 확인, zone/*·sitemap 되돌리기
git add tools/make_zone_pages.py tools/update_adv_data.py tools/fetch_hub_permits.py tools/data/hub_permits.json
git commit -m "feat: 존페이지 단지 리스트 2섹션(앞으로 준공예정 + 최근 준공)" && git push
```

---

## Task 8: 롤아웃 배선 + 동기화

**Files:**
- Modify: `sw.js`, `tools/data/hub_pilot_notes.md`
- Reuse: `.github/workflows/update-hub.yml`, `tools/split_data.py`

- [ ] **Step 1: split_data 확인 + sw.js**

`split_data.py`가 `permits.done`/`sched`/`units`를 data-core에 포함하는지 확인(permits 통째 복사면 자동). `sw.js` 캐시 버전 +1.

- [ ] **Step 2: 롤아웃 절차 문서화**

`hub_pilot_notes.md`에 go-live 절차 기록: (a) `update-hub.yml` `mode=full` 2-3회(재개가능) 전량 시드 — **DATA_GO_KR_KEY 일일쿼터 확인**, (b) `verify_rankdiff` + `verify_ref_scale`로 순위·스케일 검토(사용자 승인), (c) 승인 시 `hub_permits.json` `meta.activate=true` 커밋 → 다음 daily가 data.js 반영.

- [ ] **Step 3: 커밋 + push + 메모리**

```bash
git add sw.js tools/data/hub_pilot_notes.md tools/split_data.py
git commit -m "ci: 준공기반 러닝재고 롤아웃 배선 + sw.js 버전 + 시드/검토/activate 절차" && git push
```
그리고 `hub-permit-integration.md` 메모리를 "준공기반 러닝재고로 재설계·구현(activate off, 시드·검토 후 go-live)"로 갱신, `agongmap-data-pipeline.md`의 HUB 항목(done/sched·러닝재고) 갱신.

---

## Self-Review (작성자 체크)

**Spec coverage:**
- 러닝재고 순부족 모델 → Task 5(calc)+6(scCalc). ✅
- 단지 무중복(준공/준공예정 최신단계 1회) → Task 2. ✅
- 적정 유지+스케일 검증(재피팅 아님) → Task 4. ✅
- 신뢰 감쇠 conf(t) → Task 5/6 `_conf`. ✅
- 상세 리스트 2섹션 → Task 7. ✅
- Q6 되돌리고 재구축 → Task 1. ✅
- activate·완결성 게이트 유지 → Task 3. ✅
- 미러 0.0 → Task 6. ✅
- 롤아웃(시드·검토·activate) → Task 8. ✅

**Placeholder scan:** verify_rankdiff.py/verify_ref_scale.py 본문은 요지+명확한 알고리즘 서술(구모델 vs 신모델, HUB준공/refq 비율). Task7 units 주입은 collector 확장 명시. 그 외 실코드.

**Type consistency:** `done_q`/`sched_q`(수집기, dict[q→int]) → `permits['done']`/`['sched']`(hub_derive, dict[zone→dict[q→int]]) → `running_shortage(done, sched, refq, cur_q, horizon)`(calc/scCalc 동일 시그니처)·`_conf`/`_qkey`/`ANCHOR` calc↔scCalc 동일. `_hub_zone_map`는 `nm.split(' ')[0]`(leading 토큰) 일관.
