package dev.vyne

import android.content.Context
import java.util.concurrent.ConcurrentHashMap

/**
 * Process-once declarations of render surfaces contributed by extensions.
 *
 * Extensions implement [SurfaceRegistrant] and declare (name, pythonModule)
 * pairs; the generated registrant calls them during [AppBootstrap]'s
 * process-once registration, so a surface is available from ANY entry point
 * (MainActivity, receiver, service) without an Activity ever existing.
 *
 * A declaration is only a factory record — the actual [RenderSurface]
 * instance is created lazily by [surface] with the caller's context, so
 * consumers control which Context the Renderer is themed with.
 */
object RenderSurfaceRegistry {
    private val declarations = ConcurrentHashMap<String, String>()

    /** Declare one surface: *name* is the stable identity, *pythonModule* is
     *  the Chaquopy module that registers the surface app. */
    fun register(name: String, pythonModule: String) {
        val previous = declarations.putIfAbsent(name, pythonModule)
        check(previous == null || previous == pythonModule) {
            "Duplicate render surface declaration: $name"
        }
    }

    /** The declared Python module for *name*, or null when undeclared. */
    fun pythonModule(name: String): String? = declarations[name]

    /**
     * Create (or return the cached) surface instance for *name*.
     *
     * The instance is cached per process and bound to the first requesting
     * context; the Renderer is themed from *context*'s application context.
     * Returns null when *name* was never declared.
     */
    fun surface(name: String, context: Context): RenderSurface? {
        // The registry is populated during process-once registration; any
        // consumer (receiver, service, test) may be the first to trigger it.
        AppBootstrap.ensureRegistered(context)
        val moduleName = declarations[name] ?: return null
        return surfaces.compute(name) { _, existing ->
            // A disposed surface must not be reused: a fresh trigger after
            // dispose() re-creates the surface (new renderer, new bridge).
            if (existing != null && !existing.isDisposed) {
                existing
            } else {
                RenderSurface(
                    name,
                    moduleName,
                    context,
                    AppBootstrap.ensureRegistered(context),
                )
            }
        }
    }

    private val surfaces = ConcurrentHashMap<String, RenderSurface>()

    /** Dispose every live surface (process teardown, tests). */
    fun disposeAll() {
        surfaces.values.forEach { it.dispose() }
        surfaces.clear()
    }
}

/**
 * Optional extension hook: extensions that provide render surfaces implement
 * this and declare them via [RenderSurfaceRegistry.register]. The generated
 * registrant calls it through a safe cast, so extensions that predate the
 * interface compile unchanged.
 */
interface SurfaceRegistrant {
    fun registerSurfaces(registry: RenderSurfaceRegistry)
}
