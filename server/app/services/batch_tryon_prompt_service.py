from __future__ import annotations

from dataclasses import dataclass


MANUAL_ERROR_RULES = {
    "left_right_sleeve": "Correct the wearer-left and wearer-right sleeve mapping. Never mirror or swap sleeve-specific artwork.",
    "front_back": "Correct the front/back garment view. Never transfer back artwork to the front or front artwork to the back.",
    "text_number": "Correct every visible letter, word and number exactly, including leading zeros, font style and placement.",
    "color": "Correct garment colors to match the current garment reference exactly; do not inherit colors from any other image.",
    "detail_composition": "Restore the detail template crop, zoom, camera distance, angle, body framing and composition exactly.",
}


@dataclass(frozen=True)
class BatchTryOnPromptBundle:
    business_prompt: str
    technical_delivery_contract: str
    effective_prompt: str


PURE_WHITE_SERVER_FALLBACK = """PURE WHITE PRODUCT LAYOUT REPLACEMENT

Use Reference Image 1 only as the fixed product-display layout authority. Preserve its pure white background, product count, front/back arrangement, positions, scale, spacing, crop, whitespace and shadow relationship.

Use Reference Image 2 as the sole visual truth for the current garment. Replace only the template garment content with the current garment. Preserve the current garment's exact colors, graphics, text, numbers, names, logos, prints, front and back designs, neckline, cuffs, shoulder construction and wearer-left/wearer-right sleeve details.

Do not inherit any garment-specific color, graphic, text, number, logo or design from Reference Image 1. Do not mirror, swap or duplicate asymmetric sleeve elements. If the layout contains front and back views, map the corresponding current-garment views correctly.

Keep a pure white background. Do not add people, scenes, props, decorations or a collage. Do not alter the white background based on garment color."""

GIFT_SCENE_SERVER_FALLBACK = """GIFT SCENE GARMENT REPLACEMENT

Use Reference Image 1 as the fixed authority for the person, identity, face, hairstyle, pose, hands, gift props, festive or gifting environment, camera, framing, lighting and occlusion. Replace only the worn garment with Reference Image 2. Preserve natural interaction between the garment, body, hands, gifts and foreground objects. Do not add people, gifts, text or decorations that are absent from the template."""

STADIUM_SCENE_SERVER_FALLBACK = """STADIUM SPECTATOR SCENE GARMENT REPLACEMENT

Use Reference Image 1 as the fixed authority for the spectator identity, face, pose, stadium or stands, crowd distribution, camera, framing, lighting, depth of field and occlusion. Replace only the target person's garment with Reference Image 2. Do not change the spectator into a player, duplicate people, alter the crowd or spread garment artwork into the background."""

DETAIL_DISPLAY_SERVER_FALLBACK = """GARMENT DETAIL DISPLAY REPLACEMENT

Use Reference Image 1 as the fixed authority for the detail focus area, crop, magnification, camera distance, angle, composition, background, lighting and shadow. Reconstruct the corresponding area from Reference Image 2 faithfully. Show only details supported by the current garment reference; never invent stitching, materials, functions or decorations."""

CASUAL_SCENE_SERVER_FALLBACK = """CASUAL LIFESTYLE GARMENT REPLACEMENT

Use Reference Image 1 as the fixed authority for the person, identity, face, hairstyle, body proportions, pose, hands, casual environment, camera, framing, lighting, color mood and occlusion. Replace only the target garment with Reference Image 2. Keep trousers, shoes, accessories, people and background unchanged, and preserve natural garment fit around hair, hands, bags and foreground objects."""

CUSTOM_PROCESS_SERVER_FALLBACK = """CUSTOMIZATION PROCESS INFOGRAPHIC PRODUCT REPLACEMENT

Use Reference Image 1 as the fixed authority for process step count and order, panels, arrows, icons, information hierarchy, spacing, typography areas, color system and product-image positions. Replace only the garment product illustrations with Reference Image 2. Preserve all existing process copy exactly and do not invent customization options, labels or claims."""


