package dev.vyne

import android.graphics.Outline
import android.graphics.Path
import android.view.View
import android.view.ViewOutlineProvider
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class OutlineStrategyTest {

    @Test
    fun uniformCornerRadiiUsesSetRoundRect() {
        val radii = Renderer.CornerRadii(
            topLeft = 16f,
            topRight = 16f,
            bottomRight = 16f,
            bottomLeft = 16f,
        )
        assertTrue(radii.isUniform)
        assertEquals(16f, radii.topLeft)
    }

    @Test
    fun nonuniformCornerRadiiAreDetectedCorrectly() {
        val radii = Renderer.CornerRadii(
            topLeft = 8f,
            topRight = 16f,
            bottomRight = 8f,
            bottomLeft = 16f,
        )
        assertEquals(false, radii.isUniform)
    }

    @Test
    fun zeroCornerRadiiHasNoRadius() {
        val radii = Renderer.CornerRadii(
            topLeft = 0f,
            topRight = 0f,
            bottomRight = 0f,
            bottomLeft = 0f,
        )
        assertEquals(false, radii.hasRadius)
        assertEquals(true, radii.isUniform)
    }

    @Test
    fun toPathRadiiProducesCorrectEightElementArray() {
        val radii = Renderer.CornerRadii(
            topLeft = 1f,
            topRight = 2f,
            bottomRight = 3f,
            bottomLeft = 4f,
        )
        val expected = floatArrayOf(1f, 1f, 2f, 2f, 3f, 3f, 4f, 4f)
        val actual = radii.toPathRadii()
        assertEquals(expected.size, actual.size)
        for (i in expected.indices) {
            assertEquals(expected[i], actual[i])
        }
    }

    @Test
    fun partiallyNonzeroCornerRadiiHaveRadius() {
        val radii = Renderer.CornerRadii(
            topLeft = 0f,
            topRight = 0f,
            bottomRight = 8f,
            bottomLeft = 0f,
        )
        assertEquals(true, radii.hasRadius)
        assertEquals(false, radii.isUniform)
    }

    @Test
    fun cornerRadiiZeroCompanionIsAllZeros() {
        val zero = Renderer.CornerRadii.ZERO
        assertEquals(0f, zero.topLeft)
        assertEquals(0f, zero.topRight)
        assertEquals(0f, zero.bottomRight)
        assertEquals(0f, zero.bottomLeft)
        assertEquals(false, zero.hasRadius)
    }
}
