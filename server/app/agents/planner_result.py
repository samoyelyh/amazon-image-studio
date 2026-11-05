"""Strict planner JSON with bounded, non-semantic transport normalization.

Never invent fields/values, close truncated documents, or call another model.
Only one redundant structural delimiter may be removed, and only if exactly
one resulting document passes the original planner contract.
"""
import json
import re


def _unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate planner JSON key')
        result[key]=value
    return result


def _constant(value):raise ValueError('non-finite planner JSON number')


def _loads(raw):
    document=json.loads(raw,object_pairs_hook=_unique,parse_constant=_constant)
    if not isinstance(document,dict):raise ValueError('planner result must be an object')
    return document


def _structural_positions(raw):
    quoted=False;escaped=False
    for index,char in enumerate(raw):
        if quoted:
            if escaped:escaped=False
            elif char=='\\':escaped=True
            elif char=='"':quoted=False
        elif char=='"':quoted=True
        elif char in '{}[],:':yield index


def parse(raw,validate,*,finish_reason=None):
    if not isinstance(raw,str) or not raw.strip():raise ValueError('empty planner result')
    if len(raw)>100000:raise ValueError('intent response exceeds schema boundary')
    if finish_reason in {'length','content_filter'}:raise ValueError('incomplete planner response')
    original_length=len(raw);raw=raw.strip().removeprefix('\ufeff').strip();changes=[]
    fence=re.fullmatch(r'```(?:json)?\s*([\s\S]*?)\s*```',raw,re.IGNORECASE)
    if fence:
        raw=fence.group(1);changes.append('outer_json_fence')
    try:
        document=_loads(raw)
    except json.JSONDecodeError as error:
        # No arbitrary JSON "repair": preserve every key/value and only remove
        # one structural token within a bounded neighbourhood of the failure.
        candidates={}
        positions=set(_structural_positions(raw))
        for offset in range(max(0,error.pos-32),min(len(raw),error.pos+1)):
            if offset not in positions:continue
            char=raw[offset]
            if char not in '}]' and not (char==',' and raw[offset+1:].lstrip().startswith(('}',']'))):continue
            candidate=raw[:offset]+raw[offset+1:]
            try:
                value=_loads(candidate);result=validate(value)
            except (ValueError,TypeError,RecursionError):continue
            canonical=json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'))
            candidates.setdefault(canonical,(result,offset,char))
        if len(candidates)!=1:raise error from None
        result,offset,char=next(iter(candidates.values()))
        return result,{'normalizations':changes+['single_redundant_delimiter'],
            'removed':{'offset':offset,'character':char},'original_characters':original_length}
    result=validate(document)
    return result,({'normalizations':changes,'original_characters':original_length} if changes else None)


def rejection(error):
    """Safe diagnostics only: never include the raw response or validation inputs."""
    details={'exception':type(error).__name__}
    if isinstance(error,json.JSONDecodeError):details.update(line=error.lineno,column=error.colno,offset=error.pos)
    elif hasattr(error,'errors'):
        details['fields']=[{'loc':list(item['loc']),'type':item['type']} for item in error.errors()[:8]]
    return details
