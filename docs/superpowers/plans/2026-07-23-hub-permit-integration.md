# 건축HUB 시군구 실측 통합 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `calc()`/`scCalc()`의 인허가 성분 `dC`를 시도 인구배분에서 건축HUB 시군구 실측으로 교체하고, 착공 실측으로 forward 입주 창을 2년→4년으로 확장한다.

**Architecture:** 페이싱 배치 수집기(`fetch_hub_permits.py`)가 시군구별 인허가·착공 실측을 `hub_permits.json`으로 캐시 → 집계기(`update_adv_data.py` 스텝)가 생활권별 소량 파생값(`meas`/`fwd_far`)만 ADV에 주입 → `calc()`(존페이지)와 `scCalc()`(홈)이 **동일 산식으로 동시** 소비. 원시 레코드는 번들에 싣지 않는다.

**Tech Stack:** Python 3(stdlib + `subprocess`로 curl 호출), pytest(순수함수 단위테스트, 신규 도입), 기존 KOSIS/odcloud 파이프라인, GitHub Actions(공개 저장소).

## Global Constraints

- **키**: `~/.aptweather_keys.bat`가 주입하는 `DATA_GO_KR_KEY`(env). 스크립트는 `os.environ.get('DATA_GO_KR_KEY','')`로 읽는다(update_adv_data.py:32와 동일). 만료 2028-07-23.
- **HTTP**: urllib 금지(빈 200) → **curl(subprocess)**. 순차·병렬 금지. **호출당 2~3초 페이싱**. 빈 200(len 0) 백오프 재시도. `{"body":{}}`(60바이트)=정상 무데이터, 재시도 금지.
- **엔드포인트**: `https://apis.data.go.kr/1613000/HsPmsHubService/getHpBasisOulnInfo`. 파라미터 `serviceKey · sigunguCd(5) · bjdongCd(5, 필수) · numOfRows(≤1000) · pageNo`. 응답 XML.
- **집계 규칙**: `purpsCdNm=='공동주택' and totHhldCnt>0`, **`mgmHsrgstPk`로 dedupe**.
- **산식 미러 불변식**: `tools/make_zone_pages.py` `calc()`와 `index.html` `scCalc()`는 이중 구현이다. 한쪽을 바꾸면 반드시 다른 쪽도 같은 값이 나오게 바꾼다. 정규화(×12/H) 넣지 말 것(index.html:2005 경고).
- **가중치**: `W=(0.55, 0.35, 0.10)` (dA, dC, dB). 부호: 양(+)=부족=발산막대 오른쪽.
- **동기화 체크리스트**: 데이터 변경 시 `update_adv_data.py --update` → `tools/split_data.py` → `data.js`/`data-core.js`/`data-rest.json` 3종 git add & `git diff --quiet` → `sw.js` 버전 증가.
- **저장 위치**: 산출물은 저장소 내부(`aptweather/tools/data/`), 스크래치패드 금지(소실됨).
- **커밋**: 각 태스크 끝에 커밋. 병렬 세션이 흡수하므로 즉시.

---

## 파일 구조

- Create `tools/hub_common.py` — 순수 헬퍼(분기 변환·dedupe·옛구코드맵·착공→입주 이동). 네트워크 없음, 단위테스트 대상.
- Create `tools/fetch_hub_permits.py` — 페이싱 수집기 CLI. `hub_common` + `LIVEZONE` + bjdong 사용.
- Create `tools/data/code_bdong.json` — 법정동코드 자산(재다운로드, 커밋).
- Create `tools/data/hub_permits.json` — 수집 산출물(dedupe 완료, 커밋). `productive_bjdong` 캐시 포함.
- Create `tools/tests/test_hub_common.py` — 순수함수 pytest.
- Create `tools/verify_dc_rankdiff.py` — dC 교체 전/후 36곳 순위 diff 출력(검증 도구).
- Create `.github/workflows/hub-probe.yml` — 일회성 클라우드 IP 프로브(호스팅 게이트).
- Create `.github/workflows/update-hub.yml` — 월 1회 수집 배치(프로브 통과 시).
- Modify `tools/update_adv_data.py` — 집계기 스텝(`permits['meas']`, `permits['fwd_far']`) 추가.
- Modify `tools/make_zone_pages.py:38-98` — `calc()` dC 교체 + forward 4년.
- Modify `index.html:1981-2020` — `scCalc()` 미러(dC + forward 4년).
- Modify `sw.js` — 데이터 갱신 시 버전.

