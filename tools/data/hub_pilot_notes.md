# 건축HUB(HsPmsHubService) 파일럿 실측 노트

재확립일: 2026-07-23. 엔드포인트: `https://apis.data.go.kr/1613000/HsPmsHubService/getHpBasisOulnInfo`
(건축인허가 기본개요 조회). 인증키: `~/.aptweather_keys.bat`의 `DATA_GO_KR_KEY`(64자, `...0ad`로 끝남). 호출은 `curl -sG --data-urlencode`로 1회만 인코딩(키 원문에 예약문자가 있어도 이중인코딩 방지).

---

## Step 1: bjdong 자산 재다운로드

```bash
curl -sSL "https://raw.githubusercontent.com/WooilJeong/PublicDataReader/main/PublicDataReader/raw/code_bdong.json" -o tools/data/code_bdong.json
```

- 파일 크기: 10,123,043 bytes
- 스키마(dict-of-columns, 컬럼명 그대로): `시도코드, 시도명, 시군구코드, 시군구명, 법정동코드, 읍면동명, 동리명, 생성일자, 말소일자`
- 행 수(첫 컬럼 기준): **46,345**
- 값은 `{"컬럼": {"행인덱스(문자열)": 값}}` 형태(리스트 아님) — `d['시군구코드']['0']` 식으로 접근해야 함. `말소일자`가 없는 행은 JSON 로드 시 파이썬 `nan`(float)으로 들어오며 `str(...)=='nan'`으로 "현재 유효" 필터링 가능.
- 활성(말소일자 없음) 시군구 수: **250**개. 시도 단위 합계행(법정동코드가 `...00000`으로 끝나고 읍면동명 없음)은 시군구 목록이 아니므로 제외 필요.
- 활성 법정동(읍면동/리) 총합: **20,278**행, 시군구당 평균 **81.1**개, 중앙값 **77**개.

---

## Step 2: 오산 실호출 — 응답 형상 확인

오산시 `sigunguCd=41370`. bjdong에서 오산 소속 활성 법정동을 조회하니 `읍면동명`만 채워지고 `동리명`은 전부 결측(오산은 리 없이 동 단위). 아파트가 있을 법한 **세교동**(신도시) 선택: `법정동코드=4137011300` → `bjdongCd=[5:]="11300"`.

```bash
curl -sG "https://apis.data.go.kr/1613000/HsPmsHubService/getHpBasisOulnInfo" \
  --data-urlencode "serviceKey=${KEY}" --data-urlencode "sigunguCd=41370" \
  --data-urlencode "bjdongCd=11300" --data-urlencode "numOfRows=100" --data-urlencode "pageNo=1"
```

결과: `resultCode=00`, `totalCount=31`, `<item>` 31건(응답 크기 25,517 bytes). 그중 `purpsCdNm=공동주택`인 항목 4건, `totHhldCnt` 최대 832세대(대표 예: 832/727/720/514세대) — 실제 아파트 인허가 데이터 확인.

**item 태그명(발견된 그대로, 대소문자·철자 보존, 시도순 아님)**:
```
rnum, platPlc, sigunguCd, bjdongCd, platGbCd, bun, ji, mgmHsrgstPk, bldNm, splotNm,
block, lot, purpsCd, purpsCdNm, strctCd, strctCdNm, mainBldCnt, totArea, totHhldCnt,
demolExtngGbCd, demolExtngGbCdNm, demolStrtDay, demolEndDay, demolExtngDay,
apprvDay, stcnsSchedDay, stcnsDay, useInsptSchedDay, useInsptDay, crtnDay
```
브리프가 명시한 6개 필드(`platPlc·purpsCdNm·totHhldCnt·apprvDay·stcnsDay·useInsptDay·mgmHsrgstPk·bldNm`) 전부 실재 확인됨.

응답 봉투(body) 구조: `<response><header><resultCode/><resultMsg/></header><body><items><item>...</item>...</items><numOfRows/><pageNo/><totalCount/></body></response>`.

