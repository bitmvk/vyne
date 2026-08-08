package dev.vyne

import kotlin.test.Test
import kotlin.test.assertContentEquals

class RendererCornerRadiiTest {
    @Test
    fun pathRadiiPreserveEachCornerIndependently() {
        val radii = Renderer.CornerRadii(
            topLeft = 1f,
            topRight = 2f,
            bottomRight = 3f,
            bottomLeft = 4f,
        )

        assertContentEquals(
            floatArrayOf(1f, 1f, 2f, 2f, 3f, 3f, 4f, 4f),
            radii.toPathRadii(),
        )
    }
}
