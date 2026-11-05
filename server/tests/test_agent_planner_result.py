import json
from types import SimpleNamespace
import pytest
from app.agents.planner import parse_intent_result,parse_intent_result_with_diagnostics
from app.agents.planner_result import parse,rejection


def job(raw,finish='stop'):
    return SimpleNamespace(input_json={},result_json={'metadata':{'text':raw,'finish_reason':finish}})


def decision():
    return {'summary':'生成商品图','skills':['image-creation'],'steps':[{'capability_id':'business.create_images',
        'arguments':{'instruction':'保留红色球衣和图案，背景换为足球场。'},'reason':'按用户要求编辑'}]}


def test_valid_result_unchanged_and_no_diagnostics():
    raw=json.dumps(decision(),ensure_ascii=False)
    parsed,details=parse_intent_result_with_diagnostics(job(raw))
    assert details is None and parsed.capability_plan['steps'][0]['arguments']==decision()['steps'][0]['arguments']


def test_actual_failure_shape_one_extra_closing_brace_before_reason():
    raw=json.dumps(decision(),ensure_ascii=False).replace('}, "reason"','}}, "reason"',1)
    with pytest.raises(json.JSONDecodeError):json.loads(raw)
    parsed,details=parse_intent_result_with_diagnostics(job(raw))
    assert parsed.capability_plan['steps'][0]['arguments']==decision()['steps'][0]['arguments']
    assert details['normalizations']==['single_redundant_delimiter']
    assert details['removed']['character']=='}'


@pytest.mark.parametrize('wrap',[lambda x:'```json\n'+x+'\n```',lambda x:'\ufeff'+x,
    lambda x:x[:-1]+',}'])
def test_safe_wrappers_and_single_trailing_comma(wrap):
    assert parse_intent_result(job(wrap(json.dumps(decision(),ensure_ascii=False)))).intent=='generate'


def test_never_change_quoted_prompt_content():
    value=decision();value['steps'][0]['arguments']['instruction']='保留文字 "TEAM }]," 和反斜线 \\；背景为球场。'
    raw=json.dumps(value,ensure_ascii=False).replace('}, "reason"','}}, "reason"',1)
    parsed=parse_intent_result(job(raw))
    assert parsed.capability_plan['steps'][0]['arguments']==value['steps'][0]['arguments']


@pytest.mark.parametrize('raw',[
    '{"intent":"generate","summary":"first","summary":"second"}',
    '{"intent":"generate","summary":"unfinished',
    '{"intent":"generate","summary":"ok"}}}',
    '{"intent":"generate","summary":"ok", "unknown": true}',
    '[{"intent":"generate","summary":"ok"}]',
    '{"intent":"generate","summary":"ok","image_count":NaN}',
    'explanation\n{"intent":"generate","summary":"ok"}',
])
def test_unsafe_or_incomplete_responses_still_rejected(raw):
    with pytest.raises((ValueError,TypeError)):parse_intent_result(job(raw))


def test_finish_length_rejected_even_when_json_syntactically_valid():
    with pytest.raises(ValueError,match='incomplete'):parse_intent_result(job(json.dumps(decision()),'length'))


def test_multiple_delimiter_repairs_are_not_attempted():
    # Two extra closing tokens require guessing beyond the one-token budget.
    raw='{"a":[{"b":1}]},"c":2},"d":3}'
    with pytest.raises(ValueError):parse(raw,lambda v:v)


def test_safe_diagnostics_exclude_returned_content_and_validation_input():
    try:parse_intent_result(job('{"intent":"BAD","summary":"private-value"}'))
    except ValueError as error:details=rejection(error)
    assert 'private-value' not in json.dumps(details) and 'fields' in details
