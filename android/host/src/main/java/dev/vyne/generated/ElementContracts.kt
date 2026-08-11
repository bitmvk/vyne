/** Generated Vyne element property contracts.
 * DO NOT EDIT. Generated from vyne.spec.schema_v2 (hash=80b7188c2d24d6c0).
 */
package dev.vyne.generated

object ElementContracts {
    const val SCHEMA_HASH = "80b7188c2d24d6c0"

    val KINDS: Set<String> = setOf(
        "Box",
        "Layout",
        "Scroll",
        "HorizontalScroll",
        "Text",
        "TextInput",
        "Image",
        "Path",
        "Canvas",
    )

    val ALL_PROPS_BY_KIND: Map<String, Set<String>> = mapOf(
        "Box" to setOf("_virtual_content", "_virtual_sticky_boundary_end", "_virtual_sticky_boundary_start", "_virtual_sticky_edge", "accessibility_checked", "accessibility_range_current", "accessibility_range_max", "accessibility_range_min", "accessibility_role", "accessibility_selected", "accessibility_state_description", "align_items", "background_color", "border_color", "border_width", "clickable", "content_description", "corner_radius_bottom_left", "corner_radius_bottom_right", "corner_radius_top_left", "corner_radius_top_right", "elevation", "enabled", "focusable", "height", "justify_content", "lp_gravity", "lp_weight", "margin_bottom", "margin_end", "margin_start", "margin_top", "max_height", "max_width", "min_height", "min_width", "opacity", "overflow", "padding_bottom", "padding_end", "padding_start", "padding_top", "pointer_capture_axis", "ripple_color", "rotation", "rotation_x", "rotation_y", "safe_area", "scale_x", "scale_y", "text_alignment", "text_direction", "translation_x", "translation_y", "visible", "width"),
        "Layout" to setOf("accessibility_checked", "accessibility_range_current", "accessibility_range_max", "accessibility_range_min", "accessibility_role", "accessibility_selected", "accessibility_state_description", "align_items", "background_color", "border_color", "border_width", "clickable", "content_description", "corner_radius_bottom_left", "corner_radius_bottom_right", "corner_radius_top_left", "corner_radius_top_right", "elevation", "enabled", "focusable", "height", "justify_content", "lp_gravity", "lp_weight", "margin_bottom", "margin_end", "margin_start", "margin_top", "max_height", "max_width", "min_height", "min_width", "opacity", "orientation", "overflow", "padding_bottom", "padding_end", "padding_start", "padding_top", "pointer_capture_axis", "ripple_color", "rotation", "rotation_x", "rotation_y", "safe_area", "scale_x", "scale_y", "text_alignment", "text_direction", "translation_x", "translation_y", "visible", "width"),
        "Scroll" to setOf("_virtual_list_initial_offset", "accessibility_checked", "accessibility_range_current", "accessibility_range_max", "accessibility_range_min", "accessibility_role", "accessibility_selected", "accessibility_state_description", "align_items", "background_color", "border_color", "border_width", "clickable", "content_description", "corner_radius_bottom_left", "corner_radius_bottom_right", "corner_radius_top_left", "corner_radius_top_right", "elevation", "enabled", "focusable", "height", "justify_content", "lp_gravity", "lp_weight", "margin_bottom", "margin_end", "margin_start", "margin_top", "max_height", "max_width", "min_height", "min_width", "opacity", "overflow", "padding_bottom", "padding_end", "padding_start", "padding_top", "pointer_capture_axis", "ripple_color", "rotation", "rotation_x", "rotation_y", "safe_area", "scale_x", "scale_y", "text_alignment", "text_direction", "translation_x", "translation_y", "visible", "width"),
        "HorizontalScroll" to setOf("_virtual_list_initial_offset", "accessibility_checked", "accessibility_range_current", "accessibility_range_max", "accessibility_range_min", "accessibility_role", "accessibility_selected", "accessibility_state_description", "align_items", "background_color", "border_color", "border_width", "clickable", "content_description", "corner_radius_bottom_left", "corner_radius_bottom_right", "corner_radius_top_left", "corner_radius_top_right", "elevation", "enabled", "focusable", "height", "justify_content", "lp_gravity", "lp_weight", "margin_bottom", "margin_end", "margin_start", "margin_top", "max_height", "max_width", "min_height", "min_width", "opacity", "overflow", "padding_bottom", "padding_end", "padding_start", "padding_top", "pointer_capture_axis", "ripple_color", "rotation", "rotation_x", "rotation_y", "safe_area", "scale_x", "scale_y", "text_alignment", "text_direction", "translation_x", "translation_y", "visible", "width"),
        "Text" to setOf("accessibility_checked", "accessibility_range_current", "accessibility_range_max", "accessibility_range_min", "accessibility_role", "accessibility_selected", "accessibility_state_description", "background_color", "border_color", "border_width", "clickable", "content_description", "corner_radius_bottom_left", "corner_radius_bottom_right", "corner_radius_top_left", "corner_radius_top_right", "elevation", "enabled", "focusable", "font_size", "height", "include_font_padding", "line_height", "lp_gravity", "lp_weight", "margin_bottom", "margin_end", "margin_start", "margin_top", "min_height", "min_width", "opacity", "padding_bottom", "padding_end", "padding_start", "padding_top", "pointer_capture_axis", "ripple_color", "rotation", "rotation_x", "rotation_y", "safe_area", "scale_x", "scale_y", "text", "text_alignment", "text_color", "text_direction", "translation_x", "translation_y", "visible", "width"),
        "TextInput" to setOf("accessibility_checked", "accessibility_range_current", "accessibility_range_max", "accessibility_range_min", "accessibility_role", "accessibility_selected", "accessibility_state_description", "background_color", "blur_on_keyboard_hide", "blur_on_submit", "blur_on_tap_outside", "border_color", "border_width", "clickable", "content_description", "corner_radius_bottom_left", "corner_radius_bottom_right", "corner_radius_top_left", "corner_radius_top_right", "elevation", "enabled", "focusable", "focused", "font_size", "height", "hint", "lp_gravity", "lp_weight", "margin_bottom", "margin_end", "margin_start", "margin_top", "min_height", "min_width", "opacity", "padding_bottom", "padding_end", "padding_start", "padding_top", "pointer_capture_axis", "ripple_color", "rotation", "rotation_x", "rotation_y", "safe_area", "scale_x", "scale_y", "text", "text_alignment", "text_color", "text_direction", "translation_x", "translation_y", "visible", "width"),
        "Image" to setOf("accessibility_checked", "accessibility_range_current", "accessibility_range_max", "accessibility_range_min", "accessibility_role", "accessibility_selected", "accessibility_state_description", "background_color", "border_color", "border_width", "clickable", "content_description", "corner_radius_bottom_left", "corner_radius_bottom_right", "corner_radius_top_left", "corner_radius_top_right", "elevation", "enabled", "focusable", "height", "lp_gravity", "lp_weight", "margin_bottom", "margin_end", "margin_start", "margin_top", "min_height", "min_width", "opacity", "padding_bottom", "padding_end", "padding_start", "padding_top", "pointer_capture_axis", "ripple_color", "rotation", "rotation_x", "rotation_y", "safe_area", "scale_type", "scale_x", "scale_y", "source", "text_alignment", "text_direction", "translation_x", "translation_y", "visible", "width"),
        "Path" to setOf("accessibility_checked", "accessibility_range_current", "accessibility_range_max", "accessibility_range_min", "accessibility_role", "accessibility_selected", "accessibility_state_description", "background_color", "border_color", "border_width", "clickable", "commands", "content_description", "corner_radius_bottom_left", "corner_radius_bottom_right", "corner_radius_top_left", "corner_radius_top_right", "elevation", "enabled", "fill_color", "focusable", "height", "lp_gravity", "lp_weight", "margin_bottom", "margin_end", "margin_start", "margin_top", "min_height", "min_width", "opacity", "padding_bottom", "padding_end", "padding_start", "padding_top", "pointer_capture_axis", "ripple_color", "rotation", "rotation_x", "rotation_y", "safe_area", "scale_x", "scale_y", "stroke_color", "stroke_dash_array", "stroke_dash_offset", "stroke_line_cap", "stroke_line_join", "stroke_width", "text_alignment", "text_direction", "translation_x", "translation_y", "visible", "width"),
        "Canvas" to setOf("accessibility_checked", "accessibility_range_current", "accessibility_range_max", "accessibility_range_min", "accessibility_role", "accessibility_selected", "accessibility_state_description", "background_color", "border_color", "border_width", "clickable", "content_description", "corner_radius_bottom_left", "corner_radius_bottom_right", "corner_radius_top_left", "corner_radius_top_right", "draw", "elevation", "enabled", "focusable", "height", "lp_gravity", "lp_weight", "margin_bottom", "margin_end", "margin_start", "margin_top", "min_height", "min_width", "opacity", "padding_bottom", "padding_end", "padding_start", "padding_top", "pointer_capture_axis", "ripple_color", "rotation", "rotation_x", "rotation_y", "safe_area", "scale_x", "scale_y", "text_alignment", "text_direction", "translation_x", "translation_y", "view_box", "visible", "width"),
    )