---

## Task 1: 파일럿 재확립 — 자산·API 형상·함정·런타임 실측

수집기를 코딩하기 전에 **실호출로 형상을 고정**한다(파일럿 스크래치패드 소실). 산출물: 커밋된 bjdong 자산 + 검증 노트.

**Files:**
- Create: `tools/data/code_bdong.json`
- Create: `tools/data/hub_pilot_notes.md` (검증 기록)

**Interfaces:**
- Produces: 커밋된 `code_bdong.json`; 검증된 사실 — (a) 오산 응답 XML 필드 실재, (b) 부천 옛구코드 정확값, (c) 시군구 1곳당 법정동 수·소요시간 → 전국 런타임 추정, (d) `bjdong` 시군구명 포맷(예 '마산합포구' vs '창원시 마산합포구').

- [ ] **Step 1: bjdong 자산 재다운로드**

```bash
cd "C:/Users/shpar/OneDrive/문서/Claude/aptweather"
mkdir -p tools/data
curl -sSL "https://raw.githubusercontent.com/WooilJeong/PublicDataReader/main/PublicDataReader/raw/code_bdong.json" -o tools/data/code_bdong.json
python -c "import json;d=json.load(open('tools/data/code_bdong.json',encoding='utf-8'));print(list(d.keys()));print(len(d[list(d.keys())[0]]))"
```
Expected: dict-of-columns 키 목록에 시도명·시군구코드·법정동코드·동리명·말소일자 포함, 행 수 수만.

- [ ] **Step 2: 오산 실호출로 응답 형상 확인**

오산시 sigunguCd=`41370`. 법정동 하나(예 `41370101` 오산동 계열; bjdong에서 오산 법정동코드 조회해 [5:] 사용) 로 1건 호출:
```bash
KEY="$(grep -oiE 'DATA_GO_KR_KEY=.*' ~/.aptweather_keys.bat | head -1 | cut -d= -f2 | tr -d '\r')"
curl -sS "https://apis.data.go.kr/1613000/HsPmsHubService/getHpBasisOulnInfo?serviceKey=${KEY}&sigunguCd=41370&bjdongCd=<오산 법정동[5:]>&numOfRows=100&pageNo=1"
```
Expected: XML에 `<item>` 다수, 각 item에 `platPlc·purpsCdNm·totHhldCnt·apprvDay·stcnsDay·useInsptDay·mgmHsrgstPk·bldNm`. `hub_pilot_notes.md`에 실제 태그명 그대로 기록(대소문자·철자).

- [ ] **Step 3: 부천 옛구코드 확정**

부천 현재 41190으로 호출→0건, 옛 41192/41194/41196 각각 호출해 어디에 데이터 있는지 확인. 각 옛구코드의 법정동[5:]는 bjdong에서 (말소 포함) 조회하거나, 데이터가 나온 item의 platPlc로 역확인. `hub_pilot_notes.md`에 `{현재코드: [옛코드…], 옛코드별 법정동리스트}` 기록.

- [ ] **Step 4: 런타임 실측**

임의 시군구 3곳(대도시 구 1·중소시 1·군 1)에 대해 소속 법정동 전체를 2.5초 페이싱으로 순차 호출, **법정동 수와 총 소요시간** 기록. 전국 zone-참조 시군구 수(다음 태스크에서 확정, 대략 150)로 곱해 총 런타임 추정. `hub_pilot_notes.md`에 기록.
Expected: 추정치가 수 시간이면 Task 3의 `productive_bjdong` 증분 캐시가 **필수**임을 확인(첫 full 1회, 이후 증분).

- [ ] **Step 5: 커밋**

```bash
git add tools/data/code_bdong.json tools/data/hub_pilot_notes.md
git commit -m "chore: bjdong 자산 재다운로드 + HUB 파일럿 형상·함정·런타임 실측 기록"
```

---

## Task 2: 클라우드 IP 프로브 (호스팅 게이트)

HUB가 Azure IP를 차단하는지 GitHub Actions에서 판정. **차단이면 Task 7이 로컬 폴백으로 분기**한다.

**Files:**
- Create: `.github/workflows/hub-probe.yml`