TEMPLATE_TYPE_COMPOSERS = {
    "pure_white": {
        "heading": "AI BATCH TRY-ON — PURE WHITE PRODUCT LAYOUT",
        "fallback": PURE_WHITE_SERVER_FALLBACK,
        "authority": "Reference Image 1 is the pure-white product-layout authority. Reference Image 2 is the current garment and the sole visual source for all garment content in this task.",
        "extra_scope": "product fidelity and pure-white layout rules",
    },
    "gift_scene": {
        "heading": "AI BATCH TRY-ON — GIFT SCENE",
        "fallback": GIFT_SCENE_SERVER_FALLBACK,
        "authority": "Reference Image 1 is the authority for the person, gift setting, props, composition, light and occlusion. Reference Image 2 is the sole authority for the replacement garment.",
        "extra_scope": "garment fidelity and gift-scene continuity",
    },
    "stadium_scene": {
        "heading": "AI BATCH TRY-ON — STADIUM SPECTATOR SCENE",
        "fallback": STADIUM_SCENE_SERVER_FALLBACK,
        "authority": "Reference Image 1 is the authority for the spectator, stadium or stands, crowd, composition, light and occlusion. Reference Image 2 is the sole authority for the replacement garment.",
        "extra_scope": "garment fidelity and stadium-scene continuity",
    },
    "detail_display": {
        "heading": "AI BATCH TRY-ON — GARMENT DETAIL DISPLAY",
        "fallback": DETAIL_DISPLAY_SERVER_FALLBACK,
        "authority": "Reference Image 1 is the authority for the detail focus, crop, scale, camera, composition, background and light. Reference Image 2 is the sole authority for the current garment detail being displayed.",
        "extra_scope": "visible garment evidence and detail-layout fidelity",
    },
    "casual_scene": {
        "heading": "AI BATCH TRY-ON — CASUAL LIFESTYLE SCENE",
        "fallback": CASUAL_SCENE_SERVER_FALLBACK,
        "authority": "Reference Image 1 is the authority for the person, casual environment, pose, composition, light and occlusion. Reference Image 2 is the sole authority for the replacement garment.",
        "extra_scope": "garment fidelity and casual-scene continuity",
    },
    "custom_process": {
        "heading": "AI BATCH TRY-ON — CUSTOMIZATION PROCESS INFOGRAPHIC",
        "fallback": CUSTOM_PROCESS_SERVER_FALLBACK,
        "authority": "Reference Image 1 is the authority for the process steps, infographic layout, arrows, icons, copy areas and product positions. Reference Image 2 is the sole authority for the garment illustrations.",
        "extra_scope": "garment fidelity and infographic information integrity",
    },
}


def append_manual_retry_constraints(
    base_prompt: str, *, error_codes: list[str] | None = None, manual_notes: str = "",
) -> str:
    corrections = [MANUAL_ERROR_RULES[code] for code in (error_codes or []) if code in MANUAL_ERROR_RULES]
    if manual_notes.strip():
        corrections.append(manual_notes.strip())
    if not corrections:
        return base_prompt
    return (
        f"{base_prompt.rstrip()}\n\nREVIEW CORRECTION REQUIREMENTS:\n\n"
        "MANUAL RETRY CONSTRAINT:\n- " + "\n- ".join(corrections)
    )


def build_batch_try_on_prompt(
    *, mode: str, garment_filename: str, template_name: str,
    garment_profile: dict[str, object] | None = None,
    template_profile: dict[str, object] | None = None,
    preset_selection: dict[str, object] | None = None,
    extra_requirements: str = "", manual_error_codes: list[str] | None = None,
    manual_notes: str = "", technical_delivery_contract: str = "",
) -> BatchTryOnPromptBundle:
    garment_profile = garment_profile or {}
    template_profile = template_profile or {}
    preset_selection = preset_selection or {}
    sections = [
        "AI VIRTUAL TRY-ON — CURRENT GARMENT AUTHORITY",
        f"Template: {template_name}. Current garment: {garment_filename}.",
        "The CURRENT GARMENT reference is the sole visual truth for garment color, graphics, text, numbers, names, logos, stripes, stitching, panels, neckline, sleeves, hem, silhouette and fabric appearance.",
        "Do not inherit any garment-specific visual detail from the first batch garment, the template garment, another garment, or any previous generated output.",
        "FRONT/BACK: preserve the current garment view and never swap front artwork with back artwork.",
        "LEFT/RIGHT SLEEVES: map artwork by wearer-left and wearer-right; do not mirror or swap asymmetric sleeve details.",
        "TYPOGRAPHY/NUMBER: reproduce visible text and numbers exactly, including spelling, font character, placement and leading zeros. Do not invent unreadable text.",
        "COLOR: match the current garment reference exactly and do not recolor from batch-level analysis.",
        "TEMPLATE FIT: keep the original model identity, face, hair, pose, body proportions and natural garment fit.",
        "OCCLUSION: preserve credible hand, hair, prop and body occlusion; do not paint garment details over occluding objects.",
    ]
    if garment_profile:
        sections.append(f"STRUCTURAL GUIDANCE ONLY (never visual inheritance): {garment_profile}")
    if mode == "detail_tryon":
        sections.extend([
            "MODE — DETAIL TRY-ON: use the detail template as the fixed composition authority.",
            f"Focus area: {template_profile.get('focus_area') or 'garment detail'}.",
            "Preserve the template crop, zoom, camera distance, camera angle, body framing, pose, background, lighting and composition.",
            f"Template analysis: {template_profile}",
        ])
    else:
        sections.extend([
            "MODE — NORMAL TRY-ON: replace only the worn garment with the current garment.",
            "Keep the model, pose, camera, background, lighting and overall composition unchanged unless an explicit preset allows a controlled change.",
            f"Template analysis: {template_profile}",
        ])
    selected = [f"{key}={value}" for key, value in sorted(preset_selection.items()) if value]
    if selected:
        sections.append("SELECTED PRESETS: " + "; ".join(selected))
    if extra_requirements.strip():
        sections.append("USER ADDITIONAL REQUIREMENTS (subordinate to fidelity rules): " + extra_requirements.strip())
    business = "\n\n".join(sections)
    business = append_manual_retry_constraints(
        business, error_codes=manual_error_codes, manual_notes=manual_notes,
    )
    technical = technical_delivery_contract.strip()
    effective = f"{business}\n\n{technical}" if technical else business
    return BatchTryOnPromptBundle(business, technical, effective)


