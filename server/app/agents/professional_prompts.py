"""Deterministic execution envelope for model-authored art direction, not a second planner."""
import re

VERSION='professional-art-direction-v7'
PRINCIPLES={
 'product_identity':'Preserve reference-grounded product contour, exact color placement and printed identity.',
 'campaign_consistency':'Keep the campaign palette and lighting language consistent without repeating layouts.',
 'visual_hierarchy':'Make the intended product feature the first focal point and keep supporting information subordinate.',
 'commercial_lighting':'Use deliberate key/fill separation, coherent highlights and contact shadows, not generic glow.',
 'scale_context':'Use credible human/environment scale and camera perspective.',
 'detail_truth':'Show only details visible in original references; do not invent microscopic material structure or performance.',
 'emotional_story':'Communicate the specified human occasion through purposeful action and environment.',
 'copy_separation':'Keep native marketing copy outside the generated artwork; preserve inherent product print.',
 'multi_slot_storytelling':'This is one distinct image slot; other independently generated slots complete the native module.'}


def module_decision(module):
    """Compile a model's unique art direction; shared locks are added by aplus()."""
    return '\n'.join([
        'Produce one photographic image for this module; never a grid of outputs.',
        'Visual objective: '+module.main_point,
        'Model-authored scene and camera direction: '+module.composition,
        'Copy zone: '+module.copy_space+'. Typeset new marketing copy separately; preserve the product\'s original print.',
        'Use the supplied original product references. Integrate the product with coherent perspective, scale, lighting, surface geometry and contact shadows.',
    ])

def applied_rules(plan,module,slot,editing=False):
    from app.agents.amazon_contracts import RuleApplication
    execution=slot['direction'].design_execution if slot else None
    if editing and execution and plan.creative_strategy and plan.creative_strategy.version=='creative-director-v2':
        return [RuleApplication(principle=p,decision=d) for p,d in [
            ('product_identity','保留原参考商品的可见图案、字形、颜色与结构，不从历史生成图推导新事实。'),
            ('visual_hierarchy',execution.hierarchy),('commercial_lighting',execution.light),('copy_separation',execution.native_copy_layout)]]
    return module.rule_applications


