"""Conservative, deterministic editing shortcut; native Jobs remain authoritative.

This is not model reasoning. Ambiguous/reference-bound requests return None and
retain the existing planned editing pipeline, permissions and execution policy.
"""
import re
from time import perf_counter

from app.agents.execution_policy import autonomous


def uniform_edit_kind(content):
    if len(content) > 1200:
        return None
    # Ignore prohibitions on composition when detecting positive multi-source work.
    text = re.sub(r'(?:不要|禁止|不得|无需|不)(?:做)?(?:拼图|融合|拼接|合并)', '', content)
    text = re.sub(r'(?:不要|禁止|不得|无需|不)(?:再)?(?:新增|添加|删除|移除|改色|换脸|重新设计|重新构图)', '', text)
    if re.search(
        r'先.{0,8}(?:分析|规划|审核|确认|方案|建议|看看|做|出)|样图|等我|暂不|不要生成|不需要生成|只.{0,3}(?:分析|建议)|'
        r'是否|还是|或者|如果|哪[个些种]|不同|分别.{0,6}要求|有的|部分|'
        r'第[0-9一二三四五六七八九十两]+张|上一|前一|之前|历史|刚才|图\s*[ABCabc一二三123]|'
        r'蒙版|遮罩|涂抹|局部|抠图|扩图|画布|融合|拼接|拼图|合并|对比|比较|'
        r'换衣|换装|套图|套到|模板|参考图[ABCabc]|参考.{0,8}(?:风格|衣服|服装)|'
        r'领口|袖口|肩号|换成.{0,5}(?:衣服|服装|球衣)|(?:更换|替换|修改).{0,4}(?:衣服|服装|图案|号码|文字)|'
        r'A\+|A＋|ASIN|调研|记住|以后|忘记|下载|导出|版本|多场景|提示词|prompt|'
        r'多少钱|费用|预算|告诉我|教我|怎么|如何|写.{0,6}(?:指令|文案)|'
        r'新增|添加|删除|移除|改色|换脸|重新设计|重新构图|戴上|穿上|(?:衣服|球衣|服装|人物).{0,3}(?:换成|改成)', text, re.I
    ):
        return None
    if re.search(r'(?:不要|不用|禁止|不得|无需).{0,2}(?:提亮|压暗|调亮|调暗|换背景|更换背景|修改环境)', text):
        return None
    background = bool(re.search(
        r'(?:背景|环境).{0,8}(?:换成|改成|改为|替换为|更换为|设为|统一为)[^，。！？；\n]{1,120}|'
        r'(?:换成|改成|改为|替换为)[^，。！？；\n]{1,60}(?:背景|环境)|'
        r'(?:统一|换成|改成|改为|处理成|设为)(?:纯)?白(?:色背景|底|背景)', text
    ))
    brightness = bool(re.search(r'提亮|压暗|调亮|调暗|增加亮度|降低亮度|提高亮度', text))
    if background == brightness:  # Neither, or combined edits needing interpretation.
        return None
    # An unspecified target is not enough to skip clarification/planning.
    if re.search(r'(?:换成|改成|改为|替换为)\s*(?:一个|新的|其他|别的)?\s*(?:背景|环境)[，。！？；\s]*$', text):
        return None
    return 'background' if background else 'brightness'


