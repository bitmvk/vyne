from __future__ import annotations

import unittest
from pathlib import Path


class DirectBridgeTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1]

    def test_custom_cpython_jni_bridge_is_removed(self):
        cpp = self.ROOT / "android" / "runtime" / "src" / "main" / "cpp"
        runtime_java = (
            self.ROOT
            / "android"
            / "runtime"
            / "src"
            / "main"
            / "java"
            / "dev"
            / "vyne"
            / "runtime"
        )

        self.assertFalse((cpp / "native_bridge.c").exists())
        self.assertFalse((cpp / "CMakeLists.txt").exists())
        self.assertFalse((runtime_java / "NativeBridge.kt").exists())
        self.assertFalse((runtime_java / "PythonRuntime.kt").exists())

    def test_host_uses_chaquopy_direct_calls(self):
        gradle = (
            self.ROOT / "android" / "host" / "build.gradle.kts"
        ).read_text(encoding="utf-8")
        activity = (
            self.ROOT
            / "android"
            / "host"
            / "src"
            / "main"
            / "java"
            / "dev"
            / "vyne"
            / "MainActivity.kt"
        ).read_text(encoding="utf-8")

        self.assertIn('id("com.chaquo.python")', gradle)
        self.assertIn('"start_direct"', activity)
        self.assertIn("onNewIntent", activity)
        self.assertIn('"deliver_launch_direct"', activity)
        self.assertIn('"dispatch_event_direct"', activity)
        self.assertIn('"dispatch_external_callbacks_direct"', activity)
        self.assertNotIn("pending.callback.call(", activity)
        self.assertNotIn("PythonRuntime", activity)

    def test_rotation_keeps_the_python_runtime_alive(self):
        manifest = (
            self.ROOT
            / "android"
            / "host"
            / "src"
            / "main"
            / "AndroidManifest.xml"
        ).read_text(encoding="utf-8")
        activity = (
            self.ROOT
            / "android"
            / "host"
            / "src"
            / "main"
            / "java"
            / "dev"
            / "vyne"
            / "MainActivity.kt"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'android:configChanges="orientation|screenSize"',
            manifest,
        )
        self.assertIn("override fun onConfigurationChanged", activity)
        self.assertIn("renderer.root.requestApplyInsets()", activity)

    def test_direct_host_exposes_one_json_commit_call(self):
        source = (
            self.ROOT
            / "android"
            / "host"
            / "src"
            / "main"
            / "java"
            / "dev"
            / "vyne"
            / "DirectRenderHost.kt"
        ).read_text(encoding="utf-8")

        self.assertIn("fun commitJson(json: String)", source)
        self.assertIn("fun getActivity()", source)
        self.assertIn("fun createCallback(", source)
        # The typed-column codec and batch APIs are gone from the host.
        self.assertNotIn("fun mountNodes(", source)
        self.assertNotIn("fun commitPropBatch(", source)
        self.assertNotIn("fun setPropBatch(", source)
        self.assertNotIn("jbyteArray", source)
        self.assertNotIn("jlongArray", source)
        self.assertNotIn("jdoubleArray", source)
        self.assertNotIn("jstringArray", source)

    def test_user_callback_is_a_small_typed_android_surface(self):
        source = (
            self.ROOT
            / "android"
            / "host"
            / "src"
            / "main"
            / "java"
            / "dev"
            / "vyne"
            / "VyneCallback.kt"
        ).read_text(encoding="utf-8")

        self.assertIn("interface VyneCallback", source)
        self.assertIn("fun invoke(payload: Any?)", source)
        self.assertIn("fun dispose()", source)
        self.assertIn("data class ExternalPythonTask", source)


if __name__ == "__main__":
    unittest.main()
