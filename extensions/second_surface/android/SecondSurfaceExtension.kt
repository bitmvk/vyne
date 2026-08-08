/**
 * second_surface example — registration entry point.
 *
 * Declares two render surfaces and one custom kind:
 *
 * - "sms_overlay": the SMS-triggered WindowManager overlay. Triggered by
 *   SmsReceiver, which may cold-start the process with NO Activity.
 * - "lock_prompt": a showWhenLocked prompt Activity (fullscreen UI over
 *   the keyguard without unlocking or opening the main app).
 * - OverlayHost / PromptHost kinds: containers whose `dismiss_requested`
 *   prop tells the extension to tear down the attach point (remove the
 *   overlay window / finish the prompt activity) — the Python side drives
 *   window lifecycle through ordinary props.
 *
 * Everything here is extension-owned: the window, the permission flow,
 * the manifest declarations, the triggers.
 */
package dev.vyne.ext.second_surface

import android.content.Context
import android.widget.FrameLayout
import dev.vyne.ElementContext
import dev.vyne.ElementRegistry
import dev.vyne.ElementSpec
import dev.vyne.RenderSurfaceRegistry
import dev.vyne.SurfaceRegistrant

object SecondSurfaceExtension : SurfaceRegistrant {

    /** Register the overlay-host kinds (callable from the generated registrant). */
    internal fun register(context: Context, registry: ElementRegistry) {
        registry.register(
            ElementSpec(
                kind = "OverlayHost",
                create = { FrameLayout(it.context) },
                props =
                    mapOf(
                        "dismiss_requested" to
                            { _, view, value ->
                                if (value == true) {
                                    OverlayDismissal.find(view)?.invoke()
                                }
                            },
                    ),
                container = true,
            )
        )
        registry.register(
            ElementSpec(
                kind = "PromptHost",
                create = { FrameLayout(it.context) },
                props =
                    mapOf(
                        "dismiss_requested" to
                            { _, view, value ->
                                if (value == true) {
                                    OverlayDismissal.find(view)?.invoke()
                                }
                            },
                    ),
                container = true,
            )
        )
    }

    /** Declare the render surfaces (generated registrant calls this). */
    override fun registerSurfaces(registry: RenderSurfaceRegistry) {
        registry.register("sms_overlay", "second_surface")
        registry.register("lock_prompt", "second_surface_prompt")
    }
}