**Interfaces:**
- Produces: 워크플로 로그에 오산 시군구 응답 item 수. >0 이면 클라우드 가능.

- [ ] **Step 1: 프로브 워크플로 작성**

```yaml
name: hub-probe
on: { workflow_dispatch: {} }
jobs:
  probe:
    runs-on: ubuntu-latest
    steps:
      - name: HUB Azure IP 호출
        env: { KEY: ${{ secrets.DATA_GO_KR_KEY }} }
        run: |
          for i in 1 2 3; do
            R=$(curl -sS "https://apis.data.go.kr/1613000/HsPmsHubService/getHpBasisOulnInfo?serviceKey=${KEY}&sigunguCd=41370&bjdongCd=<오산 법정동[5:]>&numOfRows=100&pageNo=1")
            N=$(echo "$R" | grep -c "<item>")
            echo "try $i: items=$N bytes=${#R}"
            [ "$N" -gt 0 ] && exit 0
            sleep 3
          done
          echo "PROBE FAIL: 빈 응답 — Azure IP 차단 의심"; exit 1
```

- [ ] **Step 2: Secret 확인 안내**

`DATA_GO_KR_KEY`가 GitHub Secrets에 없으면 사용자에게 등록 요청(대화로). RONE_KEY 등록 전례 있음.

- [ ] **Step 3: 실행 및 판정**

```bash
git add .github/workflows/hub-probe.yml && git commit -m "ci: HUB 클라우드 IP 프로브(호스팅 게이트)"
git push
gh workflow run hub-probe.yml && sleep 20 && gh run watch
```
Expected: `items>0` 이면 **클라우드 경로 확정**; FAIL이면 **로컬 폴백 확정**. 결과를 `hub_pilot_notes.md`에 한 줄 기록.

---

## Task 3: 순수 헬퍼 `hub_common.py` (단위테스트)

네트워크 없는 순수함수만. pytest로 검증.

**Files:**
- Create: `tools/hub_common.py`
- Create: `tools/tests/test_hub_common.py`

**Interfaces:**
- Produces:
  - `to_quarter(day: str) -> str | None` — 'YYYYMMDD'/'YYYY-MM-DD' → 'YYYYQn'; 빈/불량 → None.
  - `dedupe(items: list[dict], key='mgmHsrgstPk') -> list[dict]` — key별 마지막 1건.
  - `apt_records(items: list[dict]) -> list[dict]` — `purpsCdNm=='공동주택' and int(totHhldCnt)>0` 필터 후 dedupe.
  - `shift_quarter(q: str, lag: int = 13) -> str` — 'YYYYQn' + lag분기.
  - `OLD_GU_MAP: dict[str, list[str]]` — Task1에서 확정된 `{현재5자리: [옛5자리…]}`.

- [ ] **Step 1: 실패 테스트 작성**

```python
# tools/tests/test_hub_common.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import hub_common as H

def test_to_quarter():
    assert H.to_quarter('20240315') == '2024Q1'
    assert H.to_quarter('2024-11-02') == '2024Q4'
    assert H.to_quarter('') is None
    assert H.to_quarter('bad') is None

def test_dedupe_keeps_one_per_pk():
    items = [{'mgmHsrgstPk':'A','totHhldCnt':'10'},
             {'mgmHsrgstPk':'A','totHhldCnt':'10'},
             {'mgmHsrgstPk':'B','totHhldCnt':'5'}]
    assert len(H.dedupe(items)) == 2

def test_apt_records_filters_and_dedupes():
    items = [{'mgmHsrgstPk':'A','purpsCdNm':'공동주택','totHhldCnt':'30'},
             {'mgmHsrgstPk':'A','purpsCdNm':'공동주택','totHhldCnt':'30'},  # 중복
             {'mgmHsrgstPk':'C','purpsCdNm':'단독주택','totHhldCnt':'1'},   # 유형 제외
             {'mgmHsrgstPk':'D','purpsCdNm':'공동주택','totHhldCnt':'0'}]   # 0세대 제외
    out = H.apt_records(items)
    assert [r['mgmHsrgstPk'] for r in out] == ['A']

def test_shift_quarter():
    assert H.shift_quarter('2024Q1', 13) == '2027Q2'
    assert H.shift_quarter('2024Q4', 1) == '2025Q1'
```

