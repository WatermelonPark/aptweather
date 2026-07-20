# -*- coding: utf-8 -*-
"""data.js에서 홈 화면이 실제로 쓰는 조각만 뽑아 data-core.js를 만든다.

배경: data.js 397KB를 모든 방문자가 매번 내려받는데, 홈이 실제로 쓰는 건
그중 일부다. 통계 탭을 열지 않는 방문자에게 주간 155주·기본통계 11계열을
보낼 이유가 없다.

전략은 '쪼개서 나눠 보내기'가 아니라 '핵심만 먼저 보내기'다.
  - data-core.js : 홈이 쓰는 것만. index.html이 즉시 로드.
  - data.js      : 그대로 둔다. 통계 탭을 열 때 fetch로 받아 core에 병합.
data.js를 손대지 않으므로 생활권 41장과 /cycle/은 아무 영향이 없다.

실행: python tools/split_data.py   (update_adv_data.py --update 뒤에)
"""
import io, json, os, re, sys

# 배치는 chcp 65001을 하지만 다른 경로로 불릴 수도 있다. 콘솔 인코딩 때문에
# 산출물을 다 만들고도 print에서 죽으면 배치가 exit 20으로 실패한다.
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'data.js')
OUT = os.path.join(ROOT, 'data-core.js')
REST = os.path.join(ROOT, 'data-rest.json')
TREND = os.path.join(ROOT, 'data-trend.json')

# 홈이 쓰는 STATS 계열 — 아공맵 스코어가 순공급을 계산할 때 참조한다.
# 나머지 9계열(매매지수·인허가·준공·착공·전세지수·금리·보급률·노후주택30년·
# 아파트건설, 합계 194KB)은 통계 탭 전용이라 core에 넣지 않는다.
CORE_STATS = ['전세가율', '주택멸실']

# 홈이 통째로 쓰는 ADV 키
CORE_ADV = ['livezone', 'occupancy', 'permits', 'bubble']


def main():
    src = io.open(SRC, encoding='utf-8').read()
    adv = json.loads(re.search(
        r'/\*ADV_DATA_START\*/\s*const ADV=(\{.*?\});?\s*/\*ADV_DATA_END\*/', src, re.S).group(1))
    stats = json.loads(re.search(r'const STATS\s*=\s*(\{.*?\});?\s*(?:/\*|const |$)', src, re.S).group(1))

    core_adv = {k: adv[k] for k in CORE_ADV if k in adv}

    # 히어로 배경 지도는 마지막 한 주만 쓴다(renderHeroMap: rows[rows.length-1]).
    # 전체 sgg는 59.7KB인데 그중 필요한 건 4.8KB뿐이다.
    w = adv.get('weekly') or {}
    sgg = w.get('sgg') or {}
    if sgg.get('rows'):
        core_adv['weekly'] = {'regions': w.get('regions', []),
                              'sgg': {'codes': sgg.get('codes', []), 'rows': sgg['rows'][-1:]}}

    core_stats = {k: stats[k] for k in CORE_STATS if k in stats}
    missing = [k for k in CORE_STATS if k not in stats]
    assert not missing, '홈이 쓰는 STATS 계열이 없다: %s' % missing

    dump = lambda o: json.dumps(o, ensure_ascii=False, separators=(',', ':'))
    body = (
        '/* 자동 생성 — tools/split_data.py. 직접 고치지 말 것.\n'
        '   홈 화면이 쓰는 조각만 담는다. 통계 탭을 열면 loadFullData()가\n'
        '   data-rest.json을 받아 이 전역에 Object.assign으로 채운다. */\n'
        'const ADV=%s;\n'
        'const STATS=%s;\n'
        'window.__DATA_CORE__=true;\n' % (dump(core_adv), dump(core_stats)))
    io.open(OUT, 'w', encoding='utf-8', newline='\n').write(body)

    # 나머지는 JSON으로 따로 낸다. 런타임에 data.js를 정규식으로 파싱하는 방식은
    # 선언 형태가 조금만 바뀌어도 조용히 깨지므로 쓰지 않는다.
    # 통계 탭에서 먼저 보이는 건 그래프(주간·월간)다. 기본통계 11계열은 그 아래
    # 세그먼트를 눌러야 나오므로 한 번에 받을 이유가 없다 — 둘로 더 쪼갠다.
    io.open(TREND, 'w', encoding='utf-8', newline='\n').write(
        dump({'ADV': adv}))
    # rest에 ADV를 또 담으면 trend와 중복돼 총 전송량이 오히려 는다(399→629KB).
    # rest는 기본통계 계열만 담는다 — ADV는 trend가 이미 실어 보냈다.
    io.open(REST, 'w', encoding='utf-8', newline='\n').write(dump({'STATS': stats}))

    full = len(src)
    rest = os.path.getsize(REST)
    print('data.js        %7.1f KB  (그대로 유지 — 다른 소비자 보호)' % (full / 1024))
    print('data-core.js   %7.1f KB  (홈 즉시 로드, %.0f%% 절감)'
          % (len(body) / 1024, 100 * (1 - len(body) / full)))
    print('data-trend.json%7.1f KB  (그래프 — 통계 탭 진입 시)' % (os.path.getsize(TREND) / 1024))
    print('data-rest.json %7.1f KB  (기본통계 — 세그먼트 누를 때)' % (rest / 1024))
    print('  core ADV   :', ', '.join(core_adv))
    print('  core STATS :', ', '.join(core_stats))


if __name__ == '__main__':
    main()
