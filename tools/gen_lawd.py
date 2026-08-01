# -*- coding: utf-8 -*-
"""lawd.json 재생성 — 실거래가 API용 시군구 코드 캐시.

형식: {"<시도명>|<시군구명>": "<5자리 법정동 시군구코드>"} — verify_ref_sido.py와
estimate_ref_inventory.py가 `k.split('|')`로 시도·시군구를 되꺼내 쓴다.

원본은 옛 세션 스크래치패드에 있다가 유실됐다(2026-08-01 인수인계 ②). 저장소의
tools/data/code_bdong.json(말소되지 않은 행)에서 그대로 파생되므로 외부 호출이 없다.

사용: python tools/gen_lawd.py [--write]
"""
import io, json, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'data', 'code_bdong.json')
OUT = os.path.join(HERE, 'data', 'lawd.json')


def build():
    d = json.load(io.open(SRC, encoding='utf-8'))
    out = {}
    for i in range(len(d['시도명'])):
        k = str(i)
        era = d['말소일자'][k]
        if not (era is None or (isinstance(era, float) and math.isnan(era))):
            continue                      # 말소된 코드는 제외
        sido, sgg = d['시도명'][k], d['시군구명'][k]
        if not isinstance(sido, str) or not isinstance(sgg, str) or not sgg:
            continue
        cd = str(d['시군구코드'][k])
        if len(cd) != 5:
            continue
        out.setdefault('%s|%s' % (sido, sgg), cd)
    return out


def main():
    m = build()
    print('lawd 항목 %d개' % len(m))
    for k in list(m)[:5]:
        print('   %-22s %s' % (k, m[k]))
    if '--write' in sys.argv:
        json.dump(m, io.open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
        print('saved', OUT)
    return 0


if __name__ == '__main__':
    sys.exit(main())
