# 건축HUB 시군구 실측 통합 — 설계 (spec)

- 날짜: 2026-07-23
- 관련 메모리: `hub-permit-integration`, `agongmap-data-pipeline`, `aptweather-project`
- 파일럿: 2026-07-23 (API 스펙·함정 4종 검증 완료)

## 배경 / 문제

`tools/make_zone_pages.py`의 `calc()`와 이를 미러링하는 `index.html`의
`renderScoreSec`(홈 점수 산식)에서 **인허가 성분 `dC`**(가중 `W[1]=0.35`)는
현재 **시도 인허가 × 인구배분**이다:

```
dC = (plo - (pv - dY)) * share
  plo   = P['ref'][ps][0]              # 시도(ps) 인허가 기준선
  pv    = 최근 반기 2행 합             # 시도 최근 ~1년 아파트 인허가
  dY    = last_of(DM, ps)             # 시도 주택멸실
  share = z['pop'] / sido_pop         # 생활권의 시도 내 인구 비중
```

`permits` ADV는 `REG15`(수도권 통합 + 14개 시도)를 담으므로 `dC`는
**전국 36 생활권에 이미 계산되지만 시도 수준 인구배분**이다.
파일럿에서 천명당 아파트 세대가 오산272·평택223·이천202·성남143 로
**시군구 간 ≥1.9배** 벌어져(최근 공급은 더 큼) 인구배분이 실제 분포를 왜곡함을 확인.

또한 forward 입주 성분 `dA`는 odcloud(입주예정) 기반이라 **시야가 ~2년(H_MAX=8분기)**로 짧다.

## 목표

1. **`dC` 인허가를 시군구 실측으로 교체** — 인구배분 왜곡 제거.
2. **착공 실측으로 forward 창을 2년→4년 확장** — 착공+~3.25년=입주.

두 목표는 **같은 HUB 호출**에서 나오는 데이터(인허가일·착공일)를 쓰므로 함께 수집한다.

## 비목표 (YAGNI)

- 청약홈 분양정보 확장(2026-07-20 실측 후 철회, 편향 불균일).
- 건축인허가/건축물대장 형제 API — 주택인허가(공동주택 사업계획승인)만.
- 실시간/야간 갱신 — 데이터가 느리게 변하므로 월 1회로 충분.

## 아키텍처

4개 컴포넌트. 각자 단일 책임·독립 검증 가능.

### 1. 수집기 `tools/fetch_hub_permits.py`

건축HUB 주택인허가 API(`getHpBasisOulnInfo`)를 페이싱 배치로 호출해
시군구별 인허가·착공 실측을 캐시한다.

- **법정동코드 자산**: `tools/data/code_bdong.json` 을 재다운로드
  (`https://raw.githubusercontent.com/WooilJeong/PublicDataReader/main/PublicDataReader/raw/code_bdong.json`)
  후 **저장소에 커밋**(스크래치패드는 소실되고 클라우드 실행이 필요로 함).
  필터: 말소일자 빈 것(str 판정). **리(동리명 있음)도 포함**(신도시 읍면 아파트).
  `sigunguCd=법정동코드[:5]`, `bjdongCd=법정동코드[5:]`.
- **대상 시군구 집합**: `LIVEZONE`(update_adv_data.py:980)이 참조하는 시군구의 합집합.
  `('부산','*')` 같은 `'*'` 멤버는 해당 시도 전체 시군구로 확장. 이 집합만 호출(불필요한 시군구 스킵).
- **호출 규칙(함정 반영)**:
  - `serviceKey`(`~/.aptweather_keys.bat`의 `DATA_GO_KR_KEY`) · `sigunguCd` · `bjdongCd`(필수) · `numOfRows≤1000` · `pageNo`.
  - **urllib 금지 → curl(subprocess)**. urllib은 빈 200 반환(0/15), curl 15/15.
  - **순차·호출당 2~3초 페이싱**. 병렬 금지(스로틀 유발).
  - 빈 200(len 0) → 백오프 재시도. `{"body":{}}`(60바이트)는 **정상 무데이터라 재시도 금지**.
  - **옛 구코드 매핑**: 부천(41190→41192/94/96) 등 구 폐지 통합시 옛 구 코드에 데이터. 마산·진해 통합 창원 등도 점검.
