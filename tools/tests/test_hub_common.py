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