def fast_edit_request(selection, context, *, is_autonomous):
    """Use only explicit current uploads, never guess a historical parent/binding."""
    if not is_autonomous or not selection.get('chat_mode') or selection.get('request_mode', 'create') != 'create':
        return None
    if any(selection.get(k) for k in (
        'parent_output_id', 'reply_to_run_id', 'use_batch_inputs', 'sample_review',
        'production_plan_id', 'amazon_plan_id', 'prompt_source_run_id',
        'review_before_generation', 'template_asset_ids', 'garment_asset_ids', 'prompt',
    )):
        return None
    module = (selection.get('_creative_context') or {}).get('module', 'auto')
    if module not in ('auto', 'image_edit'):
        return None
    attachments = selection.get('attachment_ids') or []
    if not 1 <= len(attachments) <= 10 or len(set(attachments)) != len(attachments):
        return None
    by_id = {a['attachment_id']: a for a in context['assets']}
    if set(attachments) - by_id.keys():
        return None  # Existing validation owns the error, never broaden references.
    sources = [by_id[i] for i in attachments]
    if len({a['id'] for a in sources}) != len(sources):
        return None
    from app.agents.intent_router import number
    counts = re.findall(r'([0-9一二三四五六七八九十两]+)张(?:上传的?|现有的?)?(?:图片|照片|原图|图像)', selection['content'])
    if any(number(n) != len(sources) for n in counts):
        return None
    if re.search(r'(?:每张|各自).{0,8}(?:两|二|[2-9]|多|若干)张|(?:生成|输出|返回).{0,3}(?:多张|多版)', selection['content']):
        return None
    kind = uniform_edit_kind(selection['content'])
    if not kind:
        return None
    return {'kind': kind, 'source_ids': [a['id'] for a in sources]}


def edit_prompt(content, kind):
    boundary = (
        '以当前提供的原图为唯一编辑底图，每张原图独立编辑并输出一张图片，不拼图、不混用其他原图。\n'
        '用户本次统一编辑要求：' + content.strip() + '\n'
    )
    if kind == 'background':
        rules = (
            '仅替换背景环境；根据原图相机视角、主体尺度和景深构建用户指定背景，'
            '处理自然边缘、接触阴影与遮挡，不移动或重新设计主体。'
            '严格保留原人物数量、身份、面部、发型、动作、身体比例、配饰以及服装的颜色、'
            '图案、Logo、文字、号码、领口、袖口、版型、纹理和褶皱。'
        )
    else:
        rules = (
            '只按用户要求调整亮度与曝光，保留色相和图案，不重新设计背景或主体；'
            '保持高光和阴影细节，避免过曝、死黑及不自然色偏。'
            '人物身份、姿势、服装结构、Logo、文字、号码及图案形状保持不变。'
        )
    return boundary + rules + (
        '保留原图现有标题、文案、装饰、位置与排版，不因替换背景而删除文字。'
        '保持原图主体数量、构图和画幅；原图没有人物时不得新增人物。'
        '禁止新增文字、水印、商品、道具或无关人物，只输出当前原图对应的完整编辑结果。'
    )


async def fast_edit_pipeline(db, settings, run, permissions, context, registry):
    request = fast_edit_request(run.selection_json, context, is_autonomous=autonomous(run))
    review_requested = (run.result_json.get('auto_execution') or {}).get('review_before_generation')
    if not request or review_requested or run.result_json.get('planner_decision') or run.result_json.get('autonomy'):
        return None
    started = perf_counter()
    from app.agents.capabilities import business
    from app.agents.capabilities.orchestrator import execution_context, stamp
    from app.agents import runtime
    cap = registry.get('business.create_images')
    skill = registry.load_skill('image-creation')
    if cap.id not in skill['allowed_tools']:
        return None
    plan = await business.materialize_image(db, settings, execution_context(run, permissions), context,
        run.selection_json, {'instruction': edit_prompt(run.selection_json['content'], request['kind']),
            'edit': True, 'independent_edits': True, 'reference_asset_ids': request['source_ids']})
    plan.capability_context = {**stamp(registry, ['image-creation']), 'selected_tools': [cap.id],
        'pending_capability': cap.id, 'pipeline': 'fast_edit_pipeline',
        'reason': '明确的统一编辑要求，确定性直通；没有模型规划或MCP调用',
        'source_count': len(request['source_ids']), 'model_planning_skipped': True}
    await runtime.event(db, run, 'fast_edit_routed', {'pipeline': 'fast_edit_pipeline',
        'kind': request['kind'], 'source_count': len(request['source_ids']),
        'capability_id': cap.id, 'model_planning_skipped': True,
        'route_ms': round((perf_counter() - started) * 1000, 3)}, key=f'fast-edit:{run.revision}')
    return plan