**중요 트랩(신규 발견, 브리프에 없던 것)**: `bjdongCd` 파라미터를 생략하면(즉 `sigunguCd`만 주면) HTTP 200이지만 **XML이 아니라 `{"body":{},"header":{"resultCode":"00","resultMsg":"NORMAL SERVICE"}}` 형태의 JSON 문자열**이 온다(69 bytes). 반면 `sigunguCd`+`bjdongCd`가 둘 다 유효하지만 실제 데이터가 0건이면 XML로 `<items/><totalCount>0</totalCount>` (약 190 bytes)가 온다. → **파서는 반드시 두 "무자료" 형태를 다 처리해야 함**: (1) JSON 형태 = 파라미터 누락/오류, (2) XML `<items/>` = 진짜 0건. 수집기(Task 4)는 `bjdongCd` 없이 절대 호출하지 말 것 — 항상 두 값 다 필요.

---

## Step 3: 부천 옛구코드 확정

- 현재 `sigunguCd=41190`(부천시, bjdongCd 없이 또는 유효 bjdongCd=10800로도) → **0건** (JSON `{"body":{}}` 무-bjdong 호출 시, XML `totalCount=0` 유효-bjdong 호출 시 둘 다 확인).
- 옛 구코드 3개 테스트 결과 (`bjdongCd`는 각 구 자체의 값으로 데이터가 있는 아무 코드나 사용, `platPlc`로 역확인):

| sigunguCd | bjdongCd(테스트값) | 결과 | platPlc(역확인) | 구 이름 |
|---|---|---|---|---|
| 41192 | 10800 | 데이터 있음 | "경기도 부천시 **원미구** 중동 3-80번지" | 원미구 |
| 41194 | 10600 | 데이터 있음 | "경기도 부천시 **소사구** 옥길동 701-1번지" | 소사구 |
| 41196 | 10800 | 데이터 있음 | "경기도 부천시 **오정구** 내동 22-4번지" | 오정구 |

**확정 매핑**: `{41190(부천시, 현재): [41192(원미구), 41194(소사구), 41196(오정구)]}`.

**핵심 함정(브리프가 예고한 것보다 더 심각)**: `code_bdong.json`에는 41192/41194/41196이 **시군구코드로 아예 존재하지 않는다**(2016년 구 폐지 후 원본 데이터셋에서 통째로 제거됨, 통합 부천시 41190의 법정동만 남음). 게다가 각 옛구의 `bjdongCd` 번호 체계는 **통합 부천시(41190)의 법정동코드와 일치하지 않는다** — 실측으로 확인:
  - `bjdongCd=10800` → 41192(원미구)에서는 "중동"을 반환(우연히 현재 41190 테이블의 중동=10800과 일치).
  - 그러나 같은 `bjdongCd=10800` → 41196(오정구)에서는 "내동"을 반환(현재 41190 테이블에서 내동은 12400 — **불일치**).
  - `bjdongCd=10600` → 41194(소사구)에서는 "옥길동"을 반환(현재 41190 테이블에서 옥길동은 11500 — **불일치**).
  
  즉 각 옛구는 폐지 이전의 독자적 법정동 번호 체계를 쓰며, 현재 부천시 통합 코드로 역산 불가능. **Task 4에서 옛 3구의 법정동 전체 리스트를 확보하려면 `code_bdong.json`(현재 활성 시군구만 수록) 외의 별도 소스(행정표준코드 이력 전체 테이블 등)가 필요**하다 — 이 갭을 Task 3/4 설계에 명시적으로 반영할 것. 본 파일럿에서는 3개 구 모두 유효 코드이고 데이터가 존재함만 확정했고, 전체 법정동 열거는 하지 않았음(비용 절감을 위해 브리프 지시대로 "형상 확인" 범위로 제한).

---

## Step 4: 런타임 실측 (3개 시군구, 2.5초 페이싱 순차 호출)

방법: `code_bdong.json`에서 활성 법정동코드[5:] 목록을 뽑아 시군구당 순차 호출(`numOfRows=1`로 페이로드 최소화, `sleep 2.5`), `date +%s`로 전/후 시각차 측정.