    val GENERIC_PROPS: Set<String> = setOf(
        "accessibility_checked",
        "accessibility_range_current",
        "accessibility_range_max",
        "accessibility_range_min",
        "accessibility_role",
        "accessibility_selected",
        "accessibility_state_description",
        "background_color",
        "border_color",
        "border_width",
        "clickable",
        "content_description",
        "corner_radius_bottom_left",
        "corner_radius_bottom_right",
        "corner_radius_top_left",
        "corner_radius_top_right",
        "elevation",
        "enabled",
        "focusable",
        "height",
        "lp_gravity",
        "lp_weight",
        "margin_bottom",
        "margin_end",
        "margin_start",
        "margin_top",
        "min_height",
        "min_width",
        "opacity",
        "padding_bottom",
        "padding_end",
        "padding_start",
        "padding_top",
        "pointer_capture_axis",
        "ripple_color",
        "rotation",
        "rotation_x",
        "rotation_y",
        "safe_area",
        "scale_x",
        "scale_y",
        "text_alignment",
        "text_direction",
        "translation_x",
        "translation_y",
        "visible",
        "width",
    )

    val ANIMATABLE_PROPS: Set<String> = setOf(
        "elevation",
        "height",
        "opacity",
        "rotation",
        "rotation_x",
        "rotation_y",
        "scale_x",
        "scale_y",
        "stroke_dash_offset",
        "translation_x",
        "translation_y",
        "width",
    )