def aplus(plan,module,*,editing=False,slot=None):
    from app.agents.amazon import module_spec, visual_rules
    spec=slot['spec'] if slot else module_spec(plan,module)
    facts=[e.statement for e in plan.insight.evidence if e.id in module.evidence_ids and e.scope=='own_product' and e.status=='fact']
    professional=plan.design_version=='professional-aplus-v2' and plan.deliverable=='aplus'
    multi=professional and len(spec.get('slots') or [])>1
    external_copy=professional and spec.get('layout') in {'header','image_left','image_right','three_columns','sidebar'}
    v2=bool(plan.creative_strategy and plan.creative_strategy.version=='creative-director-v2')
    image_prompt=module.image_prompt
    if multi or v2:
        # Remove only our generated envelope, never arbitrary user-authored text.
        # The module describes a sequence; its current slot supplies the camera.
        if image_prompt.startswith('Produce one photographic image for this module; never a grid of outputs.\n'):
            image_prompt='\n'.join(line for line in image_prompt.splitlines()
                if line!='Model-authored scene and camera direction: '+module.composition
                and (not v2 or line!='Produce one photographic image for this module; never a grid of outputs.')
                and not line.startswith('Visual objective: ')
                and not re.fullmatch(r"Copy zone: (left|right|top|bottom|none)\. Typeset new marketing copy separately; preserve the product's original print\.",line))
    geometry=slot['direction'].composition if slot and (multi or v2) else module.composition
    copy_layout=('Native headline/body are OUTSIDE this photographic image, in the Amazon module text fields. '
        'Use the entire image for its subject and environment; do not reserve an internal blank half, text panel or copy zone.'
        if external_copy else 'Reserve the specified quiet copy area for separate platform text; preserve inherent product print.')
    strategy=plan.creative_strategy
    creative=[]
    if strategy:
        c=strategy.concept
        creative=['CREATIVE DIRECTOR THEME: '+c.theme,
            'AUDIENCE / MOTIVATION (creative interpretation, not new product claims): '+c.audience+' / '+c.buying_motivation,
            'MEMORABLE VISUAL DEVICE: '+c.distinctive_device,
            'PALETTE ROLES: '+c.palette,'PHOTOGRAPHIC LANGUAGE: '+c.photographic_language,
            'EMOTIONAL TONE: '+c.emotional_tone,
            'NATIVE TYPE / LAYOUT DIRECTION (typeset outside artwork): '+c.typography_and_layout]
        if v2:creative+=['COMMERCIAL BIG IDEA: '+c.big_idea,'EXECUTABLE VISUAL MECHANISM: '+c.visual_mechanism,
            'WHY THIS PRODUCT: '+c.product_specificity]
        if module.narrative:
            creative+=['THIS STORY BEAT: '+module.narrative.story_beat,
                'SHOT PURPOSE / TREATMENT: '+module.narrative.shot_purpose+' / '+module.narrative.treatment]
            creative+=['MAPPED PURCHASE REASON '+r.id+f' (priority {r.priority}, {r.confidence}): '+r.reason+'; consumer value: '+r.consumer_benefit+'; scene: '+r.need_or_scene
                for r in strategy.purchase_reasons if r.id in module.narrative.reason_ids]
            if v2:creative+=['EVIDENCE BOUNDARY '+r.id+': '+r.evidence_boundary for r in strategy.purchase_reasons if r.id in module.narrative.reason_ids]
        creative+=['SKILL RULE IN ACTION '+r.principle+': '+r.decision for r in applied_rules(plan,module,slot,editing)]
    execution=slot['direction'].design_execution if slot else None
    if execution:creative+=['AUTHORITATIVE SLOT DESIGN '+key.upper()+': '+value for key,value in execution.model_dump().items()]
    return '\n'.join([
        ('Create ONE designed visual asset for this Amazon module. Follow its authored treatment: commercial photography, editorial still life or graphic art direction as specified; never replace a designed concept with a generic product photograph. This is not a complete page or a collage of outputs.' if v2 else 'Create ONE independent Amazon Listing product image, not a collage of outputs.' if plan.deliverable=='listing' else 'Create the photographic artwork for ONE Amazon A+ module, not a complete page or a collage of modules.'),
        ('COMPANY DESIGN DIRECTION: '+visual_rules()['directions'][module.design_direction]['composition']) if module.design_direction and not strategy else '',
        ('REFERENCE AND CUSTOM VALUES: '+visual_rules()['reference_contract']+' '+visual_rules()['customization']) if not strategy else 'REFERENCE CONTRACT: Preserve the actual product geometry, material appearance, color, inherent lettering and logo. Source photos define product identity; scene references do not supply product features.',
        'PRODUCT IDENTITY LOCK: '+plan.product_identity_lock,
        'Reference order: the first image is the previous output to edit; use subsequent original product references for product facts, not defects in that prior output.' if editing else 'Use the original product reference as the product source; follow any explicit scene/style reference roles in the module brief.',
        'The actual product references are the visual ground truth for color placement, silhouette, component geometry, printed text, numbers and logos. Do not borrow a different product from scene/style references.',
        'CAMPAIGN STYLE LOCK: '+plan.campaign_style_lock,
        'Keep this shared palette, lighting character, contrast and material treatment consistent with the campaign; vary the composition to suit THIS module instead of repeating one poster.',
        *creative,
        'SINGLE VISUAL MESSAGE: '+(geometry if multi else module.main_point),
        'PARENT MODULE CONTEXT (not additional views to draw): '+module.main_point if multi else '',
        'CUSTOMER NEED: '+module.user_need,
        'CONFIRMED PRODUCT EVIDENCE: '+'; '.join(facts),
        'MODULE ART DIRECTION: '+geometry,
        'CAMERA AND FRAMING: '+(execution.camera if execution else geometry if multi else module.art_direction.framing) if module.art_direction else '',
        'COMMERCIAL LIGHTING: '+(execution.light if execution else module.art_direction.lighting) if module.art_direction else '',
        'FOCAL / INFORMATION HIERARCHY: '+(execution.hierarchy if execution else module.art_direction.hierarchy) if module.art_direction else '',
        'PHYSICAL SCENE INTEGRATION: '+module.art_direction.integration if module.art_direction else '',
        'APPLIED DESIGN PRINCIPLES: '+', '.join(module.design_principles) if module.design_principles else '',
        'IMPLEMENTED DESIGN RULES: '+' '.join(PRINCIPLES[p] for p in module.design_principles) if module.design_principles else '',
        'THIS INDEPENDENT IMAGE SLOT: '+slot['id']+'; '+slot['direction'].composition if slot else '',
        'INDEPENDENT IMAGE PROMPT: '+image_prompt,
        f'OUTPUT FRAME: {spec["width"]}:{spec["height"]}. '+('Follow the authored framing and placement; deliberate close-up crops are allowed. Do not turn a detail or contextual shot into a centered full-product portrait.' if v2 else 'Compose for this frame without stretching or cutting off the product.'),
        'DESKTOP COMPOSITION / COPY SPACE: '+(copy_layout if external_copy else module.desktop_layout),
        'MOBILE SAFE CONTENT: '+module.mobile_layout,
        ('The slot-specific purpose, hierarchy, placement and differentiation above govern this image. Do not default to centered product, standing model with hands in pockets or interchangeable skyline backgrounds. The visible product detail may be the focal point without showing the entire item.' if v2 else 'Establish one clear focal hierarchy: product first, supporting scene second. Use deliberate depth separation, believable key/fill light and clean edge contrast, without generic glow or fake effects.'),
        'Integrate the product physically: coherent scale and perspective, contact shadows, matching light direction, faithful surface shape and correct foreground occlusion. No floating cutout or pasted flat decal.',
        copy_layout,
        'Do not render NEW headlines, body copy, labels, captions or watermarks. These are typeset separately. This does NOT remove or rewrite the product\'s inherent printed words, numbers or logos.',
        'Do not invent material, size, certification, performance benefits, brand authorization or unseen product surfaces. Market hypotheses are creative reasoning, never proven feature claims.',
        'Forbidden: '+'; '.join(module.prohibited),
        'ACCEPTANCE: '+'; '.join(module.acceptance),
        ('FINAL IMAGE SLOT CONTRACT: '+geometry+'. This request creates ONLY this independent slot, not its neighbouring views or the whole multi-image module. '
         +('Include secondary graphic elements only when explicitly authored above; do not invent additional module views. ' if v2 else 'Do not substitute a multi-view product pair or full-product overview for a requested close-up. ')+
         'For a detail view, tightly frame the actual visible region without inventing unseen microstructure. '+copy_layout) if professional and slot else '',
    ])