- [ ] **Step 2: 실패 확인**

```bash
cd "C:/Users/shpar/OneDrive/문서/Claude/aptweather"
python -m pip install -q pytest
python -m pytest tools/tests/test_hub_common.py -v
```
Expected: FAIL (`ModuleNotFoundError: hub_common`).

- [ ] **Step 3: 구현**

```python
# tools/hub_common.py
"""건축HUB 수집·집계 공용 순수 헬퍼 (네트워크 없음)."""
import re

# Task 1에서 실측 확정한 값으로 채운다.
OLD_GU_MAP = {
    '41190': ['41192', '41194', '41196'],  # 부천(2016 구 폐지)
}

def to_quarter(day):
    if not day:
        return None
    s = re.sub(r'\D', '', str(day))
    if len(s) < 6:
        return None
    y, m = int(s[:4]), int(s[4:6])
    if not (1900 < y < 2100 and 1 <= m <= 12):
        return None
    return '%dQ%d' % (y, (m - 1) // 3 + 1)

def dedupe(items, key='mgmHsrgstPk'):
    seen = {}
    for it in items:
        k = it.get(key)
        if k is None:
            continue
        seen[k] = it
    return list(seen.values())

def apt_records(items):
    def ok(it):
        if (it.get('purpsCdNm') or '').strip() != '공동주택':
            return False
        try:
            return int(float(it.get('totHhldCnt') or 0)) > 0
        except (TypeError, ValueError):
            return False
    return dedupe([it for it in items if ok(it)])

def shift_quarter(q, lag=13):
    m = re.match(r'^(\d{4})Q([1-4])$', q)
    idx = int(m.group(1)) * 4 + (int(m.group(2)) - 1) + lag
    return '%dQ%d' % (idx // 4, idx % 4 + 1)
```

- [ ] **Step 4: 통과 확인**

```bash
python -m pytest tools/tests/test_hub_common.py -v
```
Expected: 4 passed.

- [ ] **Step 5: 커밋**

```bash
git add tools/hub_common.py tools/tests/test_hub_common.py
git commit -m "feat: hub_common 순수 헬퍼(분기변환·dedupe·공동주택필터·착공이동) + 테스트"
```

---

## Task 4: 수집기 `fetch_hub_permits.py`

페이싱 배치. 대상 시군구 = `LIVEZONE` 참조 집합(‘*’ 확장). 증분 캐시(`productive_bjdong`)로 월간 저렴.

**Files:**
- Create: `tools/fetch_hub_permits.py`
- Modify: `tools/data/hub_permits.json` (생성)

**Interfaces:**
- Consumes: `hub_common.apt_records/to_quarter/OLD_GU_MAP`, `code_bdong.json`, `update_adv_data.LIVEZONE`(시군구 집합 도출).
- Produces: `tools/data/hub_permits.json`:
  ```json
  {"meta":{"fetched":"YYYY-MM-DD","mode":"full|incr"},
   "sgg":{"41370":{"name":"오산시","permit_q":{"2024Q1":123},"start_q":{"2024Q2":80}}},
   "productive_bjdong":["41370101","..."]}
  ```

- [ ] **Step 1: 대상 시군구·법정동 도출 검증(실행 스크립트)**

`build_targets()` — bjdong에서 `name→sigunguCd`, `sido→[sigunguCd…]` 구축 후 `LIVEZONE` 순회(‘*’→시도 전체). 먼저 도출만 해서 개수 출력:
```bash
python tools/fetch_hub_permits.py --list-targets
```
Expected: 시군구 수(대략 150) + 총 법정동 수 출력. Task1 런타임 추정과 대조.

- [ ] **Step 2: 수집기 구현**