    val BOX_EVENTS: Set<String> = setOf("accessibility_progress", "click", "layout_metrics", "long_click", "pointer_cancel", "pointer_down", "pointer_move", "pointer_up")
    val LAYOUT_EVENTS: Set<String> = setOf("accessibility_progress", "click", "layout_metrics", "long_click", "pointer_cancel", "pointer_down", "pointer_move", "pointer_up")
    val SCROLL_EVENTS: Set<String> = setOf("accessibility_progress", "click", "layout_metrics", "long_click", "pointer_cancel", "pointer_down", "pointer_move", "pointer_up", "scroll_metrics")
    val HORIZONTALSCROLL_EVENTS: Set<String> = setOf("accessibility_progress", "click", "layout_metrics", "long_click", "pointer_cancel", "pointer_down", "pointer_move", "pointer_up", "scroll_metrics")
    val TEXT_EVENTS: Set<String> = setOf("accessibility_progress", "click", "layout_metrics", "long_click", "pointer_cancel", "pointer_down", "pointer_move", "pointer_up")
    val TEXTINPUT_EVENTS: Set<String> = setOf("accessibility_progress", "click", "editor_action", "focus_change", "layout_metrics", "long_click", "pointer_cancel", "pointer_down", "pointer_move", "pointer_up", "text_change")
    val IMAGE_EVENTS: Set<String> = setOf("accessibility_progress", "click", "layout_metrics", "long_click", "pointer_cancel", "pointer_down", "pointer_move", "pointer_up")
    val PATH_EVENTS: Set<String> = setOf("accessibility_progress", "click", "layout_metrics", "long_click", "pointer_cancel", "pointer_down", "pointer_move", "pointer_up")
    val CANVAS_EVENTS: Set<String> = setOf("accessibility_progress", "click", "layout_metrics", "long_click", "pointer_cancel", "pointer_down", "pointer_move", "pointer_up")

    val ALL_EVENT_NAMES: Set<String> = setOf(
        "accessibility_progress",
        "click",
        "editor_action",
        "focus_change",
        "layout_metrics",
        "long_click",
        "pointer_cancel",
        "pointer_down",
        "pointer_move",
        "pointer_up",
        "scroll_metrics",
        "text_change",
    )

    val ALL_EVENTS_BY_KIND: Map<String, Set<String>> = mapOf(
        "Box" to BOX_EVENTS,
        "Layout" to LAYOUT_EVENTS,
        "Scroll" to SCROLL_EVENTS,
        "HorizontalScroll" to HORIZONTALSCROLL_EVENTS,
        "Text" to TEXT_EVENTS,
        "TextInput" to TEXTINPUT_EVENTS,
        "Image" to IMAGE_EVENTS,
        "Path" to PATH_EVENTS,
        "Canvas" to CANVAS_EVENTS,
    )

}
