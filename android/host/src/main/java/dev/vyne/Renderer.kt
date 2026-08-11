/**
 * Central renderer that applies Python commits to Android Views.
 *
 * The Renderer is the Android counterpart of the Python Runtime.  It receives
 * commit messages (JSON or binary) containing a sequence of operations — create,
 * set_props, insert_child, motion_set_target, etc. — and applies them directly to
 * native Android Views.  There is no virtual DOM on this side; the Renderer
 * trusts the Python diff and mechanically executes the ops.
 *
 * Design principles:
 * - **Stateless beyond view state**: The Renderer keeps a mutable model of view
 *   properties (ViewState, NodeLayout, etc.) to support property remove/reset
 *   and composite background generation (color + border + corner radii + ripple).
 * - **Event backpressure**: Events from native widgets are sent to Python
 *   immediately when its executor is idle. While one dispatch is in flight,
 *   MainActivity queues ordered events and coalesces `latest` events; the
 *   Renderer just calls the eventSink callback.
 * - **Animation**: Uses the unified ``PresentationEngine`` with one frame
 *   clock and one physics implementation for both View properties and Canvas
 *   operations.  Python owns motion policy; Kotlin mechanically integrates.
 * - **Generic props**: Common properties like width, height, padding, background,
 *   etc. are handled in a central `handleGenericProp` switch instead of being
 *   scattered across widget-specific prop handlers.
 */
package dev.vyne

import android.annotation.SuppressLint
import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Outline
import android.graphics.Path
import android.graphics.drawable.Drawable
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.os.Build
import android.os.Bundle
import android.os.SystemClock
import android.text.Editable
import android.text.TextWatcher
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.ViewGroup
import android.view.ViewOutlineProvider
import android.view.WindowInsets
import android.view.accessibility.AccessibilityNodeInfo
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import dev.vyne.generated.ElementContracts
import org.json.JSONArray
import org.json.JSONObject