핵심 로직(요지 — 전체는 파일에):
```python
import os, sys, json, time, subprocess, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hub_common as H
from update_adv_data import LIVEZONE

KEY = os.environ.get('DATA_GO_KR_KEY', '')
EP = 'https://apis.data.go.kr/1613000/HsPmsHubService/getHpBasisOulnInfo'
DATA = os.path.join(os.path.dirname(__file__), 'data')
PACE = 2.5

def _get(sigungu, bjdong, page=1):
    url = ('%s?serviceKey=%s&sigunguCd=%s&bjdongCd=%s&numOfRows=1000&pageNo=%d'
           % (EP, KEY, sigungu, bjdong, page))
    for attempt in range(4):
        r = subprocess.run(['curl', '-sS', url], capture_output=True, text=True)
        body = r.stdout or ''
        if len(body) > 80:            # 실데이터
            return body
        if '<totalCount>0' in body or len(body) <= 80:
            return body               # 정상 무데이터 — 재시도 금지
        time.sleep(PACE * (attempt + 1))
    return body

def _parse_items(xml):
    import re as _re
    items = []
    for blk in _re.findall(r'<item>(.*?)</item>', xml, _re.S):
        d = {t: v for t, v in _re.findall(r'<(\w+)>([^<]*)</\1>', blk)}
        items.append(d)
    return items
# ... build_targets(), 옛구코드 병합(OLD_GU_MAP), productive_bjdong 증분,
#     apt_records→to_quarter(apprvDay)→permit_q, to_quarter(stcnsDay)→start_q,
#     체크포인트 저장, --full/--list-targets/기본(증분) 플래그
```
페이싱·순차·빈응답 재시도·`{"body":{}}`(≤80바이트) 무재시도·`mgmHsrgstPk` dedupe(`apt_records`)·옛구코드 병합 반드시 포함. 증분: 기본은 `productive_bjdong`만, `--full`은 전체(첫 실행 필수).

- [ ] **Step 3: 소규모 실호출 검증**

오산·부천만 대상으로 `--only 41370,41190` 실행, 결과 확인:
```bash
python tools/fetch_hub_permits.py --full --only 41370,41190
python -c "import json;d=json.load(open('tools/data/hub_permits.json',encoding='utf-8'));import pprint;pprint.pprint({k:{'name':v['name'],'permit_q':dict(list(v['permit_q'].items())[:3]),'start_q':dict(list(v['start_q'].items())[:3])} for k,v in d['sgg'].items()})"
```
Expected: 오산·부천 둘 다 permit_q/start_q에 세대>0. **부천이 옛구코드 병합으로 0이 아님**(함정3 해소 증거). 파일럿 천명당 세대와 정합.

- [ ] **Step 4: 전체 first-full 실행(로컬)**

```bash
python tools/fetch_hub_permits.py --full 2>&1 | tail -20
```
Expected: 완주, `productive_bjdong` 채워짐, `meta.mode=full`. 소요시간 기록.

- [ ] **Step 5: 커밋**

```bash
git add tools/fetch_hub_permits.py tools/data/hub_permits.json
git commit -m "feat: 건축HUB 페이싱 수집기(옛구코드·PK dedupe·증분캐시) + 전국 first-full 산출"
```

---

## Task 5: 집계기 스텝 — `permits['meas']` / `permits['fwd_far']`

`hub_permits.json`을 존별 소량 파생값으로 접어 ADV에 주입. 원시 시군구는 번들 제외.

**Files:**
- Modify: `tools/update_adv_data.py` (permits 갱신 경로에 스텝 추가; `fetch_permits()` 근처)

**Interfaces:**
- Consumes: `hub_permits.json`, `LIVEZONE`, `LZ_GU2SI`, 기존 `zone_of` 규칙.
- Produces: `adv['permits']['meas'] = {zone: annual_avg_permit_세대}`, `adv['permits']['fwd_far'] = {zone: {'YYYYQn': 세대}}`.

- [ ] **Step 1: 매핑·집계 함수 작성**

```python
def _hub_zone_map(bdong):
    """sigunguCd(5) -> zone. bjdong의 시도명·시군구명 + LIVEZONE으로 귀속."""
    # code_bdong.json에서 sigunguCd -> (시도, 시군구명) 표 구성,
    # LZ_GU2SI로 gu→si 접기, LIVEZONE 순회하며 (시도, 시군구/‘*’) 매칭.
    ...

def hub_derive(adv):
    import json, statistics
    hp = json.load(open(os.path.join(TOOLS_DATA, 'hub_permits.json'), encoding='utf-8'))
    z_of = _hub_zone_map(load_bdong())
    WIN_Y = 3                                  # 다년 윈도우(연)
    now = datetime.date.today()
    ys = [now.year - k for k in range(WIN_Y)]  # 최근 3년
    meas, far = collections.defaultdict(int), collections.defaultdict(lambda: collections.defaultdict(int))
    orphan = 0
    for cd, v in hp['sgg'].items():
        z = z_of.get(cd)
        if not z:
            orphan += v.get('totish', 0) or 1; continue
        for q, n in v['permit_q'].items():
            if int(q[:4]) in ys:
                meas[z] += n
        for q, n in v['start_q'].items():
            far[z][H.shift_quarter(q, 13)] += n   # 착공+13분기=예상 입주
    adv['permits']['meas'] = {z: round(meas[z] / WIN_Y) for z in meas}      # 연평균 정규화
    adv['permits']['fwd_far'] = {z: dict(d) for z, d in far.items()}
    print('hub_derive: zones=%d orphan_sgg_ignored=%d' % (len(meas), orphan))
```