def build_template_prompt_composed_prompt(
    *, template_type: str, reusable_final_prompt: str | None,
    garment_filename: str, template_name: str, extra_requirements: str = "",
    has_font_reference: bool = False,
    garment_reference_count: int = 1,
    technical_delivery_contract: str = "",
) -> BatchTryOnPromptBundle:
    """Compose one image job prompt from a confirmed reusable template prompt.

    The analysis instruction is intentionally not accepted by this function, so
    it cannot leak into an image-generation request.  Each template type owns a
    distinct composer branch; unsupported future types fail closed.
    """
    composer = TEMPLATE_TYPE_COMPOSERS.get(template_type)
    if composer is None:
        raise ValueError(f"unsupported batch try-on template type: {template_type}")
    reusable = str(reusable_final_prompt or "").strip() or str(composer["fallback"])
    sections = [
        str(composer["heading"]),
        f"Template reference: {template_name}. Current garment reference: {garment_filename}.",
        str(composer["authority"]),
        "The reusable prompt below describes the template transformation rules. Apply those rules to the CURRENT garment reference; never freeze or copy visual facts from the first garment used during prompt analysis.",
        reusable,
        "CURRENT-GARMENT OVERRIDE: reproduce the current garment's visible colors, graphics, text, numbers, names, logos, front/back design and asymmetric wearer-left/wearer-right sleeve details exactly. Current-garment evidence overrides any first-sample-specific detail that may appear in the reusable prompt.",
    ]
    if garment_reference_count > 1:
        sections.append(
            "REFERENCE IMAGE ORDER: Reference Image 2 is the clean front garment reference and "
            + ("Reference Image 4" if has_font_reference else "Reference Image 3")
            + " is the clean back garment reference. Keep front and back evidence separate; never mirror, swap, or mix them."
        )
        sections.append(
            "DUAL-VIEW AUTHORITY OVERRIDE: any singular statement above that calls Reference Image 2 the sole "
            "garment authority applies to the front view. The clean back reference is the sole authority for the "
            "back view. Together these two clean references are the only garment truth sources."
        )
    if has_font_reference:
        font_index = 3
        sections.append(
            f"REFERENCE IMAGE {font_index} — CUSTOM TYPOGRAPHY ONLY: use it only for the glyph shape, number outline, "
            f"stroke structure and layout of customized names, back numbers and shoulder numbers. Reference Image {font_index} "
            "must never override Reference Image 2 or any other garment reference image for garment color, graphics, logos, neckline, cuffs, silhouette, "
            "fabric construction or any other product structure."
        )
    if extra_requirements.strip():
        sections.append(
            f"USER ADDITIONAL REQUIREMENTS (subordinate to {composer['extra_scope']}): "
            + extra_requirements.strip()
        )
    business = "\n\n".join(sections)
    technical = technical_delivery_contract.strip()
    effective = f"{business}\n\n{technical}" if technical else business
    return BatchTryOnPromptBundle(business, technical, effective)
