package dev.vyne

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse

class RenderTransactionApplierTest {
    @Test
    fun preflightFailureRejectsWithoutMutation() {
        var applied = false
        val applier =
            RenderTransactionApplier(
                preflight = { error("invalid") },
                digest = { "unchanged" },
                applyOperation = { applied = true },
            )

        assertEquals(
            Renderer.ApplyResult.REJECTED_KNOWN,
            applier.apply(listOf(RenderOperation.Clear(0))),
        )
        assertEquals(false, applied)
    }

    @Test
    fun successfulOperationsApplyInOrder() {
        val values = mutableListOf<Int>()
        val applier =
            RenderTransactionApplier(
                preflight = {},
                digest = { values.joinToString() },
                applyOperation = { operation ->
                    values += (operation as RenderOperation.Create).id
                },
            )

        assertEquals(
            Renderer.ApplyResult.OK,
            applier.apply(
                listOf(
                    RenderOperation.Create(1, "Box"),
                    RenderOperation.Create(2, "Text"),
                ),
            ),
        )
        assertEquals(listOf(1, 2), values)
    }

    @Test
    fun applyFailureRollsBackInReverseAndReportsPartial() {
        val values = mutableListOf<Int>()
        lateinit var applier: RenderTransactionApplier
        applier =
            RenderTransactionApplier(
                preflight = {},
                digest = { values.joinToString() },
                applyOperation = { operation ->
                    val id = (operation as RenderOperation.Create).id
                    if (id == 3) error("apply failed")
                    values += id
                    applier.record { values.removeLast() }
                },
            )

        assertEquals(
            Renderer.ApplyResult.PARTIAL,
            applier.apply(
                listOf(
                    RenderOperation.Create(1, "Box"),
                    RenderOperation.Create(2, "Text"),
                    RenderOperation.Create(3, "Text"),
                ),
            ),
        )
        assertEquals(emptyList(), values)
    }

    @Test
    fun rollbackFailureReportsUnknown() {
        val values = mutableListOf<Int>()
        lateinit var applier: RenderTransactionApplier
        applier =
            RenderTransactionApplier(
                preflight = {},
                digest = { values.joinToString() },
                applyOperation = { operation ->
                    val id = (operation as RenderOperation.Create).id
                    values += id
                    applier.record { error("undo failed") }
                    error("apply failed")
                },
            )

        assertEquals(
            Renderer.ApplyResult.UNKNOWN,
            applier.apply(listOf(RenderOperation.Create(1, "Box"))),
        )
    }

    @Test
    fun rollbackCallbacksCannotAppendJournalEntries() {
        val values = mutableListOf<Int>()
        lateinit var applier: RenderTransactionApplier
        applier =
            RenderTransactionApplier(
                preflight = {},
                digest = { values.joinToString() },
                applyOperation = { operation ->
                    val id = (operation as RenderOperation.Create).id
                    values += id
                    applier.record {
                        values.removeLast()
                        applier.record { error("must not run") }
                    }
                    error("apply failed")
                },
            )

        assertEquals(
            Renderer.ApplyResult.PARTIAL,
            applier.apply(listOf(RenderOperation.Create(1, "Box"))),
        )
        assertEquals(emptyList(), values)
    }

    @Test
    fun presentationActionsRunOnlyAfterEveryMutationSucceeds() {
        val order = mutableListOf<String>()
        lateinit var applier: RenderTransactionApplier
        applier =
            RenderTransactionApplier(
                preflight = {},
                digest = { order.filterNot { it.startsWith("presentation") }.joinToString() },
                applyOperation = { operation ->
                    val id = (operation as RenderOperation.Create).id
                    order += "mutation:$id"
                    applier.afterCommit { order += "presentation:$id" }
                },
            )

        assertEquals(
            Renderer.ApplyResult.OK,
            applier.apply(
                listOf(
                    RenderOperation.Create(1, "Box"),
                    RenderOperation.Create(2, "Text"),
                ),
            ),
        )
        assertEquals(
            listOf(
                "mutation:1",
                "mutation:2",
                "presentation:1",
                "presentation:2",
            ),
            order,
        )
    }

    @Test
    fun failedTransactionNeverStartsQueuedPresentationWork() {
        val values = mutableListOf<Int>()
        var presentationStarted = false
        lateinit var applier: RenderTransactionApplier
        applier =
            RenderTransactionApplier(
                preflight = {},
                digest = { values.joinToString() },
                applyOperation = { operation ->
                    val id = (operation as RenderOperation.Create).id
                    if (id == 2) error("later mutation failed")
                    values += id
                    applier.record { values.removeLast() }
                    applier.afterCommit { presentationStarted = true }
                },
            )

        assertEquals(
            Renderer.ApplyResult.PARTIAL,
            applier.apply(
                listOf(
                    RenderOperation.Create(1, "Box"),
                    RenderOperation.Create(2, "Text"),
                ),
            ),
        )
        assertFalse(presentationStarted)
    }

    @Test
    fun postCommitFailureReportsUnknownBecauseTreeAlreadyWon() {
        lateinit var applier: RenderTransactionApplier
        applier =
            RenderTransactionApplier(
                preflight = {},
                digest = { "tree" },
                applyOperation = {
                    applier.afterCommit { error("adapter registration failed") }
                },
            )

        assertEquals(
            Renderer.ApplyResult.UNKNOWN,
            applier.apply(listOf(RenderOperation.Create(1, "Box"))),
        )
    }
}