- [ ] **Step 2: permits 갱신 경로에 연결 + 고아 0 확인**

`fetch_permits()` 결과를 adv에 넣은 직후 `hub_derive(adv)` 호출. 실행:
```bash
python -c "import tools.update_adv_data as U; ..."   # 또는 --update의 permits 단계
```
Expected 로그: `orphan_sgg_ignored=0` (모든 수집 시군구가 존에 귀속). >0이면 `_hub_zone_map` 매핑 보정(창원 gu·통합시).

- [ ] **Step 3: 파생값 sanity 검증**

```bash
python -c "import json,re;t=open('data.js',encoding='utf-8').read();import json;a=json.loads(re.search(r'const ADV=(\{.*?\});\s*/\*ADV_DATA_END',t,16).group(1));p=a['permits'];print('meas zones',len(p['meas']));print('fwd_far zones',len(p['fwd_far']));print('오산권 meas',{k:v for k,v in p['meas'].items() if '오산' in k or '평택' in k})"
```
Expected: meas가 36곳 대부분 존재, 착공 fwd_far 분기가 2027~2029에 분포.

- [ ] **Step 4: 커밋**

```bash
git add tools/update_adv_data.py data.js
git commit -m "feat: HUB 집계기 — 존별 meas(연평균 인허가)·fwd_far(착공+13분기) ADV 주입"
```

---

## Task 6: `calc()` dC 교체 + forward 4년 (존페이지)

**Files:**
- Modify: `tools/make_zone_pages.py:16` (H_MAX 창), `:38-98` (`calc()`)
- Create: `tools/verify_dc_rankdiff.py`

**Interfaces:**
- Consumes: `adv['permits']['meas']`, `adv['permits']['fwd_far']`.
- Produces: 교체된 `calc()`; `verify_dc_rankdiff.py` 실행 도구.

- [ ] **Step 1: forward 창 4년으로 확장**

`make_zone_pages.py:53` FUTQ 슬라이스와 fut_supply를 근/원 분할:
```python
FUT_NEAR = 8    # ≤2년: odcloud byq
FUT_FAR  = 16   # ≤4년: 착공파생 fwd_far
FUTQ = sorted([k for k in allq if qi(k) is not None and qi(k) > cur_q], key=qi)
NEARQ = FUTQ[:FUT_NEAR]
# 원거리 분기는 fwd_far에서만 (odcloud byq far는 배타적으로 무시 — 이중집계 방지)
FARQ = ['%dQ%d' % ((cur_q+1+j)//4, (cur_q+1+j)%4+1) for j in range(FUT_NEAR, FUT_FAR)]
HQ = FUT_FAR   # need는 16분기 창
def fut_supply(zz):
    b = zz.get('byq') or {}
    near = sum(b.get(k, 0) for k in NEARQ)
    ff = (P.get('fwd_far') or {}).get(zz['z']) or {}
    far = sum(ff.get(k, 0) for k in FARQ)
    return near + far, HQ
```
`need = refq * HQ * share` (H 대신 HQ=16).

- [ ] **Step 2: dC 교체**

`make_zone_pages.py:75-81` 을:
```python
dC = 0; pv = None; plo = None
perm_z = (P.get('meas') or {}).get(z['z'])
if perm_z is not None:
    plo = refq * 4 * share            # (A) need-유도 연간 기준선 (4분기)
    dC = plo - (perm_z - dY * share)  # perm_z=연평균 실측, dY=시도멸실 배분
elif ps in P['regions']:              # 폴백: HUB 결측 존만 기존 인구배분
    pi = P['regions'].index(ps)
    vals = [r['v'][pi] for r in ph]
    if all(v is not None for v in vals):
        pv = sum(vals); plo = P['ref'][ps][0]
        dC = (plo - (pv - dY)) * share
tot = W[0] * dA + W[1] * dC + W[2] * dB
```

