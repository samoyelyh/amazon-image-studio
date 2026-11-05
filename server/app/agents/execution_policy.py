"""Human intent and execution policy, separate from billing and model proposals."""
import re

CLARIFICATION = {'needs_input', 'awaiting_clarification'}
REVIEW = {'awaiting_review'}
PENDING = CLARIFICATION | REVIEW


def autonomous(run):
    return (run.result_json.get('auto_execution') or {}).get('version') == 2


def wants_review(content):
    # Consent is sourced only from the human message, never a model question or Skill.
    content=re.sub(r'(?:不用|无需|不要|不需要)(?:再|先|进行|经过|额外|费用|额度|模型调用|提交|生成|的|任何){0,8}(?:确认|审核|审批)(?:费用|额度)?','',content)
    content=re.sub(r'(?:不用|无需|不要|不需要)(?:先)?(?:给我)?(?:看看方案|看方案|看提示词|看[Pp]rompt)','',content)
    content=re.sub(r'(?:不是|不要|不用|无需).{0,2}(?:只|仅)(?:给|出|做).{0,3}方案','',content)
    return bool(re.search(r'先.{0,8}(?:看看方案|看方案|审核|审阅|看.{0,3}提示词|看.{0,3}[Pp]rompt)|等我确认|确认后再生成|先不要生成|只.{0,3}(?:方案|提示词).*不.{0,3}生成|(?:只|仅)(?:给|出|做|要|提供).{0,3}方案|先(?:不要|不|别).{0,3}(?:生成|生图)|先(?:给|出).{0,3}方案', content))


def wants_sample_review(content):
    if re.search(r'(?:不用|无需|不要|不需要).{0,8}样图',content):return False
    return bool(re.search(r'先.{0,4}(?:做|出|看|验证).{0,3}样图|样图.{0,8}(?:确认|通过|审核)',content))


def continuation(content):
    return re.sub(r'[\s，。！!？?、,.]+', '', content) in {
        '是','是的','好','好的','继续','继续吧','可以','可以了','确认','确认生成','开始','开始吧',
        '按刚才的做','按照刚才的做','按刚才做','就这样','执行','同意','确认并执行','按这个生成','直接生成','全部做','全部生成',
    }


def approval_question(question):
    if not question:
        return False
    value = re.sub(r'\s+', '', question)
    # Do not discard real subject/role/size/content choices merely because they say "confirm".
    if re.search(r'哪个|哪些|什么|哪张|哪件|多少|尺寸|颜色|姓名|号码|正面还是|背面还是|还是|是否只|是否需要保留|是否更换', value):
        return False
    return bool(re.search(r'(?:是否|请|能否|可以).{0,6}(?:确认|允许|同意).{0,12}(?:提交|生成|执行|调用|消耗|扣除)|是否(?:现在|立即|继续|开始).{0,6}(?:提交|生成|执行)|(?:确认|允许|同意).{0,5}(?:提交|生成|执行|调用|消耗|费用|额度)|(?:may|can|shall|should)I(?:proceed|generate|submit)|confirm.{0,20}(?:generat|submit|cost)', value, re.I))


def explicit_previous_output(content):
    return bool(re.search(r'上一张|上一版|上次生成|刚才生成|之前生成|历史结果|第.{1,3}张(?:结果|生成)', content))