def tryon(template,garment):
    tf=' '.join(template.visual_facts+template.protected_elements)
    gf=' '.join(garment.visual_facts+garment.protected_elements)
    notes=['这是服装结构替换，不是把图案平贴到原衣服。图B的领口、袖型、衣身比例、肩线和下摆必须真实成为新服装结构。',
        '对模板中的目标服装分别适配：跟随身体透视、手臂张力、褶皱、接缝和原光源形成自然体积与阴影；手、头发、配饰遮挡顺序正确。',
        '保留非目标人物及非目标穿搭。没有人物的商品展示模板不得新增人物。不要为统一画面而改变当前服装的真实配色。',
        '文字、号码和Logo作为商品图形保留真实轮廓、笔画及位置；无法辨认时不编造，也不复制模板旧商品文字。']
    if re.search(r'连帽|帽衫|卫衣|hoodie|hooded',tf,re.I) and re.search(r'短袖|球衣|jersey|V领',gf,re.I) and not re.search(r'连帽|帽衫|hood',gf,re.I):
        notes.append('结构差异：模板原连帽上衣换为图B球衣。移除原服装的帽子、抽绳、袋鼠口袋及不属于图B的长袖；按图B重建领口和袖口，正确露出自然手臂。人物独立佩戴的帽饰、头发和配饰不是服装帽子，不得删除。')
    if template.template_type not in ('pure_white','detail_display','custom_process'):
        notes.append('场景融合只适配衣服表面的照明、透视和接触阴影，不重新设计场景，不更换人物身份，不重绘原广告文案。')
    return '\n'.join(notes)
