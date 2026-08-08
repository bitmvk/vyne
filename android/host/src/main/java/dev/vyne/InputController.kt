package dev.vyne

import android.content.Context
import android.graphics.Rect
import android.os.Build
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.ViewTreeObserver
import android.view.WindowInsets
import android.view.inputmethod.InputMethodManager
import android.widget.EditText
import android.widget.FrameLayout

/** Owns keyboard visibility, focus, and activity-level outside-tap handling. */
internal class InputController(
    private val root: FrameLayout,
    private val stateFor: (Int) -> Renderer.ViewState,
    private val viewFor: (Int) -> View?,
    private val isDisposed: () -> Boolean,
) {
    private var keyboardVisible: Boolean? = null
    private var outsideTapCandidate: Int? = null
    private var touchDownX = 0f
    private var touchDownY = 0f
    private val touchSlop = ViewConfiguration.get(root.context).scaledTouchSlop.toFloat()
    private val keyboardLayoutListener = ViewTreeObserver.OnGlobalLayoutListener {
        val visible = isKeyboardVisible()
        val wasVisible = keyboardVisible
        keyboardVisible = visible
        if (wasVisible == true && !visible) {
            val input = root.findFocus() as? EditText
            if (input != null && stateFor(input.id).blurOnKeyboardHide) {
                blur(input, hideKeyboard = false)
            }
        }
    }

    fun install() {
        root.viewTreeObserver.addOnGlobalLayoutListener(keyboardLayoutListener)
    }

    fun dispose() {
        outsideTapCandidate = null
        if (root.viewTreeObserver.isAlive) {
            root.viewTreeObserver.removeOnGlobalLayoutListener(keyboardLayoutListener)
        }
    }

    fun handleTouchEvent(event: MotionEvent) {
        if (isDisposed()) return
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                outsideTapCandidate = null
                val input = root.findFocus() as? EditText ?: return
                if (!stateFor(input.id).blurOnTapOutside) return

                val location = IntArray(2)
                input.getLocationOnScreen(location)
                val left = location[0].toFloat()
                val top = location[1].toFloat()
                val inside =
                    event.rawX >= left &&
                        event.rawX < left + input.width &&
                        event.rawY >= top &&
                        event.rawY < top + input.height
                if (!inside) {
                    outsideTapCandidate = input.id
                    touchDownX = event.rawX
                    touchDownY = event.rawY
                }
            }
            MotionEvent.ACTION_MOVE -> {
                if (
                    outsideTapCandidate != null &&
                    Renderer.movedBeyondTapSlop(
                        event.rawX - touchDownX,
                        event.rawY - touchDownY,
                        touchSlop,
                    )
                ) {
                    outsideTapCandidate = null
                }
            }
            MotionEvent.ACTION_UP -> {
                val inputId = outsideTapCandidate
                outsideTapCandidate = null
                val input = inputId?.let(viewFor) as? EditText ?: return
                if (input.hasFocus() && stateFor(inputId).blurOnTapOutside) {
                    blur(input, hideKeyboard = true)
                }
            }
            MotionEvent.ACTION_CANCEL -> outsideTapCandidate = null
        }
    }

    fun updateFocus(view: EditText, focused: Boolean) {
        if (focused) {
            if (!view.hasFocus()) view.requestFocus()
            view.post {
                if (view.hasFocus() && view.isAttachedToWindow) {
                    inputMethodManager().showSoftInput(
                        view,
                        InputMethodManager.SHOW_IMPLICIT,
                    )
                }
            }
        } else {
            blur(view, hideKeyboard = true)
        }
    }

    fun blur(view: EditText, hideKeyboard: Boolean) {
        if (view.hasFocus()) {
            root.requestFocus()
            view.clearFocus()
        }
        if (hideKeyboard) {
            inputMethodManager().hideSoftInputFromWindow(view.windowToken, 0)
        }
    }

    private fun inputMethodManager(): InputMethodManager =
        root.context.getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager

    private fun isKeyboardVisible(): Boolean {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            root.rootWindowInsets?.let { insets ->
                return insets.isVisible(WindowInsets.Type.ime())
            }
        }
        val visibleFrame = Rect()
        root.getWindowVisibleDisplayFrame(visibleFrame)
        val rootHeight = root.rootView.height
        return rootHeight > 0 && rootHeight - visibleFrame.bottom > rootHeight * 0.15
    }
}