| 유형 | 시군구 | 법정동 수 | 총 소요(초) | 초/콜 |
|---|---|---|---|---|
| 대도시 구 | 서울 강남구(11680) | 14 | 69 | 4.93 |
| 중소시 | 경기 구리시(41310) | 7 | 26 | 3.71 |
| 군 | 충북 증평군(43745) | 29 | 106 | 3.66 |
| **합계** | | **50** | **201** | **4.02(평균)** |

- 실패/재시도 없음(빈 응답 len 0 없음). 응답은 전부 실제 데이터(981~1069 bytes) 또는 정상 0건(`<items/>`, 191 bytes) 둘 중 하나로 분류되어 트랩②의 "0건은 정상, 재시도 불필요" 판단 기준과 일치.
- **주의**: 위 3개 표본은 파일럿 비용을 줄이려고 일부러 **작은 시군구**를 골랐다(특히 증평군 29개는 군 치고 작은 편 — 인제군 50, 정선군 68, 영월군 66 등이 더 전형적). 표본 평균(16.7개/시군구)을 그대로 전국 추정에 쓰면 **과소평가**된다. 아래 런타임 추정은 `code_bdong.json` 전체 활성 시군구 통계(평균 81.1개/시군구, n=250)를 사용해 보정했다.

### 전국 런타임 추정

- 초/콜 실측 평균: **4.02초**(2.5초 페이싱 설정 + curl 왕복 및 서버 응답 지연 ~1.5초 포함).
- 시군구당 평균 법정동 수(전국 250개 활성 시군구 기준): **81.1개**.
- 브리프 가정 "zone-참조 시군구 수 ≈ 150"(다음 태스크에서 확정) 적용:
  - 총 호출 수 ≈ 150 × 81.1 ≈ **12,165회**
  - 총 소요 ≈ 12,165 × 4.02초 ≈ **48,900초 ≈ 13.6시간**
- 교차검증: 전국 활성 법정동 총합 20,278개 중 150/250(60%)이면 ≈12,167개로 위와 거의 일치.
- (참고, 과소평가 버전) 표본 3곳 평균(16.7개/시군구) 사용 시: 150×16.7≈2,505회×4.02초≈10,070초≈2.8시간 — **이 숫자는 쓰지 말 것**, 표본이 편향됨.

**결론**: 첫 전량 수집(full)은 약 **12~14시간**급 런타임으로 추정된다. 브리프의 "추정치가 수 시간이면 Task 3의 `productive_bjdong` 증분 캐시가 필수" 조건에 명확히 해당 — **증분 캐시(최초 1회 full, 이후 증분만 재호출)는 필수 설계 요소**로 확정.

---

## bjdong 시군구명 포맷 (Task 4/5용)

`code_bdong.json`의 `시군구명` 컬럼은 구가 있는 시의 경우 **"{시명} {구명}"** 형태로 나온다(구명 단독 아님):

- `48125` → `'창원시 마산합포구'` (단독 `'마산합포구'` 아님)
- `48127` → `'창원시 마산회원구'`
- `41135` → `'성남시 분당구'`

과거(현재는 말소된) 유사 사례도 동일 패턴: `48151` → `'마산시 합포구'`, `48153` → `'마산시 회원구'`(마산시가 창원시로 통합되기 전 자체 구 시절 표기).

**결론**: bjdong 기반으로 시군구명을 표시/매칭할 때 "시명 포함" 포맷을 정본으로 취급할 것. HUB API 응답의 `platPlc`(지번 주소)는 반대로 "경기도 부천시 원미구 중동..." 처럼 시/도-시-구-동 전체 주소 문자열이라 별개 포맷임에 주의(대조 매칭 시 부분일치 필요).

---

## 클라우드 프로브 결과 (Task 2에서 채움)

