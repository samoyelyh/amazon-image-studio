from __future__ import annotations


def build_material_extract_prompt(*, target_description: str, background_color: str) -> str:
    target = target_description.strip() or "the single object indicated by the user's marked selection"
    return (
        "Extract and faithfully reconstruct only the requested material from the provided cropped reference image.\n\n"
        f"Target material: {target}.\n"
        "The user's crop and brush selection are approximate localization hints, not permission to include nearby objects. "
        "Keep the complete target object, including thin edges, holes, straps, hair, fabric fibers and other fine boundary details. "
        "Preserve its exact colors, texture, graphics, text, proportions and visible shape. "
        "Remove every unrelated person, object, shadow, reflection and original background. "
        f"Render the target centered on one perfectly flat solid {background_color} background. "
        "The background must be uniform edge to edge, with no gradient, texture, shadow, glow, floor, border or transparency. "
        "Do not crop any part of the target. Do not add labels, decorations, mockups or new content. "
        "Return one standalone, high-detail image suitable for deterministic background-to-alpha conversion."
    )