- [ ] **Step 3: 순위 diff 검증 도구 작성·실행**

```python
# tools/verify_dc_rankdiff.py — 교체 전/후 tot 순위를 나란히 출력
```
```bash
python tools/verify_dc_rankdiff.py
```
Expected: 36곳 before/after 순위표. 급변 존이 파일럿 왜곡(오산·평택 등 과대 인구배분 해소)으로 **설명 가능**해야 함. 설명 불가한 top-10 요동이면 `plo` (A)→(B) HUB 역사중앙값으로 전환(spec 폴백) 후 재실행.

- [ ] **Step 4: 존페이지 생성 스모크**

```bash
python tools/make_zone_pages.py
```
Expected: 예외 없음, 36 존 페이지 생성. dC 카드(`make_zone_pages.py:346-391`) 수치 정상.

- [ ] **Step 5: 커밋**

```bash
git add tools/make_zone_pages.py tools/verify_dc_rankdiff.py
git commit -m "feat: calc() dC 시군구 실측 교체 + forward 4년(분기 배타분할), 순위diff 검증"
```

---

## Task 7: `scCalc()` 홈 미러 동기화

`index.html` 홈 산식을 Task 6과 **동일 결과**로 맞춘다(불변식).

**Files:**
- Modify: `index.html:1990-2012`

**Interfaces:**
- Consumes: `ADV.permits.meas`, `ADV.permits.fwd_far`.

- [ ] **Step 1: FUTQ 근/원 분할 미러**

`index.html:1990-1994` 를:
```javascript
const allF=[...new Set(LZ.zones.flatMap(z=>Object.keys(z.byq||{})))]
  .map(k=>[k,qIdx(k)]).filter(x=>x[1]!=null&&x[1]>curQ).sort((a,b)=>a[1]-b[1]).map(x=>x[0]);
const NEARQ=allF.slice(0,8);                                  // ≤2년 odcloud
// FARQ: cur 이후 9~16번째 분기 키 (make_zone_pages FARQ와 동일 규칙: 분기인덱스 curQ+9..curQ+16)
const mkq=idx=>Math.floor(idx/4)+'Q'+(idx%4+1);
const farKeys=[];for(let j=8;j<16;j++)farKeys.push(mkq(curQ+1+j));
const H=16;
const futSum=z=>NEARQ.reduce((s,k)=>s+((z.byq||{})[k]||0),0)
  +farKeys.reduce((s,k)=>s+(((P.fwd_far&&P.fwd_far[z.z])||{})[k]||0),0);
```
`⚠️` 주석을 "H_MAX 8"→"NEAR 8 / FAR 16, make_zone_pages와 동일"로 갱신.

- [ ] **Step 2: dC 미러**

`index.html:2010-2011` 를:
```javascript
let dC=0,pv=null; const mz=P.meas&&P.meas[z.z];
if(mz!=null){const plo=refq*4*share; dC=plo-(mz-dY*share);}
else{const pi=P.regions.indexOf(ps);
  if(pi>=0){const vs=ph.map(r=>r.v[pi]);if(vs.every(v=>v!=null)){pv=vs[0]+vs[1];dC=(P.ref[ps][0]-(pv-dY))*share;}}}
const tot=0.55*dA+0.35*dC+0.10*dB;
```
`dA=refq*H*share-futSum(z)` 와 `need:refq*H*share` 의 H가 16인지 확인(Step1의 H).

- [ ] **Step 3: 홈=존페이지 동치 검증**

```bash
python tools/make_zone_pages.py   # 존 tot 산출
```
브라우저 프리뷰로 홈 순위표 상위 10곳과 존페이지 tot 비교(preview_start → read_page). 정규화 재발 방지(index.html:2005 경고).
Expected: 홈 상위 순위 == `calc()` 순위. 어긋나면 near/far·H·dC 식 재대조.

- [ ] **Step 4: 커밋**

```bash
git add index.html
git commit -m "feat: scCalc 홈 미러 — dC 실측·forward 4년 동기화(calc()와 동치)"
```

---