- **집계 규칙**: `purpsCdNm=='공동주택' and totHhldCnt>0`, **`mgmHsrgstPk`로 dedupe**.
- **레코드 필드**: `platPlc`·`totHhldCnt`·`apprvDay`(인허가)·`stcnsDay`(실제착공)·`useInsptDay`(준공)·`mgmHsrgstPk`.
- **출력**: `tools/data/hub_permits.json` — **시군구별 연/분기 집계**(dedupe 완료 중간산물).
  스키마(안):
  ```json
  {
    "meta": {"fetched": "YYYY-MM-DD", "sigungu_count": N, "source": "getHpBasisOulnInfo"},
    "sgg": {
      "<sigunguCd5>": {
        "name": "오산시",
        "permit_q": {"2024Q1": 세대, ...},   // apprvDay 기준 분기 인허가 세대
        "start_q":  {"2024Q1": 세대, ...}    // stcnsDay 기준 분기 착공 세대
      }
    }
  }
  ```
- **재개 가능성**: 시군구 단위 체크포인트(중단 시 이어받기) — 전국 ~30-40분 배치이므로.
  진행/스킵/재시도 로그 출력.

### 2. 집계기 → ADV (`tools/update_adv_data.py`에 스텝 추가)

`hub_permits.json`을 읽어 **생활권별 소량 파생 지표**를 `adv['permits']`에 추가한다.
원시 시군구 레코드는 **번들에 싣지 않는다**(data-core 48KB 예산 보호). 오직 존별 파생값만.

- `permits['meas']` = `{zone: 세대}` — 최근 다년 윈도우(기본 최근 3년) 실측 인허가 세대 합.
  최근연도 희소 함정 → **다년 윈도우**로 보고지연 흡수.
- `permits['fwd_far']` = `{zone: {"2028Q2": 세대, ...}}` — 착공 기반 원거리 예상 입주.
  각 착공 세대를 `착공분기 + 13분기`(≈3.25년) 로 이동해 입주 예상 분기에 배치.
  존의 시군구→존 귀속은 occupancy와 동일한 `zone_of`/`LZ_GU2SI` 규칙 재사용.

집계기는 `LIVEZONE`을 단일 소스로 시군구→존 매핑을 공유한다(occupancy 빌더와 일관).

### 3. `calc()` 개편 + `index.html` 미러

메모리 원칙: **홈 산식과 반드시 동시 수정**(대용량 HTML 패턴). 어긋나면 홈/존페이지 점수 불일치.

#### 3a. dC 교체 (인구배분 → 시군구 실측)

기존 공식의 **구조는 유지**하되 인구배분 항을 존 실측으로 대체:

```
dC = plo_z - (perm_z - dY * share)
  perm_z = permits['meas'][zone]        # 존 실측 인허가 (인구배분 pv 대체)
  dY     = 시도 주택멸실 (기존)          # 멸실은 시도만 있으므로 share로 배분 유지
  plo_z  = 존 인허가 기준선              # (아래 두 후보 중 구현 시 확정)
```

`× share` 전역 곱은 제거(`perm_z`가 이미 존 수준).
**`plo_z`(기준선) 기본값 = (A)**, 순위 diff 검증에서 문제가 드러나면 (B)로 교체:
- (A) **need 유도(기본)**: `refq`(기준 분기 흡수) × 인허가 윈도우 분기수 × share — 기존 `need`와 정합.
- (B) **폴백 — HUB 역사 중앙값**: 존의 다년 인허가 중앙값(자기 기준선).

양(+)의 dC = 인허가가 기준선 미달 = 미래 부족(발산 막대 오른쪽=부족). 부호 방향은 기존과 동일 유지.

#### 3b. forward 2년→4년 (분기 배타 분할, 이중집계 없음)