internal class Renderer(
    context: Context,
    private val eventSink: (NativeEvent) -> Unit,
    private val applyResultSink: ((ApplyResult, revision: Long?) -> Unit)? = null,
    private val registry: ElementRegistry = defaultRegistry(context),
) : PropertyHost {
    val root: FrameLayout = FrameLayout(context)

    private val nativeTree = NativeTree(root)
    private val views get() = nativeTree.views
    private val specs get() = nativeTree.specs
    private val propMementos get() = nativeTree.propMementos
    private val parentOf get() = nativeTree.parentOf
    private val childrenOf get() = nativeTree.childrenOf
    private val eventBindings = EventBindings()
    override val viewStates get() = nativeTree.viewStates
    /**
     * Detached-view reuse for cell windows. Python still decides which window
     * is rendered; this only makes mounting it cheap (and GC-free).
     */
    private val viewPool = ViewPool(maxPerKind = 32)
    /**
     * Props of a reused view that still need resetting to defaults: the old
     * cell's props minus the props the new cell explicitly sets. List cells
     * are homogeneous, so this is usually empty and costs nothing.
     */
    private val pendingResets = mutableMapOf<Int, MutableSet<String>>()
    /**
     * Theme defaults captured from the first pristine instance of each kind.
     * A recycled TextView may carry a styled color/size, so the pristine
     * defaults must outlive any single view instance.
     */
    private val defaultTextColorsByKind =
        mutableMapOf<String, android.content.res.ColorStateList?>()
    private val defaultTextSizesByKind = mutableMapOf<String, Float?>()
    private val imageDecoder = ImageDecoder()
    private val presentationEngine =
        PresentationEngine(lifecycleSink = ::emitAnimationLifecycle)
    private val declarativeAnimatedProps = mutableSetOf<Pair<Int, String>>()
    private val declarativeCanvasSlots = mutableMapOf<Int, MutableSet<String>>()
    private val animatedDriverValues = mutableMapOf<Long, Float>()
    private val animatedBindings = mutableMapOf<String, AnimatedBinding>()
    private val animatedBindingSlotsByDriver =
        mutableMapOf<Long, MutableSet<String>>()
    /**
     * Result of a native commit application.
     *
     * Python uses this to decide whether to advance the mirror or enter recovery.
     */
    enum class ApplyResult {
        /** All operations applied successfully. */
        OK,
        /**
         * Preflight rejected — no state was mutated, prior revision is known-good.
         * Python can replan and resend.
         */
        REJECTED_KNOWN,
        /**
         * Rollback succeeded — all applied ops were undone, prior revision is known-good.
         * Python can replan and resend.
         */
        PARTIAL,
        /**
         * Catastrophic failure — native state is unknown, resync via snapshot required.
         * Python must send a complete snapshot, not incrementals.
         */
        UNKNOWN,
    }

    private val transactionApplier = RenderTransactionApplier(
        preflight = ::preflightOps,
        digest = ::mechanicalDigest,
        applyOperation = ::applyOperation,
    )
    private val applyingCommit: Boolean
        get() = transactionApplier.applying
    private var nextPointerGestureId = 1L
    private val touchSlop = ViewConfiguration.get(context).scaledTouchSlop.toFloat()
    private val inputController =
        InputController(
            root = root,
            stateFor = ::stateFor,
            viewFor = views::get,
            isDisposed = { disposed },
        )

    init {
        root.isFocusable = true
        root.isFocusableInTouchMode = true
        inputController.install()
    }

    internal val registryAccessor: ElementRegistry get() = registry

    /** Detached views currently held for reuse (test observability). */
    internal val recycledViewCount: Int
        get() = viewPool.size

    internal fun viewForTest(id: Int): View? = views[id]

    fun dispose() {
        if (disposed) return
        disposed = true

        // Cancel all running presentations via the unified engine.
        presentationEngine.dispose()
        declarativeAnimatedProps.clear()
        declarativeCanvasSlots.clear()
        animatedDriverValues.clear()
        animatedBindings.clear()
        animatedBindingSlotsByDriver.clear()
        eventBindings.clear().forEach { detach ->
            runCatching { detach() }
        }

        inputController.dispose()
        imageDecoder.dispose()

        // Detach all event listeners and text watchers.
        for ((id, view) in views) {
            val state = viewStates[id] ?: continue
            state.textWatcher?.let { (view as? EditText)?.removeTextChangedListener(it) }
            view.setOnClickListener(null)
            view.setOnLongClickListener(null)
            view.setOnFocusChangeListener(null)
            view.setOnTouchListener(null)
            view.setOnApplyWindowInsetsListener(null)
            if (view is EditText) {
                view.setOnEditorActionListener(null)
            }
        }

        // Clear all state maps.
        viewStates.clear()
        viewPool.clear()
        views.clear()
        specs.clear()
        parentOf.clear()
        childrenOf.clear()
        eventBindings.clear()

        // Remove all children from root.
        root.removeAllViews()
    }

    internal var disposed = false
        private set

    fun handleTouchEvent(event: MotionEvent) {
        inputController.handleTouchEvent(event)
    }

    /**
     * Apply a renderer-internal transaction.
     *
     * Direct Chaquopy calls enter here after building an immutable transaction.
     */
    internal fun applyDirectTransaction(transaction: RenderTransaction): ApplyResult {
        if (disposed) return ApplyResult.UNKNOWN
        val result = applyTransaction(transaction.operations)
        applyResultSink?.invoke(result, transaction.revision)
        return result
    }

    /**
     * Apply a commit with preflight validation and journalled rollback.
     *
     * 1. Preflight: validate every operation against generated contracts
     *    before touching any View.  Rejections return REJECTED_KNOWN.
     * 2. Apply: each op is journalled with undo before execution.
     * 3. Rollback: on failure, journal is replayed in reverse.
     *    If rollback succeeds, return PARTIAL (known-good).
     *    If rollback fails, return UNKNOWN (force snapshot).
     */
    private fun applyTransaction(operations: List<RenderOperation>): ApplyResult {
        val result = transactionApplier.apply(operations)
        if (result != ApplyResult.OK) return result
        return try {
            pruneUnboundAnimatedDrivers()
            ApplyResult.OK
        } catch (_: Throwable) {
            ApplyResult.UNKNOWN
        }
    }

    private fun mechanicalDigest(): String {
        val idsByView = views.entries.associate { (id, view) -> view to id }
        return buildString {
            for (id in views.keys.sorted()) {
                val view = views[id] ?: continue
                append(id).append(':').append(specs[id]?.kind ?: "root")
                append(':').append(parentOf[id] ?: -1)
                val group = view as? ViewGroup
                if (group != null) {
                    append('[')
                    for (index in 0 until group.childCount) {
                        val child = group.getChildAt(index)
                        append(idsByView[child] ?: -1).append(',')
                    }
                    append(']')
                }
                append(':').append(view.visibility).append(':').append(view.isEnabled)
                append(':').append(view.alpha).append(':').append(view.rotation)
                append(':').append(view.scaleX).append(':').append(view.scaleY)
                append(':').append((view as? TextView)?.text?.toString().orEmpty())
                append(';')
            }
            for ((key, record) in eventBindings.records.toSortedMap(
                compareBy({ it.first }, { it.second }),
            )) {
                append("L:").append(key.first).append(':').append(key.second)
                append(':').append(record.handler).append(':').append(record.delivery).append(';')
            }
        }
    }

    /**
     * Preflight every operation before any View mutation.
     *
     * Validates:
     * - Op type is known
     * - Kind names are in ElementContracts.KINDS
     * - Prop names are in the applicable kind's prop set
     * - Required fields (id, kind, name, etc.) are present
     *
     * @throws IllegalArgumentException if any op is invalid
     */
    private fun preflightOps(operations: List<RenderOperation>) {
        // Track kinds for ids created within this batch so that
        // set_props/set_prop/remove_prop ops following a create can
        // validate against the correct kind even before apply.
        val pendingKinds = specs.mapValues { it.value.kind }.toMutableMap()
        val shadowParent = parentOf.toMutableMap()
        val shadowChildren = mutableMapOf<Int, MutableList<Int>>()
        val idsByView = views.entries.associate { (id, view) -> view to id }
        for ((parent, children) in childrenOf) {
            val group = views[parent] as? ViewGroup
            shadowChildren[parent] = if (group != null) {
                (0 until group.childCount).mapNotNull { index ->
                    idsByView[group.getChildAt(index)]
                }.toMutableList()
            } else children.toMutableList()
        }
        shadowChildren.putIfAbsent(0, mutableListOf())

        fun requireKnownProperty(id: Int, name: String) {
            val kind = pendingKinds[id]
                ?: throw IllegalArgumentException("preflight: unknown id $id")
            if (name.isNotEmpty() && !registry.isValidProp(name, kind)) {
                throw IllegalArgumentException(
                    "preflight: prop '$name' not in contract for kind '$kind'"
                )
            }
        }

        fun preflightInsert(parent: Int, child: Int, index: Int, move: Boolean) {
            require(parent == 0 || parent in pendingKinds) {
                "preflight: unknown parent"
            }
            if (parent != 0) {
                val parentKind = pendingKinds.getValue(parent)
                require(registry.isContainer(parentKind)) {
                    "preflight: kind '$parentKind' cannot contain children"
                }
            }
            require(child in pendingKinds && child != parent) {
                "preflight: unknown/cyclic child"
            }
            val children = shadowChildren.getOrPut(parent) { mutableListOf() }
            if (!move) {
                require(child !in shadowParent && index in 0..children.size) {
                    "preflight: invalid insert"
                }
                children.add(index, child)
                shadowParent[child] = parent
            } else {
                require(shadowParent[child] == parent && index in children.indices) {
                    "preflight: invalid move"
                }
                children.remove(child)
                children.add(index, child)
            }
        }

        fun preflightRemove(id: Int) {
            require(id in pendingKinds && id !in shadowParent) {
                "preflight: remove attached/unknown id"
            }

            // remove(id) is recursive: only the subtree root must be
            // detached from its external parent. Internal descendants
            // remain attached to that root and are destroyed with it.
            val subtree = mutableListOf(id)
            val seen = mutableSetOf<Int>()
            var cursor = 0
            while (cursor < subtree.size) {
                val current = subtree[cursor++]
                require(seen.add(current)) {
                    "preflight: cycle in subtree rooted at $id"
                }
                for (child in shadowChildren[current].orEmpty()) {
                    require(shadowParent[child] == current) {
                        "preflight: inconsistent subtree parent for $child"
                    }
                    subtree.add(child)
                }
            }
            for (removedId in subtree) {
                pendingKinds.remove(removedId)
                shadowParent.remove(removedId)
                shadowChildren.remove(removedId)
            }
        }

        for (operation in operations) {
            when (operation) {
                is RenderOperation.Create -> {
                    if (!registry.hasKind(operation.kind)) {
                        throw IllegalArgumentException(
                            "preflight: unknown kind '${operation.kind}'"
                        )
                    }
                    require(operation.id > 0 && operation.id !in pendingKinds) {
                        "preflight: duplicate/invalid id ${operation.id}"
                    }
                    pendingKinds[operation.id] = operation.kind
                    shadowChildren[operation.id] = mutableListOf()
                }
                is RenderOperation.SetProps -> {
                    val kind = pendingKinds[operation.id]
                        ?: throw IllegalArgumentException(
                            "preflight: unknown id ${operation.id}"
                        )
                    preflightProps(kind, operation.props.keys)
                }
                is RenderOperation.SetProp ->
                    requireKnownProperty(operation.id, operation.name)
                is RenderOperation.SetPropBatch -> {
                    require(
                        operation.ids.size == operation.names.size &&
                            operation.ids.size == operation.values.size
                    ) {
                        "preflight: property batch column lengths differ"
                    }
                    for (index in operation.ids.indices) {
                        requireKnownProperty(
                            operation.ids[index],
                            operation.names[index],
                        )
                    }
                }
                is RenderOperation.SetStringPropBatch -> {
                    require(operation.ids.size == operation.values.size) {
                        "preflight: string property batch column lengths differ"
                    }
                    for (id in operation.ids) {
                        requireKnownProperty(id, operation.name)
                    }
                }
                is RenderOperation.SetContiguousStringPropBatch -> {
                    require(
                        operation.firstId >= 0 &&
                            operation.values.size <= Int.MAX_VALUE - operation.firstId
                    ) {
                        "preflight: contiguous property ids overflow Int"
                    }
                    for (index in operation.values.indices) {
                        requireKnownProperty(operation.firstId + index, operation.name)
                    }
                }
                is RenderOperation.RemoveProp ->
                    requireKnownProperty(operation.id, operation.name)
                is RenderOperation.Listen -> {
                    require(operation.id in pendingKinds) {
                        "preflight: listener unknown id"
                    }
                    require(operation.handler >= 0) {
                        "preflight: invalid handler"
                    }
                    require(operation.delivery == "all" || operation.delivery == "latest") {
                        "preflight: invalid delivery"
                    }
                    val kind = pendingKinds.getValue(operation.id)
                    require(registry.isValidEvent(kind, operation.event)) {
                        "preflight: event '${operation.event}' not in contract " +
                            "for kind '$kind'"
                    }
                }
                is RenderOperation.Unlisten -> {
                    val kind = pendingKinds[operation.id]
                    if (kind != null) {
                        require(registry.isValidEvent(kind, operation.event)) {
                            "preflight: event '${operation.event}' not in contract " +
                                "for kind '$kind'"
                        }
                    }
                }
                is RenderOperation.InsertChild ->
                    preflightInsert(
                        operation.parent,
                        operation.child,
                        operation.index,
                        move = false,
                    )
                is RenderOperation.MoveChild ->
                    preflightInsert(
                        operation.parent,
                        operation.child,
                        operation.index,
                        move = true,
                    )
                is RenderOperation.RemoveChild -> {
                    require(shadowParent[operation.child] == operation.parent) {
                        "preflight: wrong child parent"
                    }
                    shadowChildren[operation.parent]?.remove(operation.child)
                    shadowParent.remove(operation.child)
                }
                is RenderOperation.Remove ->
                    preflightRemove(operation.id)
                is RenderOperation.Clear -> {
                    require(operation.id == 0) {
                        "preflight: clear requires root id 0"
                    }
                    pendingKinds.clear()
                    shadowParent.clear()
                    shadowChildren.clear()
                    shadowChildren[0] = mutableListOf()
                }
                is RenderOperation.ScrollTo -> {
                    require(
                        pendingKinds[operation.id] in
                            setOf("Scroll", "HorizontalScroll")
                    ) {
                        "preflight: scroll_to target must be a scroll container"
                    }
                    require(
                        operation.offsetX.isFinite() &&
                            operation.offsetX >= 0f &&
                            operation.offsetY.isFinite() &&
                            operation.offsetY >= 0f
                    ) {
                        "preflight: scroll_to offsets must be finite and non-negative"
                    }
                }
                is RenderOperation.MotionSetTarget -> {
                    val kind =
                        pendingKinds[operation.nodeId]
                            ?: throw IllegalArgumentException(
                                "preflight: animation unknown id ${operation.nodeId}",
                            )
                    require(operation.animationId > 0L) {
                        "preflight: animation id must be positive"
                    }
                    require(
                        operation.targets.isNotEmpty() &&
                            operation.targets.all(Float::isFinite),
                    ) {
                        "preflight: animation targets must be finite"
                    }
                    require(operation.fromValue?.isFinite() != false) {
                        "preflight: animation from-value must be finite"
                    }
                    require(operation.specType == "tween" || operation.specType == "spring") {
                        "preflight: invalid animation spec"
                    }
                    require(operation.durationMs >= 0L) {
                        "preflight: negative animation duration"
                    }
                    require(
                        operation.dampingRatio.isFinite() &&
                            operation.dampingRatio > 0f &&
                            operation.stiffness.isFinite() &&
                            operation.stiffness > 0f &&
                            operation.restValueThreshold.isFinite() &&
                            operation.restValueThreshold >= 0f &&
                            operation.restVelocityThreshold.isFinite() &&
                            operation.restVelocityThreshold >= 0f,
                    ) {
                        "preflight: invalid spring parameters"
                    }
                    require(
                        operation.retargetPolicy in
                            setOf(
                                "restart",
                                "maintain_velocity",
                                "snap_to_end",
                                "ignore",
                            ),
                    ) {
                        "preflight: invalid retarget policy"
                    }
                    if (operation.specType == "tween") {
                        require(operation.easing in MOTION_EASINGS) {
                            "preflight: invalid easing"
                        }
                    }
                    val expectedSlot =
                        if (operation.slotId == null) {
                            require(
                                operation.property in
                                    dev.vyne.generated.ElementContracts.ANIMATABLE_PROPS &&
                                    registry.isValidProp(operation.property, kind),
                            ) {
                                "preflight: property '${operation.property}' " +
                                    "is not animatable for $kind"
                            }
                            "view:${operation.nodeId}:prop:${operation.property}"
                        } else {
                            require(
                                kind == "Canvas" &&
                                    operation.property in CANVAS_ANIMATABLE_FIELDS,
                            ) {
                                "preflight: invalid Canvas animation slot"
                            }
                            "view:${operation.nodeId}:slot:" +
                                "${operation.slotId}:${operation.property}"
                        }
                    require(operation.slotKey == expectedSlot) {
                        "preflight: animation slot key mismatch"
                    }
                    validateAnimationDomain(operation.property, operation.targets)
                    operation.fromValue?.let {
                        validateAnimationDomain(operation.property, listOf(it))
                    }
                }
                is RenderOperation.MotionCancel -> {
                    require(operation.animationId > 0L) {
                        "preflight: cancellation animation id must be positive"
                    }
                    require(operation.slotKey.isNotBlank()) {
                        "preflight: cancellation slot key must not be blank"
                    }
                }
                is RenderOperation.MotionDriverSetTarget -> {
                    require(pendingKinds.containsKey(operation.nodeId)) {
                        "preflight: animation unknown id ${operation.nodeId}"
                    }
                    require(operation.animationId > 0L && operation.driverId > 0L) {
                        "preflight: driver and animation ids must be positive"
                    }
                    require(operation.property.isNotBlank()) {
                        "preflight: driver lifecycle property must not be blank"
                    }
                    require(
                        operation.targets.isNotEmpty() &&
                            operation.targets.all(Float::isFinite),
                    ) {
                        "preflight: driver targets must be finite"
                    }
                    require(operation.fromValue?.isFinite() != false) {
                        "preflight: driver from-value must be finite"
                    }
                    require(
                        operation.specType == "tween" ||
                            operation.specType == "spring",
                    ) {
                        "preflight: invalid driver animation spec"
                    }
                    require(operation.durationMs >= 0L) {
                        "preflight: negative driver animation duration"
                    }
                    require(
                        operation.dampingRatio.isFinite() &&
                            operation.dampingRatio > 0f &&
                            operation.stiffness.isFinite() &&
                            operation.stiffness > 0f &&
                            operation.restValueThreshold.isFinite() &&
                            operation.restValueThreshold >= 0f &&
                            operation.restVelocityThreshold.isFinite() &&
                            operation.restVelocityThreshold >= 0f,
                    ) {
                        "preflight: invalid driver spring parameters"
                    }
                    require(
                        operation.retargetPolicy in
                            setOf(
                                "restart",
                                "maintain_velocity",
                                "snap_to_end",
                                "ignore",
                            ),
                    ) {
                        "preflight: invalid driver retarget policy"
                    }
                    if (operation.specType == "tween") {
                        require(operation.easing in MOTION_EASINGS) {
                            "preflight: invalid driver easing"
                        }
                    }
                }
                is RenderOperation.MotionDriverCancel -> {
                    require(operation.animationId > 0L && operation.driverId > 0L) {
                        "preflight: driver cancellation ids must be positive"
                    }
                }
            }
        }
    }

    private fun preflightProps(kind: String, names: Iterable<String>) {
        for (name in names) {
            if (!registry.isValidProp(name, kind)) {
                throw IllegalArgumentException(
                    "preflight: prop '$name' not in contract for kind '$kind'"
                )
            }
        }
    }

    private fun validateAnimationDomain(
        property: String,
        targets: List<Float>,
    ) {
        when (property) {
            "opacity", "trim_start", "trim_end" ->
                require(targets.all { it in 0f..1f }) {
                    "preflight: $property animation must remain between 0 and 1"
                }
            "elevation", "width", "height", "radius", "r", "stroke_width" ->
                require(targets.all { it >= 0f }) {
                    "preflight: $property animation must be non-negative"
                }
        }
    }

    /** Dispatch a typed operation through the shared journalled renderer path. */
    private fun applyOperation(operation: RenderOperation) {
        when (operation) {
            is RenderOperation.Clear -> applyClearOperation(operation.id)
            is RenderOperation.Create ->
                applyCreateOperation(operation.id, operation.kind)
            is RenderOperation.SetProps ->
                applySetPropsOperation(operation.id, operation.props)
            is RenderOperation.SetProp ->
                applySetPropOperation(
                    operation.id,
                    operation.name,
                    operation.value,
                )
            is RenderOperation.SetPropBatch -> {
                for (index in operation.ids.indices) {
                    applySetPropOperation(
                        operation.ids[index],
                        operation.names[index],
                        operation.values[index],
                    )
                }
            }
            is RenderOperation.SetStringPropBatch -> {
                for (index in operation.ids.indices) {
                    applySetPropOperation(
                        operation.ids[index],
                        operation.name,
                        operation.values[index],
                    )
                }
            }
            is RenderOperation.SetContiguousStringPropBatch -> {
                for (index in operation.values.indices) {
                    applySetPropOperation(
                        operation.firstId + index,
                        operation.name,
                        operation.values[index],
                    )
                }
            }
            is RenderOperation.RemoveProp ->
                applyRemovePropOperation(operation.id, operation.name)
            is RenderOperation.Listen ->
                applyListenOperation(
                    operation.id,
                    operation.event,
                    operation.handler,
                    operation.delivery,
                )
            is RenderOperation.Unlisten ->
                applyUnlistenOperation(operation.id, operation.event)
            is RenderOperation.InsertChild ->
                applyInsertOperation(
                    operation.parent,
                    operation.child,
                    operation.index,
                )
            is RenderOperation.MoveChild ->
                applyMoveOperation(
                    operation.parent,
                    operation.child,
                    operation.index,
                )
            is RenderOperation.RemoveChild ->
                applyRemoveChildOperation(operation.parent, operation.child)
            is RenderOperation.Remove ->
                applyRemoveOperation(operation.id)
            is RenderOperation.ScrollTo ->
                applyScrollToOperation(operation)
            is RenderOperation.MotionSetTarget ->
                applyMotionSetTargetOperation(operation)
            is RenderOperation.MotionCancel ->
                applyMotionCancelOperation(operation)
            is RenderOperation.MotionDriverSetTarget ->
                applyMotionDriverSetTargetOperation(operation)
            is RenderOperation.MotionDriverCancel ->
                applyMotionDriverCancelOperation(operation)
        }
    }

    private fun applyClearOperation(id: Int) {
        val savedChildren: List<Int>? =
            if (id == 0) {
                null
            } else {
                (views[id] as? ViewGroup)?.let { group ->
                    (0 until group.childCount).map {
                        group.getChildAt(it).id
                    }
                }
            }
        transactionApplier.record {
            if (id != 0 && savedChildren != null) {
                restoreAll(
                    savedChildren
                        .filter { views.containsKey(it) }
                        .map { childId -> { insertChild(id, childId, null) } }
                )
            }
        }
        clear(id)
    }

    private fun applyCreateOperation(id: Int, kind: String) {
        transactionApplier.record { remove(id) }
        create(id, kind)
    }

    private fun applySetPropsOperation(
        id: Int,
        props: Map<String, Any?>,
    ) {
        val undo = mutableListOf<() -> Unit>()
        for ((name, value) in props) {
            undo += capturePropUndo(id, name)
            recordAcceptedProp(id, name, present = true, wireValue = value)
        }
        transactionApplier.record { restoreAll(undo) }
        pendingResets[id]?.removeAll(props.keys)
        setProps(id, props)
    }

    private fun applySetPropOperation(
        id: Int,
        name: String,
        value: Any?,
    ) {
        val undo = capturePropUndo(id, name)
        recordAcceptedProp(id, name, present = true, wireValue = value)
        transactionApplier.record { restoreAll(listOf(undo)) }
        pendingResets[id]?.remove(name)
        val targetView = views[id]
        setProp(id, name, value)
        if (name == "interactive_scrollbar" && value != true) {
            transactionApplier.afterCommit {
                val scroll = targetView as? VyneScrollContainer
                if (scroll?.interactiveScrollbarEnabled == false) {
                    scroll.clearVirtualScrollSeekState()
                }
            }
        }
    }

    private fun applyRemovePropOperation(id: Int, name: String) {
        pendingResets[id]?.remove(name)
        val undo = capturePropUndo(id, name)
        recordAcceptedProp(id, name, present = false, wireValue = null)
        transactionApplier.record { restoreAll(listOf(undo)) }
        val targetView = views[id]
        removeProp(id, name)
        if (name == "interactive_scrollbar") {
            transactionApplier.afterCommit {
                val scroll = targetView as? VyneScrollContainer
                if (scroll?.interactiveScrollbarEnabled == false) {
                    scroll.clearVirtualScrollSeekState()
                }
            }
        }
    }

    private fun applyListenOperation(
        id: Int,
        event: String,
        handler: Int,
        delivery: String,
    ) {
        val key = id to event
        val previous = eventBindings.records[key]
        transactionApplier.record {
            if (previous != null) {
                detachListener(views[id] ?: return@record, id, event)
                listen(
                    id,
                    event,
                    previous.handler,
                    previous.delivery,
                )
            } else {
                unlisten(id, event)
            }
        }
        listen(id, event, handler, delivery)
    }

    private fun applyUnlistenOperation(id: Int, event: String) {
        val key = id to event
        val previous = eventBindings.records[key]
        transactionApplier.record {
            if (previous != null) {
                listen(
                    id,
                    event,
                    previous.handler,
                    previous.delivery,
                )
            }
        }
        val targetView = views[id]
        unlisten(id, event)
        if (event == "scroll_seek") {
            transactionApplier.afterCommit {
                if (eventBindings.records[id to event] == null) {
                    (targetView as? VyneScrollContainer)?.clearVirtualScrollSeekState()
                }
            }
        }
    }

    private fun applyInsertOperation(
        parent: Int,
        child: Int,
        index: Int?,
    ) {
        val previousIndex =
            (views[child]?.parent as? ViewGroup)?.indexOfChild(views[child])
        val previousParent = parentOf[child]
        transactionApplier.record {
            if (
                previousParent != null &&
                previousIndex != null &&
                previousIndex >= 0
            ) {
                insertChild(previousParent, child, previousIndex)
            } else {
                removeChild(parent, child)
            }
        }
        insertChild(parent, child, index)
    }

    private fun applyMoveOperation(parent: Int, child: Int, index: Int) {
        val oldIndex =
            (views[parent] as? ViewGroup)?.indexOfChild(views[child]) ?: -1
        transactionApplier.record {
            if (oldIndex >= 0) {
                insertChild(parent, child, oldIndex)
            }
        }
        insertChild(parent, child, index)
    }

    private fun applyRemoveChildOperation(parent: Int, child: Int) {
        val oldIndex =
            (views[parent] as? ViewGroup)?.indexOfChild(views[child]) ?: -1
        transactionApplier.record {
            if (oldIndex >= 0 && views.containsKey(child)) {
                insertChild(parent, child, oldIndex)
            }
        }
        removeChild(parent, child)
    }

    private fun applyScrollToOperation(operation: RenderOperation.ScrollTo) {
        val view = views[operation.id]
        if (view !is ViewGroup || view !is VyneScrollContainer) {
            error("scroll_to: target ${operation.id} is not a scroll container")
        }
        val density = view.resources.displayMetrics.density
        val x = logicalScrollOffsetToPx(operation.offsetX, density)
        val y = logicalScrollOffsetToPx(operation.offsetY, density)
        // Scrolling is an accepted effect, not tree state. Start it only after
        // every structural operation in the transaction has succeeded.
        transactionApplier.afterCommit {
            if (operation.animated) {
                view.smoothScrollToPosition(x, y)
            } else {
                view.scrollToPosition(x, y)
            }
        }
    }

    private fun applyRemoveOperation(id: Int) {
        val removedViewMap: MutableMap<Int, View> = mutableMapOf()
        val removedSpecMap: MutableMap<Int, ElementSpec> = mutableMapOf()
        val removedStateMap: MutableMap<Int, ViewState> = mutableMapOf()
        val removedParentMap: MutableMap<Int, Int> = mutableMapOf()
        val removedChildrenMap: MutableMap<Int, MutableSet<Int>> =
            mutableMapOf()
        val removedMementos: MutableMap<Int, MutableMap<String, PropMemento>> =
            mutableMapOf()
        // Prior (parent, index) of every subtree view, so rollback can
        // reattach views that were detached for pooling.
        val removedPositions: MutableMap<Int, Pair<Int?, Int>> = mutableMapOf()
        val idsToSnapshot = mutableListOf(id)
        var cursor = 0
        while (cursor < idsToSnapshot.size) {
            val current = idsToSnapshot[cursor++]
            views[current]?.let { removedViewMap[current] = it }
            specs[current]?.let { removedSpecMap[current] = it }
            viewStates[current]?.let { removedStateMap[current] = it }
            parentOf[current]?.let { removedParentMap[current] = it }
            childrenOf[current]?.let {
                removedChildrenMap[current] = it.toMutableSet()
                idsToSnapshot.addAll(it)
            }
            propMementos[current]?.let { mementos ->
                removedMementos[current] =
                    mementos.mapValuesTo(mutableMapOf()) { (_, m) -> m.snapshot() }
            }
            removedPositions[current] =
                parentOf[current] to
                    ((views[current]?.parent as? ViewGroup)
                        ?.indexOfChild(views[current]) ?: -1)
        }
        // Views the subtree pushes into the pool; the undo pops them so a
        // rollback never leaves a view both pooled and re-attached.
        val pooledViews = mutableListOf<View>()
        transactionApplier.record {
            // Restore subtree maps unconditionally, then re-attach the view;
            // every action runs even if an earlier one fails (#3).
            restoreAll(
                listOf(
                    {
                        views.putAll(removedViewMap)
                        specs.putAll(removedSpecMap)
                        viewStates.putAll(removedStateMap)
                        parentOf.putAll(removedParentMap)
                        for ((removedParent, children) in removedChildrenMap) {
                            childrenOf
                                .getOrPut(removedParent) { mutableSetOf() }
                                .addAll(children)
                        }
                        for ((removedId, mementos) in removedMementos) {
                            propMementos.getOrPut(removedId) { mutableMapOf() }
                                .putAll(mementos)
                        }
                    },
                    {
                        pooledViews.forEach { viewPool.remove(it) }
                    },
                    {
                        // A pooled view may have been reused and reset by a
                        // create in the same transaction; re-apply the prior
                        // accepted props so the restored tree matches the
                        // restored mementos exactly (digest stays stable).
                        for ((removedId, mementos) in removedMementos) {
                            for ((name, memento) in mementos) {
                                if (memento.present) {
                                    applyResolvedProp(
                                        removedId,
                                        name,
                                        deepCopyBridgeValue(
                                            memento.acceptedWireValue,
                                        ),
                                    )
                                } else {
                                    removeProp(removedId, name)
                                }
                            }
                        }
                    },
                    {
                        // Reattach every subtree view (all were detached so
                        // each could be pooled) at its prior position, in
                        // ascending index order per parent.
                        val reattachOrder = removedPositions
                            .filterValues { (parentId, index) ->
                                parentId != null && index >= 0
                            }
                            .entries
                            .sortedWith(
                                compareBy(
                                    { it.value.first },
                                    { it.value.second },
                                )
                            )
                        for (entry in reattachOrder) {
                            val vid = entry.key
                            val parentId = entry.value.first
                            val index = entry.value.second
                            if (views[vid]?.parent == null) {
                                insertChild(parentId!!, vid, index)
                            }
                        }
                    },
                )
            )
        }
        remove(id, pooledViews)
    }

    private fun applyMotionSetTargetOperation(
        operation: RenderOperation.MotionSetTarget,
    ) {
        transactionApplier.afterCommit {
            motionSetTarget(operation)
        }
    }

    private fun applyMotionCancelOperation(
        operation: RenderOperation.MotionCancel,
    ) {
        transactionApplier.afterCommit {
            motionCancel(operation)
        }
    }

    private fun applyMotionDriverSetTargetOperation(
        operation: RenderOperation.MotionDriverSetTarget,
    ) {
        transactionApplier.afterCommit {
            motionDriverSetTarget(operation)
        }
    }

    private fun applyMotionDriverCancelOperation(
        operation: RenderOperation.MotionDriverCancel,
    ) {
        transactionApplier.afterCommit {
            motionDriverCancel(operation)
        }
    }

    /**
     * Clear all children from a ViewGroup, or reset all state when id=0 (root).
     *
     * id=0 is used by Python's error commit to wipe the tree before showing
     * the error message.  For non-root clears, only the children are removed —
     * the View itself and its props are preserved (useful for re-parenting).
     */
    private fun clear(id: Int) {
        val view = views[id]
        if (view is ViewGroup) {
            view.removeAllViews()
        }
        if (id == 0) {
            nativeTree.resetToRoot()
            val remaining = eventBindings.clear()
            transactionApplier.afterCommit {
                for (detach in remaining) {
                    runCatching { detach() }
                }
            }
            transactionApplier.afterCommit {
                presentationEngine.dispose()
                declarativeAnimatedProps.clear()
                declarativeCanvasSlots.clear()
                animatedDriverValues.clear()
                animatedBindings.clear()
                animatedBindingSlotsByDriver.clear()
            }
        }
    }

    /**
     * Create a new View from the element registry.
     *
     * Views are identified by integer IDs assigned by Python.  The ID is set
     * on the View via `View.id` so LayoutParams and animations can reference it.
     * Default text color/size are captured in ViewState so remove_prop can
     * correctly reset them.
     *
     * A pooled view of the same kind is reused when available; its stale
     * props are reset to defaults first, then the transaction's set_prop ops
     * apply the new cell's values.  Reset is journalled through the normal
     * create/remove undo so a rolled-back transaction returns the view to the
     * pool exactly as it left it.
     */
    private fun create(id: Int, kind: String) {
        val spec = registry.get(kind)
        specs[id] = spec
        val pooled = viewPool.take(kind)
        val view = pooled?.view ?: spec.create(ElementContext(root.context))
        view.id = id
        views[id] = view
        viewStates[id] = ViewState(
            defaultTextColors = defaultTextColorsByKind.getOrPut(kind) {
                (view as? TextView)?.textColors
            },
            defaultTextSizePx = defaultTextSizesByKind.getOrPut(kind) {
                (view as? TextView)?.textSize
            },
        )
        if (pooled != null) {
            // Do not reset eagerly: the new cell's set_props overwrite most
            // props anyway, so reset only the leftover ones after the
            // transaction (see pendingResets in set/remove prop paths).
            pendingResets[id] = pooled.resetProps.toMutableSet()
            transactionApplier.afterCommit {
                val remaining = pendingResets.remove(id) ?: return@afterCommit
                for (name in remaining) {
                    runCatching { removeProp(id, name) }
                }
            }
        }
    }

    private fun setProps(id: Int, props: Map<String, Any?>) {
        for ((name, value) in props) {
            setProp(id, name, value)
        }
    }

    /**
     * Set a single prop on a View.
     *
     * Generic props (width, height, padding, background, etc.) are handled first
     * in `handleGenericProp`.  Widget-specific props (text, orientation, etc.)
     * fall through to the ElementSpec's prop map.  Changing orientation requires
     * re-computing all child LayoutParams since the parent axis flips.
     *
     * @throws IllegalStateException if the view or spec is not found
     */
    private fun setProp(id: Int, name: String, value: Any?) {
        if (name == "draw" && value is JSONArray && views[id] is CanvasView) {
            setCanvasDraw(id, value)
            return
        }

        val animatedNode = (value as? JSONObject)?.takeIf {
            it.optBoolean(ANIMATED_NODE_MARKER, false)
        }
        if (animatedNode != null) {
            setAdvancedViewProp(id, name, animatedNode)
            return
        }

        val animatedValue = (value as? JSONObject)?.takeIf {
            it.optBoolean(ANIMATED_VALUE_MARKER, false)
        }
        if (animatedValue != null) {
            setDeclarativeViewProp(id, name, animatedValue)
            return
        }

        val key = id to name
        val slotKey = "view:$id:prop:$name"
        val presentationOwned =
            key in declarativeAnimatedProps ||
                presentationEngine.hasSlot(slotKey)
        requireNotNull(views[id]) { "set_prop: view $id not found" }
        applyResolvedProp(id, name, value)
        if (presentationOwned) {
            transactionApplier.afterCommit {
                declarativeAnimatedProps.remove(key)
                removeAnimatedBinding(slotKey, unregisterSlot = false)
                presentationEngine.unregisterSlot(
                    slotKey,
                    reason = "property_replaced",
                )
            }
        }
    }

    private fun setDeclarativeViewProp(
        id: Int,
        name: String,
        value: JSONObject,
    ) {
        val target = value.getDouble("value").toFloat()
        require(target.isFinite()) { "AnimatedValue target must be finite" }
        val key = id to name
        val slotKey = "view:$id:prop:$name"
        val hadDeclarativeTarget = key in declarativeAnimatedProps
        val previousLive =
            if (presentationEngine.hasSlot(slotKey)) {
                presentationEngine.readSlot(slotKey)
            } else {
                null
            }

        // Mutate the logical property inside the journalled transaction. The
        // old presentation value is restored only after the transaction wins,
        // before the next display frame can observe this temporary target.
        applyResolvedProp(id, name, target.toDouble())
        transactionApplier.afterCommit {
            removeAnimatedBinding(slotKey)
            val view = requireNotNull(views[id]) {
                "Animated target view $id disappeared after commit"
            }
            ensureViewAdapter(slotKey, view, name)
            if (!hadDeclarativeTarget && previousLive == null) {
                presentationEngine.prime(
                    slotKey,
                    target,
                )
            } else {
                previousLive?.let {
                    applyResolvedProp(id, name, it.toDouble())
                }
                startDeclarativeAnimation(
                    id,
                    name,
                    value,
                    fromValue = previousLive,
                )
            }
            declarativeAnimatedProps.add(key)
        }
    }

    private fun setAdvancedViewProp(
        id: Int,
        name: String,
        payload: JSONObject,
    ) {
        val expression =
            requireNotNull(payload.optJSONObject("expression")) {
                "Animated node requires an expression"
            }
        val initialValue = evaluateAnimatedExpression(expression, initialOnly = true)
        require(initialValue.isFinite()) {
            "Animated node initial value must be finite"
        }
        applyResolvedProp(id, name, initialValue.toDouble())
        val slotKey = "view:$id:prop:$name"
        transactionApplier.afterCommit {
            val view = requireNotNull(views[id]) {
                "Animated node target view $id disappeared after commit"
            }
            presentationEngine.unregisterSlot(
                slotKey,
                reason = "property_rebound",
            )
            ensureViewAdapter(slotKey, view, name)
            bindAnimatedExpression(
                slotKey = slotKey,
                nodeId = id,
                property = name,
                expression = expression,
            )
            declarativeAnimatedProps.remove(id to name)
        }
    }

    private fun setCanvasDraw(id: Int, value: JSONArray) {
        val canvas = views[id] as? CanvasView
            ?: error("Canvas draw target $id is not a Canvas")
        val targets = extractCanvasAnimatedTargets(id, value)
        val advancedTargets = extractAdvancedCanvasTargets(id, value)
        val oldSlots = declarativeCanvasSlots[id]?.toSet().orEmpty()
        val oldAdvancedSlots =
            animatedBindings.values
                .filter { it.nodeId == id && it.slotKey.contains(":slot:") }
                .mapTo(mutableSetOf()) { it.slotKey }
        val previousLive =
            targets.associate { target ->
                target.slotKey to
                    if (presentationEngine.hasSlot(target.slotKey)) {
                        presentationEngine.readSlot(target.slotKey)
                    } else {
                        null
                    }
            }

        applyResolvedProp(id, "draw", value)
        transactionApplier.afterCommit {
            val nextSlots = targets.mapTo(mutableSetOf()) { it.slotKey }
            val nextAdvancedSlots =
                advancedTargets.mapTo(mutableSetOf()) { it.slotKey }
            for (removed in oldSlots - nextSlots) {
                presentationEngine.unregisterSlot(
                    removed,
                    reason = "canvas_slot_removed",
                )
            }
            for (removed in oldAdvancedSlots - nextAdvancedSlots) {
                removeAnimatedBinding(removed)
            }
            for (target in targets) {
                removeAnimatedBinding(target.slotKey)
                ensureCanvasAdapter(
                    target.slotKey,
                    canvas,
                    target.opId,
                    target.propertyName,
                )
                val oldValue = previousLive[target.slotKey]
                if (target.slotKey !in oldSlots && oldValue == null) {
                    presentationEngine.prime(
                        target.slotKey,
                        target.target,
                    )
                } else {
                    oldValue?.let {
                        canvas.writeOpField(target.opId, target.propertyName, it)
                    }
                    startDeclarativeCanvasAnimation(target, oldValue)
                }
            }
            for (target in advancedTargets) {
                if (target.slotKey in oldSlots) {
                    presentationEngine.unregisterSlot(
                        target.slotKey,
                        reason = "canvas_slot_rebound",
                    )
                }
                ensureCanvasAdapter(
                    target.slotKey,
                    canvas,
                    target.opId,
                    target.propertyName,
                )
                bindAnimatedExpression(
                    slotKey = target.slotKey,
                    nodeId = target.nodeId,
                    property = target.propertyName,
                    expression = target.expression,
                )
            }
            if (nextSlots.isEmpty()) {
                declarativeCanvasSlots.remove(id)
            } else {
                declarativeCanvasSlots[id] = nextSlots
            }
        }
    }

    private fun extractCanvasAnimatedTargets(
        id: Int,
        draw: JSONArray,
    ): List<DeclarativeCanvasTarget> {
        val targets = mutableListOf<DeclarativeCanvasTarget>()
        for (index in 0 until draw.length()) {
            val operation = draw.optJSONObject(index) ?: continue
            val kind = operation.optString("kind")
            val fields = CANVAS_ANIMATABLE_FIELDS_BY_KIND[kind].orEmpty()
            for (field in fields) {
                val payload =
                    (operation.opt(field) as? JSONObject)?.takeIf {
                        it.optBoolean(ANIMATED_VALUE_MARKER, false)
                    } ?: continue
                val opId =
                    operation.optString(CanvasOpIdentity.RESERVED_ID_KEY)
                require(opId.isNotBlank()) {
                    "Animated Canvas operation $index has no stable identity"
                }
                val target = payload.getDouble("value").toFloat()
                require(target.isFinite()) {
                    "Animated Canvas target must be finite"
                }
                targets +=
                    DeclarativeCanvasTarget(
                        nodeId = id,
                        opId = opId,
                        propertyName = field,
                        target = target,
                        payload = payload,
                    )
            }
        }
        return targets
    }

    private fun extractAdvancedCanvasTargets(
        id: Int,
        draw: JSONArray,
    ): List<AdvancedCanvasTarget> {
        val targets = mutableListOf<AdvancedCanvasTarget>()
        for (index in 0 until draw.length()) {
            val operation = draw.optJSONObject(index) ?: continue
            val kind = operation.optString("kind")
            val fields = CANVAS_ANIMATABLE_FIELDS_BY_KIND[kind].orEmpty()
            for (field in fields) {
                val payload =
                    (operation.opt(field) as? JSONObject)?.takeIf {
                        it.optBoolean(ANIMATED_NODE_MARKER, false)
                    } ?: continue
                val expression =
                    requireNotNull(payload.optJSONObject("expression")) {
                        "Animated Canvas node requires an expression"
                    }
                val initial =
                    evaluateAnimatedExpression(expression, initialOnly = true)
                require(initial.isFinite()) {
                    "Animated Canvas node initial value must be finite"
                }
                val opId =
                    operation.optString(CanvasOpIdentity.RESERVED_ID_KEY)
                require(opId.isNotBlank()) {
                    "Animated Canvas operation $index has no stable identity"
                }
                targets +=
                    AdvancedCanvasTarget(
                        nodeId = id,
                        opId = opId,
                        propertyName = field,
                        expression = expression,
                    )
            }
        }
        return targets
    }

    /**
     * Capture the current live value of a property for faithful rollback.
     *
     * Returns null when the property is not currently set or its value
     * cannot be meaningfully captured, so rollback will remove/reset it.
     */
    /**
     * Record the accepted wire state of one prop (design-pattern #2).
     *
     * Runs on the accepted set/remove paths BEFORE the mutation; the value
     * is deep-copied so later container mutation cannot corrupt history.
     * Live presentation values with no wire form (Canvas draw ops) are
     * captured alongside.
     */
    private fun recordAcceptedProp(
        id: Int,
        name: String,
        present: Boolean,
        wireValue: Any?,
    ) {
        val live = mutableMapOf<String, Any?>()
        if (name == "draw") {
            (views[id] as? CanvasView)?.ops?.let { live["draw"] = JSONArray(it.toString()) }
        }
        propMementos.getOrPut(id) { mutableMapOf() }[name] =
            PropMemento(present, deepCopyBridgeValue(wireValue), live)
    }

    /**
     * Build the undo closure restoring one prop's PRIOR accepted state:
     * live presentation values first, then the accepted wire value (or
     * removal if it was absent). One rollback algorithm for all kinds —
     * no live-view when-switch, no extension shadow.
     */
    private fun capturePropUndo(id: Int, name: String): () -> Unit {
        val prior = propMementos[id]?.get(name)?.snapshot()
        return {
            val mementos = propMementos.getOrPut(id) { mutableMapOf() }
            if (prior == null) {
                mementos.remove(name)
            } else {
                mementos[name] = prior
            }
            if (prior != null && prior.present) {
                val live = prior.livePresentationValues["draw"]
                applyResolvedProp(
                    id,
                    name,
                    if (live != null) deepCopyBridgeValue(live) else
                        deepCopyBridgeValue(prior.acceptedWireValue),
                )
            } else {
                removeProp(id, name)
            }
        }
    }

    /**
     * Display a base64 data-URI source. Python owns fetching (urllib, aiohttp,
     * ...) and passes the bytes here; this tool only decodes and applies them.
     * The previous bitmap stays visible until the new one lands, and a source
     * changed mid-decode is dropped (generation check).
     */
    private fun applyDataUriImageSource(
        id: Int,
        view: android.widget.ImageView,
        dataUri: String,
    ) {
        viewStates[id]?.imageSource = dataUri
        imageDecoder.load(
            dataUri = dataUri,
            target = view,
            isCurrent = { viewStates[id]?.imageSource == dataUri },
        )
    }

    private fun applyResolvedProp(id: Int, name: String, value: Any?) {
        val view = views[id] ?: return
        val spec = specs[id] ?: return

        if (handleGenericProp(id, view, name, value)) return

        if (name == "source" && view is android.widget.ImageView && value is String &&
            value.startsWith("data:")
        ) {
            applyDataUriImageSource(id, view, value)
            return
        }

        val handler = spec.props[name]
        if (handler != null) {
            handler.invoke(propContext(id), view, value)
        } else {
            // Unknown property — reject defensively.  Python should have
            // validated and rejected this before it reached the wire.
            // Throwing ensures the commit fails and triggers rollback.
            error("Unknown prop '$name' for kind ${spec.kind} (id=$id)")
        }
        if (name == "orientation" && view is LinearLayout) {
            updateChildLayoutParams(id)
        }
    }

    private fun removeProp(id: Int, name: String) {
        val view = views[id] ?: return
        val spec = specs[id] ?: return
        val key = id to name
        val slotKey = "view:$id:prop:$name"
        val presentationOwned =
            key in declarativeAnimatedProps ||
                presentationEngine.hasSlot(slotKey)
        if (presentationOwned) {
            transactionApplier.afterCommit {
                declarativeAnimatedProps.remove(key)
                removeAnimatedBinding(slotKey, unregisterSlot = false)
                presentationEngine.unregisterSlot(
                    slotKey,
                    reason = "property_removed",
                )
            }
        }
        if (name == "draw") {
            val slots = declarativeCanvasSlots[id]?.toSet().orEmpty()
            transactionApplier.afterCommit {
                slots.forEach {
                    presentationEngine.unregisterSlot(
                        it,
                        reason = "canvas_draw_removed",
                    )
                }
                animatedBindings.values
                    .filter { it.nodeId == id && it.slotKey.contains(":slot:") }
                    .map { it.slotKey }
                    .forEach(::removeAnimatedBinding)
                declarativeCanvasSlots.remove(id)
            }
        }

        if (handleGenericRemoveProp(id, view, name)) return

        // Widget-specific removal is the SAME handler with a null value:
        // each handler owns its default in one place.
        spec.props[name]?.invoke(propContext(id), view, null)
        if (name == "orientation" && view is LinearLayout) {
            updateChildLayoutParams(id)
        }
    }

    /**
     * Apply a generic prop via the table-driven applicator.
     *
     * Falls through to widget-specific props if the generic table doesn't
     * handle this name.  Unknown props for the given kind are rejected.
     */
    private fun handleGenericProp(id: Int, view: View, name: String, value: Any?): Boolean {
        val kind = specs[id]?.kind ?: return false
        val applicator = PropertyTable.get(name, kind)
        if (applicator != null) {
            applicator.set(ApplicatorContext(id, view, this), value)
            return true
        }
        // If the prop is in the contract for this kind but has no applicator,
        // it's a widget-specific prop — let the ElementSpec handle it.
        if (registry.isValidProp(name, kind)) {
            return false
        }
        // Not in contract — reject.
        error("Unknown prop '$name' for kind $kind (id=$id)")
    }

    /**
     * Remove a generic prop via the table-driven applicator.
     */
    private fun handleGenericRemoveProp(id: Int, view: View, name: String): Boolean {
        val kind = specs[id]?.kind ?: return false
        val applicator = PropertyTable.get(name, kind)
        if (applicator != null) {
            applicator.remove(ApplicatorContext(id, view, this))
            return true
        }
        // Widget-specific prop — let the ElementSpec handle it.
        if (registry.isValidProp(name, kind)) {
            return false
        }
        // Not in contract — reject.
        error("Unknown prop '$name' for kind $kind (id=$id)")
    }

    /** Raw dimension update used by PropertyApplicators. */
    override fun updateNodeLayoutRaw(id: Int, update: NodeLayout.() -> Unit) {
        val state = stateFor(id)
        if (state.layout == null) state.layout = NodeLayout()
        state.layout!!.update()
        updateLayoutParams(id)
    }

    /** Pixel-value layout update used by margin/lp applicators. */
    override fun updateNodeLayoutPx(id: Int, update: NodeLayout.() -> Unit) {
        val state = stateFor(id)
        if (state.layout == null) state.layout = NodeLayout()
        state.layout!!.update()
        updateLayoutParams(id)
    }

    override fun updateBasePadding(
        id: Int,
        view: View,
        update: EdgeInsets.() -> EdgeInsets,
    ) {
        stateFor(id).basePadding = stateFor(id).basePadding.update()
        updatePadding(id, view)
    }

    override fun updateCornerRadii(id: Int, view: View, update: CornerRadii.() -> Unit) {
        val state = stateFor(id)
        val radii = state.cornerRadii ?: CornerRadii()
        radii.update()
        state.cornerRadii = radii
        updateBackground(id, view)
    }

    internal fun updatePadding(id: Int, view: View) {
        val state = stateFor(id)
        val base = state.basePadding
        val safe = state.safeAreaInset
        view.setPaddingRelative(
            base.left + safe.left,
            base.top + safe.top,
            base.right + safe.right,
            base.bottom + safe.bottom,
        )
    }

    @SuppressLint("NewApi")
    override fun updateOverflow(id: Int, view: View, overflow: String?) {
        val hidden = overflow != "visible"
        val state = stateFor(id)
        state.overflowHidden = hidden
        if (view is ViewGroup) {
            view.clipChildren = hidden
            view.clipToPadding = hidden
        }
        (view as? RoundedView)?.clipsChildrenToBounds = hidden
        val radii = state.cornerRadii
        if (radii != null && radii.hasRadius) {
            view.outlineProvider = createRoundOutlineProvider(radii)
            view.clipToOutline = hidden
        } else {
            view.clipToOutline = false
            view.outlineProvider = ViewOutlineProvider.BACKGROUND
        }
        view.invalidate()
    }

    /**
     * Update accessibility semantics on a View.
     *
     * Applies the Python-owned role, state, and range values to Android's
     * AccessibilityNodeInfo. Kotlin only mechanically maps the resolved
     * values — it never derives roles or states from visual properties.
     */
    override fun updateAccessibility(id: Int, view: View) {
        val state = stateFor(id)
        val role = state.accessibilityRole
        if (role == null && !state.accessibilityStateSelected &&
            state.accessibilityStateChecked == null &&
            state.accessibilityStateDescription == null &&
            state.accessibilityRangeMin == 0f && state.accessibilityRangeMax == 0f &&
            state.accessibilityProgressHandler == null) {
            // No accessibility semantics set; restore default.
            view.importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_AUTO
            view.accessibilityDelegate = null
            return
        }

        view.importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_YES
        view.accessibilityDelegate = object : View.AccessibilityDelegate() {
            override fun onInitializeAccessibilityNodeInfo(
                host: View,
                info: AccessibilityNodeInfo,
            ) {
                super.onInitializeAccessibilityNodeInfo(host, info)

                // Exhaustive mechanical mapping of Python's accepted roles.
                when (role) {
                    null, "none" -> info.className = View::class.java.name
                    "button", "keyboard_key" -> {
                        info.className = android.widget.Button::class.java.name
                        info.isClickable = host.isEnabled
                    }
                    "link" -> {
                        info.className = TextView::class.java.name
                        info.isClickable = host.isEnabled
                    }
                    "search" -> info.className = EditText::class.java.name
                    "image" -> info.className = android.widget.ImageView::class.java.name
                    "text" -> info.className = TextView::class.java.name
                    "adjustable", "slider" -> info.className = android.widget.SeekBar::class.java.name
                    "header" -> {
                        info.className = TextView::class.java.name
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) info.isHeading = true
                    }
                    "tab" -> {
                        info.className = android.widget.Button::class.java.name
                        info.isClickable = host.isEnabled
                    }
                    "checkbox" -> {
                        info.className = android.widget.CheckBox::class.java.name
                        info.isCheckable = true
                    }
                    "radio_button" -> {
                        info.className = android.widget.RadioButton::class.java.name
                        info.isCheckable = true
                    }
                    "switch" -> {
                        info.className = android.widget.Switch::class.java.name
                        info.isCheckable = true
                    }
                    "dropdown_list" -> info.className = android.widget.Spinner::class.java.name
                    "toolbar" -> info.className = android.widget.Toolbar::class.java.name
                    "progress_bar" -> info.className = android.widget.ProgressBar::class.java.name
                    else -> error("Unmapped canonical accessibility role: $role")
                }

                // Selection state
                if (state.accessibilityStateSelected) {
                    info.isSelected = true
                }

                // Checked state (isChecked available since API 19; minSdk 26).
                // Android has no native "mixed" state; set false with state_description.
                when (state.accessibilityStateChecked) {
                    "checked", "true" -> info.isChecked = true
                    "unchecked", "false" -> info.isChecked = false
                    "mixed" -> info.isChecked = false
                }

                // State description (for custom state text, API 30+)
                state.accessibilityStateDescription?.let { desc ->
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                        info.stateDescription = desc
                    }
                }

                // Range info (for sliders, progress bars).
                // RangeInfo.obtain() available since API 19 (KitKat); minSdk is 26.
                // obtain() deprecated in API 33 but still functional.
                if (state.accessibilityRangeMax > state.accessibilityRangeMin) {
                    @Suppress("DEPRECATION")
                    info.rangeInfo = AccessibilityNodeInfo.RangeInfo.obtain(
                        AccessibilityNodeInfo.RangeInfo.RANGE_TYPE_FLOAT,
                        state.accessibilityRangeMin,
                        state.accessibilityRangeMax,
                        state.accessibilityRangeCurrent,
                    )
                    if (host.isEnabled && state.accessibilityProgressHandler != null) {
                        info.addAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_SET_PROGRESS)
                    }
                }
            }

            override fun performAccessibilityAction(
                host: View,
                action: Int,
                args: Bundle?,
            ): Boolean {
                if (action == AccessibilityNodeInfo.AccessibilityAction.ACTION_SET_PROGRESS.id && host.isEnabled) {
                    val handler = state.accessibilityProgressHandler ?: return false
                    val value = args?.getFloat(
                        AccessibilityNodeInfo.ACTION_ARGUMENT_PROGRESS_VALUE,
                        Float.NaN,
                    ) ?: return false
                    if (value.isFinite() && value >= state.accessibilityRangeMin &&
                        value <= state.accessibilityRangeMax
                    ) {
                        emit(id, "accessibility_progress", handler, mapOf("value" to value))
                        return true
                    }
                    return false
                }
                return super.performAccessibilityAction(host, action, args)
            }
        }
    }

    @SuppressLint("NewApi")
    override fun updateBackground(id: Int, view: View) {
        val state = stateFor(id)
        val color = state.backgroundColor
        val radii = state.cornerRadii
        val hasRadius = radii != null && radii.hasRadius
        val hasColor = color != null
        val borderW = state.borderWidth
        val borderC = state.borderColor
        val hasBorder = borderW > 0 && borderC != null
        val rippleC = state.rippleColor
        val hasRipple = rippleC != null

        // Push radii to custom ViewGroup subclasses so they clip children
        // in dispatchDraw (following React Native's ReactViewGroup pattern).
        (view as? RoundedView)?.cornerRadii = radii

        val needsDrawable = hasColor || hasRadius || hasBorder || hasRipple
        if (needsDrawable) {
            val content = createGradientBackground(
                backgroundColor = color,
                cornerRadii = radii,
                borderWidth = borderW,
                borderColor = borderC,
            )

            // Wrap in RippleDrawable *before* setting as background (single assignment).
            val finalBg: Drawable = if (hasRipple) {
                RippleDrawable(
                    ColorStateList.valueOf(rippleC!!),
                    content,
                    createGradientBackground(
                        backgroundColor = Color.WHITE,
                        cornerRadii = radii,
                        borderWidth = 0,
                        borderColor = null,
                    )
                )
            } else {
                content
            }
            view.background = finalBg

            if (hasRadius) {
                view.clipToOutline = state.overflowHidden
                view.outlineProvider = createRoundOutlineProvider(radii!!)
            } else {
                view.clipToOutline = false
                view.outlineProvider = ViewOutlineProvider.BACKGROUND
            }
        } else {
            // Neither color, radius, nor border — reset to system default.
            view.background = null
            // Reset child-clipping state on custom ViewGroup subclasses.
            (view as? RoundedView)?.cornerRadii = null
            view.clipToOutline = false
            view.outlineProvider = ViewOutlineProvider.BACKGROUND
        }
    }

    private fun createGradientBackground(
        backgroundColor: Int?,
        cornerRadii: CornerRadii?,
        borderWidth: Int,
        borderColor: Int?,
    ): GradientDrawable = GradientDrawable().apply {
        shape = GradientDrawable.RECTANGLE
        setColor(backgroundColor ?: Color.TRANSPARENT)
        if (cornerRadii != null && cornerRadii.hasRadius) {
            // GradientDrawable uses the same TL, TR, BR, BL pair ordering as Path.
            this.cornerRadii = cornerRadii.toPathRadii()
        }
        if (borderWidth > 0 && borderColor != null) {
            setStroke(borderWidth, borderColor)
        }
    }

    @SuppressLint("NewApi")
    internal fun createRoundOutlineProvider(radii: CornerRadii): ViewOutlineProvider {
        return object : ViewOutlineProvider() {
            override fun getOutline(view: View, outline: Outline) {
                val w = view.width
                val h = view.height
                if (w <= 0 || h <= 0) return
                if (radii.isUniform) {
                    outline.setRoundRect(0, 0, w, h, radii.topLeft)
                } else {
                    val path = Path().apply {
                        addRoundRect(
                            0f, 0f, w.toFloat(), h.toFloat(),
                            radii.toPathRadii(),
                            Path.Direction.CW,
                        )
                    }
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                        @Suppress("NewApi")
                        outline.setPath(path)
                    } else {
                        @Suppress("DEPRECATION")
                        outline.setConvexPath(path)
                    }
                }
            }
        }
    }

    override fun installSafeArea(id: Int, view: View) {
        view.setOnApplyWindowInsetsListener { target, insets ->
            stateFor(id).safeAreaInset = safeAreaFrom(insets)
            updatePadding(id, target)
            insets
        }
        if (view.isAttachedToWindow) {
            view.requestApplyInsets()
        } else {
            view.addOnAttachStateChangeListener(object : View.OnAttachStateChangeListener {
                override fun onViewAttachedToWindow(attachedView: View) {
                    attachedView.removeOnAttachStateChangeListener(this)
                    attachedView.requestApplyInsets()
                }
                override fun onViewDetachedFromWindow(detachedView: View) = Unit
            })
        }
    }

    override fun removeSafeArea(id: Int, view: View) {
        view.setOnApplyWindowInsetsListener(null)
        stateFor(id).safeAreaInset = EdgeInsets.ZERO
        updatePadding(id, view)
    }

    @Suppress("DEPRECATION")
    private fun safeAreaFrom(insets: WindowInsets): EdgeInsets {
        var left = insets.systemWindowInsetLeft
        var top = insets.systemWindowInsetTop
        var right = insets.systemWindowInsetRight
        var bottom = insets.systemWindowInsetBottom

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            insets.displayCutout?.safeInsetLeft?.let { left = maxOf(left, it) }
            insets.displayCutout?.safeInsetTop?.let { top = maxOf(top, it) }
            insets.displayCutout?.safeInsetRight?.let { right = maxOf(right, it) }
            insets.displayCutout?.safeInsetBottom?.let { bottom = maxOf(bottom, it) }
        }

        return EdgeInsets(left, top, right, bottom)
    }

    internal fun updateLayoutParams(id: Int) {
        val view = views[id] ?: return
        val parent = view.parent as? ViewGroup ?: return
        val layout = viewStates[id]?.layout

        // Convert DimensionValue to Android layout param constant.
        fun dim(dv: DimensionValue?, default: Int): Int = dv?.toLayoutParam(default) ?: default

        val params = when (parent) {
            is LinearLayout -> {
                val defaultWidth: Int
                val defaultHeight: Int
                if (parent.orientation == LinearLayout.HORIZONTAL) {
                    defaultWidth = ViewGroup.LayoutParams.WRAP_CONTENT
                    defaultHeight = ViewGroup.LayoutParams.WRAP_CONTENT
                } else {
                    defaultWidth = ViewGroup.LayoutParams.MATCH_PARENT
                    defaultHeight = ViewGroup.LayoutParams.WRAP_CONTENT
                }
                LinearLayout.LayoutParams(
                    dim(layout?.width, defaultWidth),
                    dim(layout?.height, defaultHeight),
                ).apply {
                    layout?.lpWeight?.let { weight = it }
                    layout?.lpGravity?.let { gravity = it }
                    setMargins(
                        0,
                        layout?.marginTop ?: 0,
                        0,
                        layout?.marginBottom ?: 0,
                    )
                    marginStart = layout?.marginStart ?: 0
                    marginEnd = layout?.marginEnd ?: 0
                }
            }
            is FrameLayout -> FrameLayout.LayoutParams(
                dim(layout?.width, ViewGroup.LayoutParams.MATCH_PARENT),
                dim(layout?.height, ViewGroup.LayoutParams.WRAP_CONTENT),
            ).apply {
                layout?.lpGravity?.let { gravity = it }
                setMargins(
                    0,
                    layout?.marginTop ?: 0,
                    0,
                    layout?.marginBottom ?: 0,
                )
                marginStart = layout?.marginStart ?: 0
                marginEnd = layout?.marginEnd ?: 0
            }
            else -> ViewGroup.LayoutParams(
                dim(layout?.width, ViewGroup.LayoutParams.MATCH_PARENT),
                dim(layout?.height, ViewGroup.LayoutParams.WRAP_CONTENT),
            )
        }
        view.layoutParams = params
    }

    internal fun updateChildLayoutParams(parentId: Int) {
        childrenOf[parentId]?.forEach(::updateLayoutParams)
    }

    private fun listen(id: Int, event: String, handler: Int, delivery: String = "all") {
        val key = id to event
        val view = views[id] ?: return
        val previous = eventBindings.records.remove(key)
        if (previous != null) {
            // Replace the existing listener: detach the OLD listener first —
            // for extension events that is the record's detach callback
            // (additive native listeners must never leak).
            detachListener(view, id, event)
            previous.detach?.invoke()
        }
        val detach = attachListener(view, id, event, handler)
        eventBindings.records[key] = ListenerRecord(handler, delivery, detach)
    }

    private fun unlisten(id: Int, event: String) {
        val key = id to event
        val record = eventBindings.records.remove(key) ?: return
        val view = views[id] ?: return
        detachListener(view, id, event)   // core events
        record.detach?.invoke()           // extension events — exactly once
    }

    /**
     * Attach an Android event listener for a Python event handler.
     *
     * All listeners check `applyingCommit` to suppress synthetic events during
     * programmatic view mutations.  For example, `EditText.setText()` during
     * a commit would fire a text_change event — we suppress it because the
     * Python side already knows about the value it sent.
     */
    private fun attachListener(
        view: View,
        id: Int,
        event: String,
        handler: Int,
    ): (() -> Unit)? {
        var detach: (() -> Unit)? = null
        when (event) {
            "click" -> view.setOnClickListener {
                emit(id, "click", handler, emptyMap())
            }
            "long_click" -> view.setOnLongClickListener {
                emit(id, "long_click", handler, emptyMap())
                true
            }
            "focus_change" -> view.setOnFocusChangeListener { _, hasFocus ->
                if (applyingCommit) return@setOnFocusChangeListener
                emit(id, "focus_change", handler, mapOf("has_focus" to hasFocus))
            }
            "text_change" -> if (view is EditText) {
                val watcher = object : TextWatcher {
                    override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) = Unit
                    override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) = Unit
                    override fun afterTextChanged(s: Editable?) {
                        if (applyingCommit) return
                        emit(id, "text_change", handler, mapOf("text" to s?.toString().orEmpty()))
                    }
                }
                stateFor(id).textWatcher = watcher
                view.addTextChangedListener(watcher)
            }
            "editor_action" -> if (view is EditText) {
                stateFor(id).editorActionHandler = handler
                updateEditorActionListener(id, view)
            }
            "accessibility_progress" -> {
                stateFor(id).accessibilityProgressHandler = handler
                updateAccessibility(id, view)
            }
            "layout_metrics" -> {
                val listener = View.OnLayoutChangeListener {
                    measured, left, top, right, bottom, _, _, _, _ ->
                    if (applyingCommit) return@OnLayoutChangeListener
                    emitLayoutMetrics(
                        measured,
                        id,
                        handler,
                        left,
                        top,
                        right,
                        bottom,
                    )
                }
                view.addOnLayoutChangeListener(listener)
                view.post {
                    if (
                        view.isLaidOut &&
                        eventBindings.records[id to event]?.handler == handler
                    ) {
                        emitLayoutMetrics(
                            view,
                            id,
                            handler,
                            view.left,
                            view.top,
                            view.right,
                            view.bottom,
                        )
                    }
                }
                detach = { view.removeOnLayoutChangeListener(listener) }
            }
            "scroll_metrics" -> if (
                view is ViewGroup && view is VyneScrollContainer
            ) {
                var lastX = view.scrollX
                var lastY = view.scrollY
                var lastTime = SystemClock.uptimeMillis()
                val scrollListener = View.OnScrollChangeListener {
                    _, scrollX, scrollY, _, _ ->
                    if (applyingCommit) return@OnScrollChangeListener
                    val now = SystemClock.uptimeMillis()
                    if (view.consumeSeekRevealMetricsSuppression(scrollX, scrollY, now)) {
                        lastX = scrollX
                        lastY = scrollY
                        lastTime = now
                        return@OnScrollChangeListener
                    }
                    val elapsedMs = (now - lastTime).coerceAtLeast(1L)
                    val density = view.resources.displayMetrics.density
                    val velocityX = pixelsToDp(
                        (scrollX - lastX).toFloat(),
                        density,
                    ) * 1000f / elapsedMs
                    val velocityY = pixelsToDp(
                        (scrollY - lastY).toFloat(),
                        density,
                    ) * 1000f / elapsedMs
                    lastX = scrollX
                    lastY = scrollY
                    lastTime = now
                    emitScrollMetrics(
                        view,
                        id,
                        handler,
                        velocityX,
                        velocityY,
                        now,
                    )
                }
                val layoutListener = View.OnLayoutChangeListener {
                    _, _, _, _, _, _, _, _, _ ->
                    if (!applyingCommit) {
                        lastX = view.scrollX
                        lastY = view.scrollY
                        lastTime = SystemClock.uptimeMillis()
                        if (!view.consumeSeekRevealMetricsSuppression(
                                lastX, lastY, lastTime,
                            )) {
                            emitScrollMetrics(
                                view,
                                id,
                                handler,
                                0f,
                                0f,
                                lastTime,
                            )
                        }
                    }
                }
                view.setOnScrollChangeListener(scrollListener)
                view.addOnLayoutChangeListener(layoutListener)
                view.post {
                    if (
                        view.isLaidOut &&
                        eventBindings.records[id to event]?.handler == handler
                    ) {
                        lastX = view.scrollX
                        lastY = view.scrollY
                        lastTime = SystemClock.uptimeMillis()
                        if (!view.consumeSeekRevealMetricsSuppression(
                                lastX, lastY, lastTime,
                            )) {
                            emitScrollMetrics(
                                view,
                                id,
                                handler,
                                0f,
                                0f,
                                lastTime,
                            )
                        }
                    }
                }
                detach = {
                    view.setOnScrollChangeListener(null)
                    view.removeOnLayoutChangeListener(layoutListener)
                }
            }
            "scroll_seek" -> if (view is VyneScrollContainer) {
                view.setVirtualScrollSeekListener { targetX, targetY, final, eventTime ->
                    if (!applyingCommit) {
                        val density = view.resources.displayMetrics.density
                        emit(
                            id,
                            "scroll_seek",
                            handler,
                            linkedMapOf(
                                "target_offset_x" to pixelsToDp(targetX.toFloat(), density),
                                "target_offset_y" to pixelsToDp(targetY.toFloat(), density),
                                "final" to final,
                                "event_time" to eventTime,
                            ),
                        )
                    }
                }
            }
            in POINTER_EVENTS -> {
                stateFor(id).pointerHandlers[event] = handler
                updatePointerListener(id, view)
            }
            else -> {
                // Extension event: fall back to the spec's attach hook.
                // Publication is commit-gated: an event fired while a
                // transaction is applying (e.g. synchronously from a prop
                // setter) is deferred to afterCommit and dropped on
                // rollback — Python never sees state that was not accepted.
                val spec = specs[id] ?: return null
                val hook = spec.events[event]
                    ?: error("unsupported event '$event' for kind ${spec.kind}")
                detach = hook(view) { payload ->
                    if (applyingCommit) {
                        transactionApplier.afterCommit {
                            emit(id, event, handler, payload)
                        }
                    } else {
                        emit(id, event, handler, payload)
                    }
                }
            }
        }
        return detach
    }

    private fun emitLayoutMetrics(
        view: View,
        id: Int,
        handler: Int,
        left: Int,
        top: Int,
        right: Int,
        bottom: Int,
    ) {
        val density = view.resources.displayMetrics.density
        emit(
            id,
            "layout_metrics",
            handler,
            linkedMapOf(
                "x" to pixelsToDp(left.toFloat(), density),
                "y" to pixelsToDp(top.toFloat(), density),
                "width" to pixelsToDp((right - left).coerceAtLeast(0).toFloat(), density),
                "height" to pixelsToDp((bottom - top).coerceAtLeast(0).toFloat(), density),
            ),
        )
    }

    private fun emitScrollMetrics(
        view: ViewGroup,
        id: Int,
        handler: Int,
        velocityX: Float,
        velocityY: Float,
        eventTime: Long,
    ) {
        val density = view.resources.displayMetrics.density
        val content = view.getChildAt(0)
        val viewportWidth =
            (view.width - view.paddingLeft - view.paddingRight).coerceAtLeast(0)
        val viewportHeight =
            (view.height - view.paddingTop - view.paddingBottom).coerceAtLeast(0)
        val projection = (view as? VyneScrollContainer)?.virtualListProjection
        val contentWidth = (content?.width ?: 0).toFloat()
        val contentHeight = (content?.height ?: 0).toFloat()
        val projectedX = InteractiveScrollbarMath.clampProjectedOffset(
            (projection?.first ?: view.scrollX).toFloat(),
            viewportWidth.toFloat(),
            contentWidth,
        )
        val projectedY = InteractiveScrollbarMath.clampProjectedOffset(
            (projection?.second ?: view.scrollY).toFloat(),
            viewportHeight.toFloat(),
            contentHeight,
        )
        emit(
            id,
            "scroll_metrics",
            handler,
            linkedMapOf(
                "offset_x" to pixelsToDp(view.scrollX.coerceAtLeast(0).toFloat(), density),
                "offset_y" to pixelsToDp(view.scrollY.coerceAtLeast(0).toFloat(), density),
                "viewport_width" to pixelsToDp(viewportWidth.toFloat(), density),
                "viewport_height" to pixelsToDp(viewportHeight.toFloat(), density),
                "content_width" to pixelsToDp(contentWidth, density),
                "content_height" to pixelsToDp(contentHeight, density),
                "velocity_x" to velocityX,
                "velocity_y" to velocityY,
                "projected_offset_x" to pixelsToDp(projectedX, density),
                "projected_offset_y" to pixelsToDp(projectedY, density),
                "event_time" to eventTime,
            ),
        )
    }

    private fun detachListener(view: View, id: Int, event: String) {
        when (event) {
            "click" -> view.setOnClickListener(null)
            "long_click" -> view.setOnLongClickListener(null)
            "focus_change" -> view.setOnFocusChangeListener(null)
            "text_change" -> if (view is EditText) {
                viewStates[id]?.textWatcher?.let { view.removeTextChangedListener(it) }
                viewStates[id]?.textWatcher = null
            }
            "editor_action" -> if (view is EditText) {
                stateFor(id).editorActionHandler = null
                updateEditorActionListener(id, view)
            }
            "accessibility_progress" -> {
                stateFor(id).accessibilityProgressHandler = null
                updateAccessibility(id, view)
            }
            "scroll_seek" ->
                (view as? VyneScrollContainer)?.setVirtualScrollSeekListener(null)
            in POINTER_EVENTS -> {
                stateFor(id).pointerHandlers.remove(event)
                updatePointerListener(id, view)
            }
            // Extension events: the detach callback lives on the
            // ListenerRecord and is invoked by unlisten() — exactly once.
        }
    }

    /**
     * Install a pointer listener that delegates to the pure PointerSession reducer.
     *
     * The session state is stored in ViewState.  On each touch event, the reducer
     * produces decisions that the host applies mechanically: emitting events,
     * requesting parent disallow-intercept, performing click, and resetting state.
     */
    private fun updatePointerListener(id: Int, view: View) {
        val state = stateFor(id)
        if (state.pointerHandlers.isEmpty()) {
            view.setOnTouchListener(null)
            state.pointerSession = PointerSessionState.IDLE
            return
        }

        view.setOnTouchListener { _, event ->
            if (applyingCommit || !view.isEnabled) {
                return@setOnTouchListener false
            }

            // Allocate gesture ID on ACTION_DOWN.
            if (event.actionMasked == MotionEvent.ACTION_DOWN) {
                state.pointerGestureId = nextPointerGestureId++
            }

            val config = PointerSessionConfig(
                touchSlop = touchSlop,
                captureAxis = state.pointerCaptureAxis,
                hasPointerDown = "pointer_down" in state.pointerHandlers,
                hasPointerMove = "pointer_move" in state.pointerHandlers,
                hasPointerUp = "pointer_up" in state.pointerHandlers,
                hasPointerCancel = "pointer_cancel" in state.pointerHandlers,
                gestureId = state.pointerGestureId,
            )

            val transition = PointerSession.reduceMotionEvent(
                state.pointerSession,
                event,
                state.pointerSession.activePointerId,
                config,
            )
            state.pointerSession = transition.state

            for (decision in transition.decisions) {
                when (decision) {
                    is PointerDecision.Noop -> { /* nothing */ }
                    is PointerDecision.EmitPointerEvent -> {
                        val handlerId = state.pointerHandlers[decision.eventName] ?: continue
                        emit(
                            id, decision.eventName, handlerId,
                            buildPointerPayload(view, decision.sample),
                        )
                    }
                    is PointerDecision.ParentIntercept -> {
                        view.parent?.requestDisallowInterceptTouchEvent(decision.disallow)
                    }
                    is PointerDecision.PerformClick -> {
                        view.performClick()
                    }
                    is PointerDecision.Reset -> {
                        state.pointerSession = PointerSessionState.IDLE
                    }
                }
            }
            true
        }
    }

    /**
     * Build a pointer event payload from the current session state.
     *
     * Uses the preserved DOWN coordinates from the original event for
     * down_x/down_y, and computes current coordinates from the last known
     * position in the session state.
     */
    private fun buildPointerPayload(
        view: View,
        session: PointerSessionState,
    ): Map<String, Any?> {
        val density = view.resources.displayMetrics.density
        return linkedMapOf(
            "x" to pixelsToDp(session.lastX, density),
            "y" to pixelsToDp(session.lastY, density),
            "down_x" to pixelsToDp(session.downX, density),
            "down_y" to pixelsToDp(session.downY, density),
            "pointer_id" to (session.activePointerId ?: 0),
            "gesture_id" to (session.gestureId ?: 0L),
            "pressure" to session.lastPressure,
            "size" to session.lastSize,
            "tool_type" to session.lastToolType,
            "source" to session.lastSource,
            "down_time" to session.downTime,
            "event_time" to session.lastEventTime,
        )
    }

    override fun updateEditorActionListener(id: Int, view: EditText) {
        val state = stateFor(id)
        if (state.editorActionHandler == null && !state.blurOnSubmit) {
            view.setOnEditorActionListener(null)
            return
        }
        view.setOnEditorActionListener { editText, _, _ ->
            if (!applyingCommit) {
                state.editorActionHandler?.let { handler ->
                    emit(id, "editor_action", handler, mapOf("text" to editText.text.toString()))
                }
            }
            if (state.blurOnSubmit) {
                inputController.blur(view, hideKeyboard = true)
                true
            } else {
                false
            }
        }
    }

    override fun updateTextInputFocus(view: EditText, focused: Boolean) {
        inputController.updateFocus(view, focused)
    }

    private fun insertChild(parentId: Int, childId: Int, index: Int?) {
        val parent = views[parentId] as? ViewGroup
            ?: error("insert_child: parent $parentId not found or is not a ViewGroup")
        val child = views[childId]
            ?: error("insert_child: child $childId not found")
        val previousParent = child.parent as? ViewGroup
        parentOf[childId]?.let { previousParentId ->
            childrenOf[previousParentId]?.remove(childId)
        }
        previousParent?.removeView(child)
        val targetIndex = index?.coerceIn(0, parent.childCount) ?: parent.childCount
        parent.addView(child, targetIndex)
        parentOf[childId] = parentId
        childrenOf.getOrPut(parentId) { mutableSetOf() }.add(childId)
        updateLayoutParams(childId)
    }

    private fun removeChild(parentId: Int, childId: Int) {
        val parent = views[parentId] as? ViewGroup
            ?: error("remove_child: parent $parentId not found or is not a ViewGroup")
        val child = views[childId]
            ?: error("remove_child: child $childId not found")
        parent.removeView(child)
        parentOf.remove(childId)
        childrenOf[parentId]?.remove(childId)
    }

    /**
     * Remove a subtree. Detached views of recyclable kinds enter the pool so
     * a later create in the same transaction can reuse them.
     *
     * `pooledOut`, when supplied, receives the views that entered the pool;
     * the caller's undo closure pops them back so rollback restores the tree
     * without double ownership.
     */
    private fun remove(id: Int, pooledOut: MutableList<View>? = null) {
        val view = views[id] ?: return
        val parent = view.parent as? ViewGroup
        parent?.removeView(view)
        parentOf.remove(id)?.let { oldParent ->
            childrenOf[oldParent]?.remove(id)
        }

        val idsToRemove = mutableListOf(id)
        var cursor = 0
        while (cursor < idsToRemove.size) {
            val current = idsToRemove[cursor++]
            childrenOf[current]?.let { idsToRemove.addAll(it) }
        }

        // Detach every subtree view from its parent so each can be pooled as
        // an independent, childless entry.
        for (vid in idsToRemove) {
            val subtreeView = views[vid] ?: continue
            (subtreeView.parent as? ViewGroup)?.removeView(subtreeView)
        }

        val recyclable = idsToRemove.mapNotNull { vid ->
            val kind = specs[vid]?.kind ?: return@mapNotNull null
            if (kind in ViewPool.RECYCLABLE_KINDS) {
                Triple(vid, kind, views[vid])
            } else {
                null
            }
        }
        val resetPropsByVid = recyclable.associate { (vid, _, _) ->
            vid to propMementos[vid]?.keys?.toList().orEmpty()
        }
        val pooledViews = recyclable.mapNotNull { (_, _, pooledView) -> pooledView }
        pooledOut?.addAll(pooledViews)

        val removedIds = idsToRemove.toHashSet()

        for (vid in idsToRemove) {
            views.remove(vid)
            specs.remove(vid)
            viewStates.remove(vid)
            parentOf.remove(vid)
            childrenOf.remove(vid)
            propMementos.remove(vid)
            pendingResets.remove(vid)
        }
        for ((vid, kind, pooledView) in recyclable) {
            if (pooledView != null) {
                viewPool.put(kind, pooledView, resetPropsByVid.getValue(vid))
            }
        }
        // Listener records are removed on the ACCEPTED commit only: a
        // rollback restores the tree with its listener records intact, so
        // the digest never sees a record/view mismatch.
        transactionApplier.afterCommit {
            val detaches = eventBindings.removeNodes(removedIds)
            for (detach in detaches) {
                runCatching { detach() }
            }
        }
        transactionApplier.afterCommit {
            for (removedId in removedIds) {
                presentationEngine.unregisterNode(
                    removedId,
                    reason = "node_removed",
                )
                animatedBindings.values
                    .filter { it.nodeId == removedId }
                    .map { it.slotKey }
                    .forEach(::removeAnimatedBinding)
                declarativeCanvasSlots.remove(removedId)
            }
            declarativeAnimatedProps.removeAll { it.first in removedIds }
        }
    }

    private fun emit(target: Int, event: String, handler: Int, payload: Map<String, Any?>) {
        eventSink(
            NativeEvent(
                eventBindings.nextEventSequence(),
                target,
                event,
                handler,
                payload,
                delivery = eventBindings.records[target to event]?.delivery ?: "all",
            )
        )
    }

    // ── Unified animation system ────────────────────────────────────────
    //
    // Uses the unified PresentationEngine with one frame clock and one
    // physics implementation for both View properties and Canvas operations.
    // Python owns motion policy (target, spec, retarget behavior); Kotlin
    // mechanically applies values each frame via adapters.

    private fun bindAnimatedExpression(
        slotKey: String,
        nodeId: Int,
        property: String,
        expression: JSONObject,
    ) {
        val expressionCopy = JSONObject(expression.toString())
        val drivers = mutableMapOf<Long, Float>()
        collectAnimatedDrivers(expressionCopy, drivers)
        require(drivers.isNotEmpty()) {
            "Animated expression must reference at least one driver"
        }
        val previousDrivers =
            animatedBindings[slotKey]?.driverIds.orEmpty()
        for (driverId in previousDrivers - drivers.keys) {
            detachAnimatedBindingSlot(driverId, slotKey)
        }
        for ((driverId, initial) in drivers) {
            ensureAnimatedDriver(driverId, initial)
            animatedBindingSlotsByDriver
                .getOrPut(driverId) { mutableSetOf() }
                .add(slotKey)
        }
        animatedBindings[slotKey] =
            AnimatedBinding(
                slotKey = slotKey,
                nodeId = nodeId,
                property = property,
                expression = expressionCopy,
                driverIds = drivers.keys.toSet(),
            )
        refreshAnimatedBinding(slotKey)
    }

    private fun removeAnimatedBinding(
        slotKey: String,
        unregisterSlot: Boolean = true,
    ) {
        val binding = animatedBindings.remove(slotKey) ?: return
        for (driverId in binding.driverIds) {
            detachAnimatedBindingSlot(driverId, slotKey)
        }
        if (unregisterSlot) {
            presentationEngine.unregisterSlot(
                slotKey,
                reason = "animated_binding_removed",
            )
        }
    }

    private fun detachAnimatedBindingSlot(
        driverId: Long,
        slotKey: String,
    ) {
        val slots = animatedBindingSlotsByDriver[driverId] ?: return
        slots.remove(slotKey)
        if (slots.isEmpty()) {
            animatedBindingSlotsByDriver.remove(driverId)
        }
    }

    private fun pruneUnboundAnimatedDrivers() {
        for (driverId in animatedDriverValues.keys.toList()) {
            if (animatedBindingSlotsByDriver[driverId].isNullOrEmpty()) {
                presentationEngine.unregisterSlot(
                    slotKey = "driver:$driverId",
                    reason = "driver_unbound",
                )
                animatedDriverValues.remove(driverId)
            }
        }
    }

    private fun ensureAnimatedDriver(driverId: Long, initial: Float) {
        require(driverId > 0L && initial.isFinite()) {
            "Animated driver identity and initial value must be valid"
        }
        animatedDriverValues.putIfAbsent(driverId, initial)
        val driverKey = "driver:$driverId"
        presentationEngine.registerAdapter(
            driverKey,
            object : PresentationEngine.PropertyAdapter {
                override fun read(): Float =
                    requireNotNull(animatedDriverValues[driverId]) {
                        "Animated driver $driverId is not registered"
                    }

                override fun write(value: Float) {
                    require(value.isFinite()) {
                        "Animated driver value must be finite"
                    }
                    animatedDriverValues[driverId] = value
                    animatedBindingSlotsByDriver[driverId]
                        ?.toList()
                        ?.forEach(::refreshAnimatedBinding)
                }
            },
        )
    }

    private fun refreshAnimatedBinding(slotKey: String) {
        val binding = animatedBindings[slotKey] ?: return
        if (!presentationEngine.hasSlot(slotKey)) return
        val value =
            evaluateAnimatedExpression(
                binding.expression,
                initialOnly = false,
            )
        require(value.isFinite()) {
            "Animated expression produced a non-finite value"
        }
        presentationEngine.writeSlot(
            slotKey,
            constrainPresentationValue(binding.property, value),
        )
    }

    private fun collectAnimatedDrivers(
        expression: JSONObject,
        result: MutableMap<Long, Float>,
    ) {
        when (val operation = expression.getString("op")) {
            "value" -> {
                val driverId = expression.getLong("driver_id")
                val initial = expression.getDouble("initial").toFloat()
                require(driverId > 0L && initial.isFinite()) {
                    "Animated value node is invalid"
                }
                val previous = result.putIfAbsent(driverId, initial)
                require(previous == null || previous == initial) {
                    "Animated driver $driverId has conflicting initial values"
                }
            }
            "constant" -> {
                require(expression.getDouble("value").isFinite()) {
                    "Animated constant must be finite"
                }
            }
            "negate", "clamp", "interpolate" ->
                collectAnimatedDrivers(
                    expression.getJSONObject("input"),
                    result,
                )
            "add", "subtract", "multiply", "divide" -> {
                collectAnimatedDrivers(
                    expression.getJSONObject("left"),
                    result,
                )
                collectAnimatedDrivers(
                    expression.getJSONObject("right"),
                    result,
                )
            }
            else -> error("Unknown animated expression operation: $operation")
        }
    }

    private fun evaluateAnimatedExpression(
        expression: JSONObject,
        initialOnly: Boolean,
    ): Float {
        fun evaluate(child: String): Float =
            evaluateAnimatedExpression(
                expression.getJSONObject(child),
                initialOnly,
            )

        val value =
            when (val operation = expression.getString("op")) {
                "value" -> {
                    val driverId = expression.getLong("driver_id")
                    val initial = expression.getDouble("initial").toFloat()
                    if (initialOnly) {
                        initial
                    } else {
                        animatedDriverValues[driverId] ?: initial
                    }
                }
                "constant" -> expression.getDouble("value").toFloat()
                "add" -> evaluate("left") + evaluate("right")
                "subtract" -> evaluate("left") - evaluate("right")
                "multiply" -> evaluate("left") * evaluate("right")
                "divide" -> {
                    val divisor = evaluate("right")
                    require(divisor != 0f) {
                        "Animated expression division by zero"
                    }
                    evaluate("left") / divisor
                }
                "negate" -> -evaluate("input")
                "clamp" ->
                    evaluate("input").coerceIn(
                        expression.getDouble("minimum").toFloat(),
                        expression.getDouble("maximum").toFloat(),
                    )
                "interpolate" ->
                    interpolateAnimatedValue(
                        evaluate("input"),
                        expression.getJSONArray("input_range"),
                        expression.getJSONArray("output_range"),
                        expression.optString("extrapolate", "extend"),
                    )
                else -> error(
                    "Unknown animated expression operation: $operation",
                )
            }
        require(value.isFinite()) {
            "Animated expression produced a non-finite value"
        }
        return value
    }

    private fun interpolateAnimatedValue(
        value: Float,
        inputRange: JSONArray,
        outputRange: JSONArray,
        extrapolate: String,
    ): Float {
        require(
            inputRange.length() >= 2 &&
                inputRange.length() == outputRange.length(),
        ) {
            "Animated interpolation ranges must have equal lengths >= 2"
        }
        require(extrapolate in setOf("extend", "clamp", "identity")) {
            "Invalid animated interpolation extrapolation"
        }
        val inputs =
            (0 until inputRange.length()).map {
                inputRange.getDouble(it).toFloat()
            }
        val outputs =
            (0 until outputRange.length()).map {
                outputRange.getDouble(it).toFloat()
            }
        require(
            inputs.all(Float::isFinite) &&
                outputs.all(Float::isFinite) &&
                inputs.zipWithNext().all { (left, right) -> right > left },
        ) {
            "Animated interpolation ranges are invalid"
        }

        val index =
            when {
                value < inputs.first() -> {
                    if (extrapolate == "identity") return value
                    if (extrapolate == "clamp") return outputs.first()
                    0
                }
                value > inputs.last() -> {
                    if (extrapolate == "identity") return value
                    if (extrapolate == "clamp") return outputs.last()
                    inputs.lastIndex - 1
                }
                else ->
                    (0 until inputs.lastIndex).firstOrNull {
                        value >= inputs[it] && value <= inputs[it + 1]
                    } ?: inputs.lastIndex - 1
            }
        val fraction =
            (value - inputs[index]) /
                (inputs[index + 1] - inputs[index])
        return outputs[index] +
            (outputs[index + 1] - outputs[index]) * fraction
    }

    private fun startDeclarativeAnimation(
        id: Int,
        prop: String,
        value: JSONObject,
        fromValue: Float?,
    ) {
        val view = requireNotNull(views[id])
        val slotKey = "view:$id:prop:$prop"
        val spec = value.optString("easing", "ease_out")
        ensureViewAdapter(slotKey, view, prop)
        presentationEngine.setTarget(
            animationId = 0L,
            slotKey = slotKey,
            nodeId = id,
            property = prop,
            spec = if (spec == "spring") "spring" else "tween",
            targets = listOf(value.getDouble("value").toFloat()),
            fromValue = fromValue,
            durationMs = value.optLong("duration", 300L).coerceAtLeast(0L),
            easing = spec,
            dampingRatio = value.optDouble("damping_ratio", 0.8).toFloat().coerceAtLeast(0.01f),
            stiffness = value.optDouble("stiffness", 380.0).toFloat().coerceAtLeast(0.01f),
            restValueThreshold = 0.01f,
            restVelocityThreshold = 0.01f,
            retargetPolicy =
                value.optString(
                    "retarget",
                    if (spec == "spring") "maintain_velocity" else "restart",
                ),
        )
    }

    private fun startDeclarativeCanvasAnimation(
        target: DeclarativeCanvasTarget,
        fromValue: Float?,
    ) {
        val spec = target.payload.optString("easing", "ease_out")
        presentationEngine.setTarget(
            animationId = 0L,
            slotKey = target.slotKey,
            nodeId = target.nodeId,
            property = target.propertyName,
            spec = if (spec == "spring") "spring" else "tween",
            targets = listOf(target.target),
            fromValue = fromValue,
            durationMs =
                target.payload.optLong("duration", 300L).coerceAtLeast(0L),
            easing = spec,
            dampingRatio =
                target.payload
                    .optDouble("damping_ratio", 0.8)
                    .toFloat()
                    .coerceAtLeast(0.01f),
            stiffness =
                target.payload
                    .optDouble("stiffness", 380.0)
                    .toFloat()
                    .coerceAtLeast(0.01f),
            restValueThreshold = 0.01f,
            restVelocityThreshold = 0.01f,
            retargetPolicy =
                target.payload.optString(
                    "retarget",
                    if (spec == "spring") "maintain_velocity" else "restart",
                ),
        )
    }

    /** Unified motion_set_target operation. */
    private fun motionSetTarget(op: RenderOperation.MotionSetTarget) {
        if (op.slotId != null) {
            // Canvas operation animation: register a Canvas adapter.
            val canvasView =
                views[op.nodeId] as? CanvasView
                    ?: error("Animation target ${op.nodeId} is not a Canvas")
            ensureCanvasAdapter(
                op.slotKey,
                canvasView,
                op.slotId,
                op.property,
            )
        } else {
            // View property animation: register a View adapter.
            val view =
                requireNotNull(views[op.nodeId]) {
                    "Animation target ${op.nodeId} no longer exists"
                }
            ensureViewAdapter(op.slotKey, view, op.property)
        }

        presentationEngine.setTarget(
            animationId = op.animationId,
            slotKey = op.slotKey,
            nodeId = op.nodeId,
            property = op.property,
            spec = op.specType,
            targets = op.targets,
            fromValue = op.fromValue,
            durationMs = op.durationMs,
            easing = op.easing,
            dampingRatio = op.dampingRatio,
            stiffness = op.stiffness,
            restValueThreshold = op.restValueThreshold,
            restVelocityThreshold = op.restVelocityThreshold,
            retargetPolicy = op.retargetPolicy,
        )
    }

    private fun motionCancel(op: RenderOperation.MotionCancel) {
        presentationEngine.cancel(
            op.slotKey,
            animationId = op.animationId,
            reason = "cancelled",
        )
    }

    private fun motionDriverSetTarget(
        op: RenderOperation.MotionDriverSetTarget,
    ) {
        require(animatedBindingSlotsByDriver[op.driverId]?.isNotEmpty() == true) {
            "Animated driver ${op.driverId} has no mounted bindings"
        }
        require(presentationEngine.hasSlot(op.driverKey)) {
            "Animated driver ${op.driverId} is not registered"
        }
        presentationEngine.setTarget(
            animationId = op.animationId,
            slotKey = op.driverKey,
            nodeId = op.nodeId,
            property = op.property,
            spec = op.specType,
            targets = op.targets,
            fromValue = op.fromValue,
            durationMs = op.durationMs,
            easing = op.easing,
            dampingRatio = op.dampingRatio,
            stiffness = op.stiffness,
            restValueThreshold = op.restValueThreshold,
            restVelocityThreshold = op.restVelocityThreshold,
            retargetPolicy = op.retargetPolicy,
        )
    }

    private fun motionDriverCancel(
        op: RenderOperation.MotionDriverCancel,
    ) {
        presentationEngine.cancel(
            op.driverKey,
            animationId = op.animationId,
            reason = "cancelled",
        )
    }

    private fun emitAnimationLifecycle(lifecycle: PresentationEngine.Lifecycle) {
        eventSink(
            NativeEvent(
                sequence = eventBindings.nextEventSequence(),
                target = lifecycle.nodeId,
                name = "__vyne_system__",
                handler = 0,
                payload =
                    buildMap {
                        put("type", "animation_lifecycle")
                        put("animation_id", lifecycle.animationId)
                        put("status", lifecycle.status)
                        put("node_id", lifecycle.nodeId)
                        put("property", lifecycle.property)
                        lifecycle.reason?.let { put("reason", it) }
                    },
                delivery = "ordered",
            ),
        )
    }

    /**
     * Ensure a View PropertyAdapter is registered with the engine.
     * The adapter reads/writes the View's live property value.
     */
    private fun ensureViewAdapter(slotKey: String, view: View, prop: String) {
        presentationEngine.registerAdapter(slotKey, object : PresentationEngine.PropertyAdapter {
            override fun read(): Float = readLiveProp(view, prop)
            override fun write(value: Float) {
                applyResolvedProp(
                    view.id,
                    prop,
                    constrainPresentationValue(prop, value).toDouble(),
                )
            }
            override fun settle(value: Float) {
                applyResolvedProp(
                    view.id,
                    prop,
                    constrainPresentationValue(prop, value).toDouble(),
                )
            }
        })
    }

    /**
     * Ensure a Canvas PropertyAdapter is registered with the engine.
     * The adapter reads/writes a Canvas operation field by stable op_id.
     */
    private fun ensureCanvasAdapter(
        slotKey: String,
        canvasView: CanvasView,
        opId: String,
        field: String,
    ) {
        require(canvasView.hasOpField(opId, field)) {
            "Canvas animation slot '$opId:$field' does not exist"
        }
        presentationEngine.registerAdapter(slotKey, object : PresentationEngine.PropertyAdapter {
            override fun read(): Float = canvasView.readOpField(opId, field)
            override fun write(value: Float) {
                canvasView.writeOpField(
                    opId,
                    field,
                    constrainPresentationValue(field, value),
                )
            }
        })
    }

    private fun constrainPresentationValue(property: String, value: Float): Float =
        when (property) {
            "opacity", "trim_start", "trim_end" -> value.coerceIn(0f, 1f)
            "elevation", "width", "height", "radius", "r", "stroke_width" ->
                value.coerceAtLeast(0f)
            else -> value
        }

    /**
     * Read the current live value of a View property for animation.
     */
    private fun readLiveProp(view: View, prop: String): Float {
        val density = view.context.resources.displayMetrics.density
        return when (prop) {
            "alpha", "opacity" -> view.alpha
            "scale_x" -> view.scaleX
            "scale_y" -> view.scaleY
            "rotation" -> view.rotation
            "rotation_x" -> view.rotationX
            "rotation_y" -> view.rotationY
            "translation_x" -> pixelsToDp(view.translationX, density)
            "translation_y" -> pixelsToDp(view.translationY, density)
            "elevation" -> pixelsToDp(view.elevation, density)
            "width" -> {
                val pixels =
                    view.layoutParams?.width?.takeIf { it >= 0 }
                        ?: view.measuredWidth
                pixelsToDp(pixels.toFloat(), density)
            }
            "height" -> {
                val pixels =
                    view.layoutParams?.height?.takeIf { it >= 0 }
                        ?: view.measuredHeight
                pixelsToDp(pixels.toFloat(), density)
            }
            "stroke_dash_offset" -> if (view is PathView) view.dashOffset else 0f
            else -> error("No presentation adapter for property '$prop'")
        }
    }

    /**
     * Convert a Python wire dimension to raw pixels.
     * Delegates to the canonical [dimensionToPx] decoder in PropertyApplicators.
     */
    private fun toPixels(value: Any?): Int {
        return dimensionToPx(value, root.context.resources.displayMetrics.density)
    }

    private fun parseGravity(value: Any?): Int = parseGravityStatic(value)

    override fun stateFor(id: Int): ViewState {
        return viewStates.getOrPut(id) { ViewState() }
    }

    private fun propContext(id: Int): PropContext = PropContext(
        resetTextColor = { view ->
            val colors = viewStates[id]?.defaultTextColors
            if (view is TextView && colors != null) view.setTextColor(colors)
        },
        resetTextSize = { view ->
            val size = viewStates[id]?.defaultTextSizePx
            if (view is TextView && size != null) {
                view.setTextSize(TypedValue.COMPLEX_UNIT_PX, size)
            }
        },
    )

    internal data class ViewState(
        var textWatcher: TextWatcher? = null,
        var defaultTextColors: android.content.res.ColorStateList? = null,
        var defaultTextSizePx: Float? = null,
        var layout: NodeLayout? = null,
        var basePadding: EdgeInsets = EdgeInsets.ZERO,
        var safeAreaInset: EdgeInsets = EdgeInsets.ZERO,
        var backgroundColor: Int? = null,
        var cornerRadii: CornerRadii? = null,
        var borderWidth: Int = 0,
        var borderColor: Int? = null,
        var rippleColor: Int? = null,
        var overflowHidden: Boolean = true,
        var controlledFocus: Boolean? = null,
        var blurOnKeyboardHide: Boolean = false,
        var blurOnTapOutside: Boolean = false,
        var blurOnSubmit: Boolean = false,
        var editorActionHandler: Int? = null,
        val pointerHandlers: MutableMap<String, Int> = mutableMapOf(),
        var pointerCaptureAxis: String? = null,
        var pointerGestureId: Long = 0L,
        var pointerSession: PointerSessionState = PointerSessionState.IDLE,
        // Data-URI source currently requested; generation check for decodes.
        var imageSource: String? = null,
        // Accessibility semantics
        var accessibilityRole: String? = null,
        var accessibilityStateSelected: Boolean = false,
        var accessibilityStateChecked: String? = null,
        var accessibilityStateDescription: String? = null,
        var accessibilityRangeMin: Float = 0f,
        var accessibilityRangeMax: Float = 0f,
        var accessibilityRangeCurrent: Float = 0f,
        var accessibilityProgressHandler: Int? = null,
    )

    private data class DeclarativeCanvasTarget(
        val nodeId: Int,
        val opId: String,
        val propertyName: String,
        val target: Float,
        val payload: JSONObject,
    ) {
        val slotKey: String
            get() = "view:$nodeId:slot:$opId:$propertyName"
    }

    private data class AdvancedCanvasTarget(
        val nodeId: Int,
        val opId: String,
        val propertyName: String,
        val expression: JSONObject,
    ) {
        val slotKey: String
            get() = "view:$nodeId:slot:$opId:$propertyName"
    }

    private data class AnimatedBinding(
        val slotKey: String,
        val nodeId: Int,
        val property: String,
        val expression: JSONObject,
        val driverIds: Set<Long>,
    )

    companion object {
        const val ANIMATED_VALUE_MARKER = "__vyne_animated_value__"
        const val ANIMATED_NODE_MARKER = "__vyne_animated_node__"
        private val MOTION_EASINGS =
            setOf(
                "linear",
                "ease_in",
                "ease_out",
                "ease_in_out",
                "overshoot",
                "bounce",
            )
        private val CANVAS_ANIMATABLE_FIELDS_BY_KIND =
            mapOf(
                "rect" to
                    setOf(
                        "x", "y", "width", "height",
                        "opacity", "stroke_width", "dash_offset",
                    ),
                "round_rect" to
                    setOf(
                        "x", "y", "width", "height", "radius",
                        "opacity", "stroke_width", "dash_offset",
                    ),
                "circle" to
                    setOf(
                        "cx", "cy", "r",
                        "opacity", "stroke_width", "dash_offset",
                    ),
                "line" to
                    setOf(
                        "x1", "y1", "x2", "y2",
                        "opacity", "stroke_width", "dash_offset",
                    ),
                "path" to
                    setOf(
                        "trim_start", "trim_end",
                        "opacity", "stroke_width", "dash_offset",
                    ),
            )
        private val CANVAS_ANIMATABLE_FIELDS =
            CANVAS_ANIMATABLE_FIELDS_BY_KIND.values.flatten().toSet()
        val POINTER_EVENTS = setOf(
            "pointer_cancel",
            "pointer_down",
            "pointer_move",
            "pointer_up",
        )

        fun pixelsToDp(pixels: Float, density: Float): Float =
            if (density > 0f) pixels / density else pixels

        fun pointerPayload(
            xPixels: Float,
            yPixels: Float,
            downXPixels: Float,
            downYPixels: Float,
            density: Float,
            pointerId: Int,
            gestureId: Long,
        ): Map<String, Any?> = linkedMapOf(
            "x" to pixelsToDp(xPixels, density),
            "y" to pixelsToDp(yPixels, density),
            "down_x" to pixelsToDp(downXPixels, density),
            "down_y" to pixelsToDp(downYPixels, density),
            "pointer_id" to pointerId,
            "gesture_id" to gestureId,
        )

        fun resolvePointerAxis(deltaX: Float, deltaY: Float, slop: Float): String? {
            if (!movedBeyondTapSlop(deltaX, deltaY, slop)) return null
            return if (kotlin.math.abs(deltaX) >= kotlin.math.abs(deltaY)) {
                "horizontal"
            } else {
                "vertical"
            }
        }

        fun movedBeyondTapSlop(deltaX: Float, deltaY: Float, slop: Float): Boolean =
            deltaX * deltaX + deltaY * deltaY > slop * slop
    }

    internal data class NodeLayout(
        var width: DimensionValue? = null,
        var height: DimensionValue? = null,
        var lpWeight: Float? = null,
        var lpGravity: Int? = null,
        var marginTop: Int = 0,
        var marginBottom: Int = 0,
        var marginStart: Int = 0,
        var marginEnd: Int = 0,
    )

    internal data class EdgeInsets(
        val left: Int,
        val top: Int,
        val right: Int,
        val bottom: Int,
    ) {
        companion object {
            val ZERO = EdgeInsets(0, 0, 0, 0)
            fun all(value: Int): EdgeInsets = EdgeInsets(value, value, value, value)
        }
    }

    override fun updateLayoutGravity(id: Int, view: View) {
        if (view is LinearLayout) {
            updateLinearLayoutGravity(view)
            updateChildLayoutParams(id)
        }
    }

    internal data class CornerRadii(
        var topLeft: Float = 0f,
        var topRight: Float = 0f,
        var bottomRight: Float = 0f,
        var bottomLeft: Float = 0f,
    ) {
        val hasRadius: Boolean
            get() = topLeft > 0f || topRight > 0f || bottomRight > 0f || bottomLeft > 0f

        val isUniform: Boolean
            get() = topLeft == topRight && topRight == bottomRight && bottomRight == bottomLeft

        /** 8-element float array for Path.addRoundRect. */
        fun toPathRadii(): FloatArray = floatArrayOf(
            topLeft, topLeft,
            topRight, topRight,
            bottomRight, bottomRight,
            bottomLeft, bottomLeft,
        )

        companion object {
            val ZERO = CornerRadii(0f, 0f, 0f, 0f)
        }
    }

}