실시일: 2026-07-23. 워크플로: `.github/workflows/hub-probe.yml` (workflow_dispatch).
런: [WatermelonPark/aptweather run 30004590437](https://github.com/WatermelonPark/aptweather/actions/runs/30004590437) — job `probe`, `completed/success`.

- [x] 클라우드 환경: GitHub Actions `ubuntu-latest` (Azure East US 러너, Ubuntu 24.04.4)
- [x] 결과: **PASS** — 1차 시도에서 성공. 로그: `try 1: items=1 bytes=24675` → `PROBE PASS: items=1 — 클라우드 경로 가능`.
  (`grep -c "<item>"`는 응답이 단일 라인이라 실제 태그 개수가 아니라 "매치 라인 수"=1을 세지만, `bytes=24675`가 파일럿의 동일 쿼리 응답 크기(25,517 bytes, Step 2)와 근접해 진짜 데이터(31건 상당)가 왔음을 확인. IP 차단 시 나타나는 무자료 형태(JSON 69 bytes 또는 XML `<items/>` ~190 bytes)와는 확연히 다름.)
- [x] 비고: 시크릿(`DATA_GO_KR_KEY`/`DATAGOKR`)도 정상 해석됨(빈 키였다면 스텝이 exit 2로 즉시 실패했을 것). Azure IP 차단 없음 확인.

**판정: 클라우드 월배치 가능(CLOUD-VIABLE)** — Task 8은 GitHub Actions에서 실행 가능, 로컬 폴백 불필요.

---

## 적정 스케일 검증 (Task 4)

**전제**: '적정'(수요 기준선, `ADV.occupancy.ref[시도]` = `refq`, 신쌤 상수)은 이번 재설계에서
**손대지 않는다**. 바뀌는 건 공급 측 실측치뿐이다 — 기존 `ADV.occupancy`(KOSIS 준공실적,
분기·시도 단위)에서 건축HUB `useInsptDay`(준공, `done_q`, 분기·시군구→생활권 집계) 단위로
갈아탄다. 문제는 두 소스가 **집계 단위가 다르다**(시도 vs 시군구→생활권)는 점이라, `refq`가
기대하던 스케일과 HUB준공의 분기 스케일이 맞는지 별도 확인이 필요하다.

**도구**: `tools/verify_ref_scale.py` (읽기 전용 진단, 값을 고치지 않음).

1. `tools/data/hub_permits.json`을 직접 읽어 `sgg[시군구코드].done_q`(있는 것만 —
   `.get('done_q', {})`로 방어, 구스키마 `permit_q`/`start_q`만 있는 항목은 조용히 0 기여)를
   최근 3년(`calc()`의 LB=12분기 창과 동일) 구간으로 필터링한다.
2. `update_adv_data._hub_zone_map(update_adv_data._load_bdong_map())`을 **그대로 재사용**해
   시군구코드→생활권 매핑을 얻는다(Task 3에서 확정한 매핑과 100% 동일 — 별도 매핑 로직을
   새로 만들지 않음). 같은 생활권으로 매핑된 시군구들의 `done_q`를 분기별로 합산 후, 분기
   수로 나눠 "HUB준공 분기평균"을 얻는다.
3. `data.js`를 `make_zone_pages.load()`와 동일한 정규식 패턴(`/*ADV_DATA_START*/const ADV=...`)
   으로 파싱해 `ADV.livezone.zones`와 `ADV.occupancy`를 얻는다. 생활권마다 `make_zone_pages.calc()`
   의 지역 결정 규칙을 그대로 복제(`region=='수도권'`이면 무조건 `'수도권'`, 아니면 `psido`,
   그것도 없으면 `'수도권'` 폴백)해 시도를 정하고, `refq = O['ref'][시도]`(없으면 `O['band'][시도]`
   중앙값)를 가져온다.
4. 생활권별로 `HUB준공_분기평균 / refq` 비율 표를 출력하고, 표본이 5개 존 이상이면 비율의
   평균·표준편차·변동계수(CV)를 계산해 "CV<0.3이면 단일 스케일 계수로 보정 가능, CV>=0.3이면
   지역별 검토 필요"로 판정한다. done_q가 아예 없으면(현재 상태) 그 사실만 보고하고 exit 0.

**스모크 실행 결과 (2026-07-24, 전량 시드 전)**:

```
$ python tools/verify_ref_scale.py
done_q 데이터 없음 — 전량 시드 후 재실행 (hub_permits.json은 현재 부분 스캔 상태: meta.mode='full', sgg항목 3개 중 done_q 보유 0개)
```

예상대로다 — `hub_permits.json`은 아직 `sgg` 3개 항목뿐이고 전부 `permit_q`/`start_q`만 있는
구스키마(=Task 3 이전 파일럿 잔재)라 `done_q`가 하나도 없다(Task 7 전량 시드 미실행). 예외 없이
정상 종료(exit 0)해 브리프의 스모크 통과 조건을 만족한다.

**순수함수 단위 테스트**: `tools/test_verify_ref_scale.py` — `zone_done_avg`(인메모리 픽스처로
"같은 존 시군구 합산", "구스키마 done_q 없음은 무시", "3년 창 밖 분기 제외", "매핑 없는 코드 무시"
4가지 케이스)와 `zone_region`/`zone_refq`(calc() 규칙 미러링 — 수도권 강제, psido 폴백, ref 없으면
band 중앙값)를 검증. `python tools/test_verify_ref_scale.py` → 3개 테스트 모두 통과.

**남은 일 (Task 5로 이월)**: 실제 비율 표와 스케일 계수 판단은 `done_q`가 채워진 뒤에만
의미가 있다. 전량 시드(Task 7, `--full`, 추정 12~14시간) 완료 → `verify_ref_scale.py`
재실행 → 비율이 지역 간 일정하면 계수 하나로 `refq`를 보정하거나 HUB준공 쪽에 계수를
곱해 스케일을 맞추고, 들쭉날쭉하면 단일 계수를 포기하고 지역별 원인(생활권-시도 경계
불일치, 시군구 커버리지 격차 등)을 따로 조사한다 — 이 판단은 Task 5(순위검토)에서 확정한다.

---

## 준공 러닝재고 go-live 절차 (Task 8)

전제: 코드는 완결(Task 1~7, 86 테스트 통과, 미러 0.0), 스코어 계산 경로는
`hub_permits.json`의 `meta.activate`(현재 `false`)로 게이트돼 있다. 즉 아래 절차를
밟기 전까지는 라이브 사이트가 계속 기존(구모델) 스코어를 쓴다. **되돌리기는 언제든
`meta.activate`를 제거(또는 `false`)하고 커밋하면 즉시 구모델로 복귀**한다(코드 삭제 불필요).

### (a) 전량 시드 — `update-hub.yml` workflow_dispatch, mode=full, 2~3회

- GitHub Actions → `update-hub` 워크플로 → `Run workflow` → `mode=full` 선택.
- 전량 첫 시딩은 약 12,000회 호출·11~14시간이 걸려 GitHub 호스티드 러너의 6시간
  캡(`timeout-minutes: 350`)을 넘는다 — 킬돼도 정상이다. `fetch_hub_permits.py --full`은
  그룹 완료마다 `hub_permits.json`의 `meta['scanned']`에 진행 지점을 즉시 기록하므로,
  같은 `mode=full`을 **사람이 다시 트리거**하면 끊긴 지점부터 이어서 스캔한다
  (대략 **2~3회 재트리거**로 전량 완료 — Step 4 실측 기준 추정).
- **⚠️ 트리거 전 확인**: `DATA_GO_KR_KEY`(`data.go.kr`)의 **일일 호출 쿼터**를 반드시
  확인할 것. 1회 풀런이 약 12,000회를 소모하므로 일일 한도가 그보다 낮으면 하루 안에
  못 끝나고(정상 — collector가 429/한도초과를 재시도하지 않고 `unresolved`로 기록,
  다음날 이어받음) 예상보다 재트리거 횟수가 늘어난다. 한도가 넉넉하면(예: 무제한 또는
  10만+/일) 2~3회로 끝난다.
- 진행 상황 확인: 매 트리거 후 커밋된 `hub_permits.json`의 `meta.scanned` 길이(스캔
  완료 그룹 수)와 워크플로 로그를 보고 다음 재트리거 여부를 판단한다. 전량 완료 판정은
  `meta.mode` 및 `sgg` 항목 수가 더 이상 늘지 않고 `scanned`가 전체 그룹 수를 덮을 때.

### (b) 검토 — 순위·스케일 확인 (사용자 승인 필요)

전량 시드가 끝난 뒤(또는 상당량 진행된 뒤) 아래 두 진단을 로컬에서 실행한다:

```bash
python tools/verify_rankdiff.py   # 구모델 vs 신모델 — 생활권 36곳 순위 비교
python tools/verify_ref_scale.py  # HUB준공 분기평균 vs refq(적정) — 스케일 비율(CV)
```

- `verify_rankdiff.py`: 기존 KOSIS 기반 순공급 순위와 HUB 준공 기반 러닝재고 순위를
  36개 생활권에 대해 나란히 비교 출력한다. 순위가 크게 요동치는 존이 있으면(특히 상위권)
  원인(시군구 커버리지 누락, 부천 옛구 매핑 등)을 먼저 확인한다.
- `verify_ref_scale.py`: HUB준공 분기평균 / `refq`(신쌤 적정 상수) 비율의 변동계수(CV)를
  본다. `CV<0.3`이면 스케일이 지역 간 일정해 신뢰할 만하고, `CV>=0.3`이면 지역별 원인을
  더 파야 한다(위 "적정 스케일 검증" 절 참조 — 재피팅이 아니라 검증 목적).
- 두 출력을 사람이 보고 "납득할 만하다" 판단이 서면 (c)로 진행한다. 이 판단은 자동화하지
  않는다 — 스코어가 사용자에게 노출되는 핵심 지표라 사람 검토를 반드시 거친다.

### (c) 활성화 — `meta.activate=true`

- 로컬에서 `tools/data/hub_permits.json`을 열어 최상위 `meta.activate`를 `true`로
  설정하고 커밋·푸시한다(별도 워크플로 없음 — 사람이 직접 값을 바꾸는 1줄짜리 변경).
- 다음 daily `update-cloud.yml`(`update_adv_data.py --update`)이 실행되면
  `hub_derive()`가 `meta.activate=true`를 보고 `adv['permits']['done'|'sched'|'units']`를
  채우고, `make_zone_pages.calc()`/홈 `scCalc()`가 준공 기반 러닝재고 경로로 전환된다.
  `split_data.py`는 `permits`를 통째로 복사하므로(Task 8 확인 완료) `data-core.js`에도
  자동으로 실린다 — 추가 배선 불필요.
- **되돌리기**: `meta.activate`를 지우거나 `false`로 되돌려 커밋하면 다음 daily 런부터
  즉시 구모델(KOSIS 기반)로 복귀한다. 코드를 되돌릴 필요가 없다.

### 함정 재상기 (Task 2~3에서 확정, go-live 시 다시 확인)

- `bjdongCd` 파라미터 필수 — 생략하면 무자료 JSON(69 bytes)이 온다(진짜 0건 XML `<items/>`
  ~190 bytes와 다름, 3구분: ①bjdongCd 누락 JSON ②진짜 0건 XML ③auth 에러 XML).
- `useInsptDay`(준공, 과거) vs `useInsptSchedDay`(준공예정, 미래) — 착공일(`stcnsDay`)은
  이번 재설계에서 스코어 계산에 쓰지 않는다.
- 부천은 현재(41190)로 호출하면 0건 — 옛 3구(41192/41194/41196) 폴백 매핑 필요
  (`unresolved_legacy`로 별도 처리, Step 3 참조). 전량 시드 결과에서 부천 인근 생활권의
  값이 비정상적으로 낮으면 이 폴백이 제대로 동작했는지 우선 확인할 것.
