package dev.vyne

import android.content.Context
import dev.vyne.generated.registerAppExtensions
import dev.vyne.generated.registerAppSurfaces

/**
 * Process-once framework bootstrap, reachable from ANY entry point.
 *
 * MainActivity historically owned registration: it built the frozen element
 * registry (core + extensions) during onCreate. That made the registry
 * unavailable to receiver/service-started processes where no Activity ever
 * exists. [ensureRegistered] is idempotent and lazily triggered by
 * MainActivity, RenderSurfaceRegistry, or any consumer, so extension
 * registration side effects run exactly once per process no matter which
 * component started it.
 */
internal object AppBootstrap {
    private val lock = Any()
    @Volatile private var sharedRegistry: ElementRegistry? = null

    /** Build the process registry and populate the surface registry once. */
    fun ensureRegistered(context: Context): ElementRegistry {
        sharedRegistry?.let { return it }
        synchronized(lock) {
            sharedRegistry?.let { return it }
            val registry = defaultRegistry(context.applicationContext)
            sharedRegistry = registry
            registerAppSurfaces(RenderSurfaceRegistry)
            return registry
        }
    }
}
