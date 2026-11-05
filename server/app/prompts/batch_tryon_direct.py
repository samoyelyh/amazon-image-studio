"""Opt-in direct output preset. Image A/B keep the platform reference order."""
DIRECT_REPLACEMENT_PRESET_ID = "f96a520b-82bb-470a-9d71-a2c42fa11db8"
DIRECT_REPLACEMENT_LABEL = "通用模特换衣 · 直接输出（不经Luna）"
DIRECT_REPLACEMENT_PROMPT = """图A为模特模板图，图B为当前服装参考图。

将图B中的当前服装替换到图A中的所有目标球衣上。严格以图B为服装的视觉依据，准确保留其颜色、图案、领口、袖口、文字和号码。根据图A模特的身体姿势自然调整服装透视、褶皱和遮挡关系。保留图A中的人物身份、面部、动作、背景及原有文案，仅修改目标服装及必要的边缘区域。不得保留图A旧衣服的图案和结构，需要以图B参考服装准确重建文字、号码等细节部位，不得凭空修改或编造。

图C如有，仅用于定制文字和号码的字形参考，不得改变图B服装的颜色、图案、Logo、领口、袖口和商品结构。"""