## Task 8: 호스팅 배선 + 동기화 체크리스트 + sw.js

Task 2 결과에 따라 분기.

**Files:**
- Create: `.github/workflows/update-hub.yml` (프로브 통과 시) **또는** 로컬 실행 문서화
- Modify: `sw.js` (버전), `tools/split_data.py` 확인

- [ ] **Step 1 (클라우드 경로): 월 배치 워크플로**

프로브 통과 시:
```yaml
name: update-hub
on:
  schedule: [{ cron: '0 18 1 * *' }]   # 매월 1일 03:00 KST
  workflow_dispatch: {}
jobs:
  fetch:
    runs-on: ubuntu-latest
    timeout-minutes: 180
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - name: 수집(증분)
        env: { DATA_GO_KR_KEY: ${{ secrets.DATA_GO_KR_KEY }} }
        run: python tools/fetch_hub_permits.py     # 기본=증분
      - name: 집계+split
        env: { KOSIS_API_KEY: ${{ secrets.KOSIS_API_KEY }}, DATA_GO_KR_KEY: ${{ secrets.DATA_GO_KR_KEY }} }
        run: |
          python tools/update_adv_data.py --update
          python tools/split_data.py
      - name: commit
        run: |
          git config user.name github-actions; git config user.email actions@github.com
          git add tools/data/hub_permits.json data.js data-core.js data-rest.json
          git diff --quiet && echo "no change" || git commit -m "data: HUB 월간 갱신" && git push
```

- [ ] **Step 1 (로컬 폴백): 문서화**

프로브 FAIL 시 워크플로 대신 `tools/data/hub_pilot_notes.md`에 월 1회 로컬 실행 절차 기록:
```
python tools/fetch_hub_permits.py && python tools/update_adv_data.py --update && python tools/split_data.py
git add ... && git commit && git push
```

- [ ] **Step 2: sw.js 버전 증가 + split 포함 확인**

`sw.js`의 캐시 버전(현 v8) +1. `split_data.py`가 `permits.meas/fwd_far`를 data-core에 포함하는지 확인(홈 점수가 필요로 함) — 필요 시 `split_data.py:63` 부근 permits 처리에 추가.

- [ ] **Step 3: 커밋**

```bash
git add .github/workflows/update-hub.yml sw.js tools/split_data.py tools/data/hub_pilot_notes.md
git commit -m "ci: HUB 월배치(or 로컬폴백) + sw.js 버전 + split 동기화"
```

- [ ] **Step 4: 메모리 갱신**

`hub-permit-integration.md`를 "계획"→"구현 완료"로 갱신(호스팅 경로 결과, OLD_GU_MAP 확정값, 런타임 실측, dC plo 선택 A/B 기록). `agongmap-data-pipeline.md` 동기화 체크리스트에 HUB 추가.

---

## Self-Review (작성자 체크)

**Spec coverage:**
- 수집기(함정4종) → Task 1(형상·함정 실측)+Task 3(dedupe/필터/구코드 순수함수)+Task 4(페이싱·증분). ✅
- 집계기 파생값 → Task 5. ✅
- dC 교체 → Task 6 Step2 + 순위diff Step3. ✅
- forward 4년 배타분할 → Task 6 Step1 + Task 7(홈). ✅
- 파생값만 번들 → Task 5(원시 제외) + Task 8 Step2(split 포함). ✅
- 호스팅 프로브 게이트 → Task 2 + Task 8 분기. ✅
- 미러 불변식 → Task 7 + 동치검증 Step3. ✅
- 파일럿 재확립 → Task 1. ✅

**Placeholder scan:** `_hub_zone_map`/`build_targets` 본문은 요지+명확한 알고리즘 서술(창원 gu·‘*’ 확장 규칙 명시). OLD_GU_MAP은 Task 1에서 실측 확정 후 Task 3에 기입(값 의존이 명시적). 그 외 실코드.

**Type consistency:** `permits['meas']`(dict[zone→int]), `permits['fwd_far']`(dict[zone→dict[q→int]])가 Task5 생성·Task6/7 소비에서 일치. `shift_quarter(q,13)`·`to_quarter`·`apt_records` 시그니처가 Task3 정의와 Task4/5 사용에서 일치. H(=16)·NEARQ(8)·FARQ가 calc()와 scCalc()에서 동일 규칙.