`fut_supply(zz)`를 분기 단위로 재정의:
- `q ≤ cur_q + H_MAX`(향후 ~2년): **odcloud `byq` 그대로**(측정 입주예정).
- `cur_q + H_MAX < q ≤ cur_q + 16`(2~4년): **`fwd_far[zone]`만** 사용.
- 분기 경계로 **배타 분할**하므로 odcloud와 착공파생이 겹치지 않음.
  (최근 착공→2년내 입주 프로젝트는 이미 odcloud에 있고, 우리는 2년 밖 분기만 착공에서 더한다.)

전역 미래 분기 창 `FUTQ`/`HQ`를 16분기(4년)까지 확장. 모든 존이 같은 창을 써야 절대량 비교 성립(기존 불변식 유지).

### 4. 호스팅 — 구현 계획 1단계에서 분기

- **클라우드 프로브 먼저**: 일회성 GH Actions 워크플로가 HUB를 Azure IP에서 몇 시군구 호출.
  - 통과 → **월 1회 GH Actions 배치**(`.github/workflows/`에 추가, 공개 저장소=무료 무제한).
    산출물 `hub_permits.json` 커밋 → 집계기 재실행 → split → sw.js 버전.
  - **차단** → **로컬 월 1회 수동 스크립트**(사용자가 실행, 캐시 커밋). PC 은퇴와 부분 상충하나 월 1회 수동은 야간배치보다 훨씬 가벼움.
- HUB의 Azure IP 차단 여부는 파일럿(로컬 IP)에서 미검증 → **프로브가 게이트**.

## 데이터 흐름

```
HUB API ──curl 페이싱──▶ fetch_hub_permits.py ──▶ tools/data/hub_permits.json (커밋)
                                                        │
                              update_adv_data.py 집계기 ─┤ permits['meas'], permits['fwd_far']
                                                        ▼
                                         data.js ADV ──split──▶ data-core.js / data-rest.json
                                                        │
                          calc() (존페이지)  ◀───────────┴──────────▶  index.html renderScoreSec (홈)
                                    (동일 산식 미러, 동시 수정)
```

## 검증 / 테스트

- **파일럿 재확립**: bjdong 재다운로드 후 로컬 실호출로 오산/평택/이천/성남 천명당 세대 재현 확인(수집기 정합).
- **dedupe/함정 단위 테스트**: `mgmHsrgstPk` 중복 제거, 부천 옛구코드 매핑, `{"body":{}}` 무재시도.
- **순위 diff 검증(핵심)**: dC 교체 **전/후** 36곳 `tot` 순위를 나란히 출력.
  급변 존은 실측 근거로 설명 가능해야 함(왜곡 제거의 기대 효과). 설명 불가한 요동은 재정식화 재검토.
- **forward 배타분할 검증**: H_MAX 경계에서 odcloud/착공 겹침 0 확인, 존별 `fsup` 단조성 점검.
- **동기화 체크리스트(메모리)**: `hub_permits.json` 갱신 → 집계기 → `data-core.js`/`data-rest.json` split → `sw.js` 버전. 하나라도 빠지면 홈만 지난 데이터.

## 리스크

1. **HUB Azure IP 차단** — 프로브로 즉시 판정, 차단 시 로컬 폴백(설계에 이미 분기).
2. **dC 재정식화가 순위를 흔듦** — 순위 diff 검증 스텝으로 관리, `plo_z` A/B.
3. **최근연도 희소** — 다년 윈도우로 완화.
4. **구 폐지 통합 코드 불일치** — 매핑 테이블, 신규 통합시 점검 필요(유지보수 항목).

## 구현 순서(개요 — 상세는 plan에서)

1. 클라우드 프로브(호스팅 게이트) + bjdong 재다운로드·커밋 + 파일럿 재확립.
2. `fetch_hub_permits.py` 수집기(페이싱·dedupe·구코드·재개).
3. 집계기 스텝(`meas`/`fwd_far`) + 시군구→존 매핑 재사용.
4. `calc()` dC 교체 + 순위 diff 검증 → `plo_z` 확정.
5. forward 4년 확장(분기 배타분할) — calc() + index.html 미러.
6. 호스팅 배선(월 배치 or 로컬) + 동기화 체크리스트 + sw.js.
