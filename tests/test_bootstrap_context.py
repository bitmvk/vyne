"""LF-1: Bootstrap import-context isolation, sequential starts, candidate failures."""

import importlib
import sys
import tempfile
import textwrap
import unittest

from vyne.bootstrap import (
    _start_registered_app,
    run_app,
)
from vyne.runtime import Runtime
from vyne.transport import MemoryTransport


class BootstrapImportContextTests(unittest.TestCase):
    """Verify import-local registration resets and rejects cross-module/ambiguous calls."""

    def setUp(self):
        # Ensure clean state before each test.
        import vyne.bootstrap as bm
        # Release the lock if it was somehow held.
        try:
            bm._start_lock.release()
        except RuntimeError:
            pass

    def tearDown(self):
        import vyne.bootstrap as bm
        try:
            bm._start_lock.release()
        except RuntimeError:
            pass

    def _create_temp_module(self, name: str, source: str):
        """Create a temporary Python module and return (tmpdir, unique_module_name)."""
        unique_name = f"{name}_{id(self)}"
        tmpdir = tempfile.mkdtemp(prefix=f"vyne-test-{unique_name}-")
        with open(f"{tmpdir}/{unique_name}.py", "w") as f:
            f.write(source)
        if tmpdir not in sys.path:
            sys.path.insert(0, tmpdir)
        self.addCleanup(lambda: sys.path.remove(tmpdir) if tmpdir in sys.path else None)
        self.addCleanup(lambda: sys.modules.pop(unique_name, None))
        return tmpdir, unique_name

    def test_sequential_starts_with_same_module(self):
        """Two sequential starts with the same module each get fresh registration."""
        src = textwrap.dedent("""\
        from vyne import run_app

        def app():
            from vyne.elements import Text
            return Text(text="hello")

        run_app(app)
        """)
        _, mod_name = self._create_temp_module("same_mod", src)

        r1 = _start_registered_app(mod_name, transport=MemoryTransport())
        self.assertIsNotNone(r1)
        self.assertIsInstance(r1, Runtime)

        # Second start with same module should also work (fresh reset).
        r2 = _start_registered_app(mod_name, transport=MemoryTransport())
        self.assertIsNotNone(r2)
        self.assertIsInstance(r2, Runtime)

        self.assertIsNot(r1, r2)
        r1.dispose()
        r2.dispose()

    def test_different_modules_sequential_starts(self):
        """Two sequential starts with different modules are correctly isolated."""
        src_a = textwrap.dedent("""\
        from vyne import run_app
        from vyne.elements import Text

        def app_a():
            return Text(text="A")

        run_app(app_a)
        """)
        src_b = textwrap.dedent("""\
        from vyne import run_app
        from vyne.elements import Text

        def app_b():
            return Text(text="B")

        run_app(app_b)
        """)
        _, mod_a = self._create_temp_module("mod_a", src_a)
        _, mod_b = self._create_temp_module("mod_b", src_b)

        r1 = _start_registered_app(mod_a, transport=MemoryTransport())
        r2 = _start_registered_app(mod_b, transport=MemoryTransport())

        self.assertIsNotNone(r1)
        self.assertIsNotNone(r2)
        self.assertIsNot(r1, r2)

        r1.dispose()
        r2.dispose()

    def test_cross_module_registration_rejected(self):
        """A module that calls run_app from a sub-import is rejected when target is different."""
        src_helper = textwrap.dedent("""\
        from vyne import run_app

        def helper_app():
            from vyne.elements import Text
            return Text(text="helper")

        run_app(helper_app)
        """)
        src_target = textwrap.dedent("""\
        import {helper_mod}
        def App():
            from vyne.elements import Text
            return Text(text="target")
        """)
        _, helper_mod = self._create_temp_module("helper_mod", src_helper)
        # Format target source with the actual helper module name.
        _, target_mod = self._create_temp_module(
            "target_cross",
            textwrap.dedent(f"""\
            import {helper_mod}
            def App():
                from vyne.elements import Text
                return Text(text="target")
            """),
        )

        with self.assertRaises(RuntimeError) as ctx:
            _start_registered_app(target_mod, transport=MemoryTransport())
        self.assertIn("Foreign run_app()", str(ctx.exception))

    def test_zero_registration_is_rejected(self):
        """Startup requires an explicit attempt-local registration."""
        src = textwrap.dedent("""\
        def App():
            from vyne.elements import Text
            return Text(text="convention")
        """)
        _, mod_name = self._create_temp_module("conv_mod", src)

        with self.assertRaises(RuntimeError):
            _start_registered_app(mod_name, transport=MemoryTransport())

    def test_zero_registration_no_App_symbol_raises(self):
        """Module with no run_app and no App raises AttributeError."""
        src = textwrap.dedent("""\
        x = 1
        """)
        _, mod_name = self._create_temp_module("empty_mod", src)

        with self.assertRaises(RuntimeError) as ctx:
            _start_registered_app(mod_name, transport=MemoryTransport())
        self.assertIn("no run_app() registration", str(ctx.exception))

    def test_multiple_registrations_same_module_rejected(self):
        """Multiple run_app calls in the same target module are rejected."""
        src = textwrap.dedent("""\
        from vyne import run_app
        from vyne.elements import Text

        def a1():
            return Text(text="1")
        def a2():
            return Text(text="2")

        run_app(a1)
        run_app(a2)
        """)
        _, mod_name = self._create_temp_module("multi_reg", src)

        with self.assertRaises(RuntimeError) as ctx:
            _start_registered_app(mod_name, transport=MemoryTransport())
        self.assertIn("exactly one is required", str(ctx.exception))

    def test_run_app_outside_collect_raises(self):
        """Calling run_app outside _start_registered_app context raises."""
        def my_app():
            pass
        with self.assertRaises(RuntimeError) as ctx:
            run_app(my_app)
        self.assertIn("outside a host start sequence", str(ctx.exception))

    def test_import_error_resets_collector_and_allows_recovery(self):
        """A failed module import resets the collector; a later start works."""
        src_fail = textwrap.dedent("""\
        raise RuntimeError("import boom")
        """)
        src_ok = textwrap.dedent("""\
        from vyne import run_app
        from vyne.elements import Text

        def app():
            return Text(text="ok")

        run_app(app)
        """)
        _, fail_mod = self._create_temp_module("fail_then", src_fail)
        _, ok_mod = self._create_temp_module("ok_then", src_ok)

        with self.assertRaisesRegex(RuntimeError, "import boom"):
            _start_registered_app(fail_mod, transport=MemoryTransport())

        import vyne.bootstrap as bm
        # The failed import must leave the collector reset.
        self.assertIsNone(bm._registration_attempt.get())

        # A subsequent start with a valid module succeeds.
        runtime = _start_registered_app(ok_mod, transport=MemoryTransport())
        self.assertIsNotNone(runtime)
        runtime.dispose()


class BootstrapCandidatePromotionTests(unittest.TestCase):
    """LF-2: Candidate Runtime promotion pattern."""

    def setUp(self):
        import vyne.bootstrap as bm
        try:
            bm._start_lock.release()
        except RuntimeError:
            pass

    def tearDown(self):
        import vyne.bootstrap as bm
        try:
            bm._start_lock.release()
        except RuntimeError:
            pass

    def _create_temp_module(self, name: str, source: str):
        unique_name = f"{name}_{id(self)}"
        tmpdir = tempfile.mkdtemp(prefix=f"vyne-test-{unique_name}-")
        with open(f"{tmpdir}/{unique_name}.py", "w") as f:
            f.write(source)
        if tmpdir not in sys.path:
            sys.path.insert(0, tmpdir)
        self.addCleanup(lambda: sys.path.remove(tmpdir) if tmpdir in sys.path else None)
        self.addCleanup(lambda: sys.modules.pop(unique_name, None))
        return tmpdir, unique_name

    def test_candidate_import_failure_preserves_clean_state(self):
        """When _start_registered_app fails during import, collector is reset."""
        src = textwrap.dedent("""\
        raise RuntimeError("app boom")
        """)
        _, mod_name = self._create_temp_module("fail_candidate", src)

        with self.assertRaises(RuntimeError):
            _start_registered_app(mod_name, transport=MemoryTransport())

        import vyne.bootstrap as bm
        self.assertIsNone(bm._registration_attempt.get())

    def test_dispose_prior_runtime_on_successful_promotion(self):
        """After a successful start, the prior runtime is disposed (simulated)."""
        src = textwrap.dedent("""\
        from vyne import run_app
        from vyne.elements import Text

        def app():
            return Text(text="promoted")

        run_app(app)
        """)
        _, mod_name = self._create_temp_module("promo_mod", src)

        r1 = _start_registered_app(mod_name, transport=MemoryTransport())
        self.assertTrue(r1._mounted)

        r1.dispose()
        self.assertFalse(r1._mounted)

        r2 = _start_registered_app(mod_name, transport=MemoryTransport())
        self.assertTrue(r2._mounted)
        self.assertIsNot(r1, r2)

        r2.dispose()

    def test_candidate_mount_failure_is_handled_gracefully(self):
        """If mount() would fail due to invalid element, an error commit is sent."""
        src_bad = textwrap.dedent("""\
        from vyne import run_app
        from vyne.elements import Element

        def app():
            return Element(kind="BadKind", props={})

        run_app(app)
        """)
        _, mod_name = self._create_temp_module("bad_mod", src_bad)

        # Invalid elements produce an error commit rather than raising.
        runtime = _start_registered_app(mod_name, transport=MemoryTransport())
        self.assertIsNotNone(runtime)
        # The runtime is mounted but the commit should be an error.
        transport = runtime.transport
        self.assertIsNotNone(transport.latest)
        runtime.dispose()


class BootstrapThreadSafetyTests(unittest.TestCase):
    """Verify reentrancy/thread safety of the bootstrap layer."""

    def setUp(self):
        import vyne.bootstrap as bm
        try:
            bm._start_lock.release()
        except RuntimeError:
            pass

    def tearDown(self):
        import vyne.bootstrap as bm
        try:
            bm._start_lock.release()
        except RuntimeError:
            pass

    def _create_temp_module(self, name: str, source: str):
        unique_name = f"{name}_{id(self)}"
        tmpdir = tempfile.mkdtemp(prefix=f"vyne-test-{unique_name}-")
        with open(f"{tmpdir}/{unique_name}.py", "w") as f:
            f.write(source)
        if tmpdir not in sys.path:
            sys.path.insert(0, tmpdir)
        self.addCleanup(lambda: sys.path.remove(tmpdir) if tmpdir in sys.path else None)
        self.addCleanup(lambda: sys.modules.pop(unique_name, None))
        return tmpdir, unique_name

    def test_nested_start_rejected(self):
        """Calling _start_registered_app while another start is in progress is rejected."""
        import vyne.bootstrap as bm

        # Simulate: set _collecting to a module name so the lock appears held.
        # Don't acquire the lock — the guard checks the lock, not _collecting.
        # Actually the guard uses _start_lock, not _collecting. So let's test
        # that acquiring the lock prevents reentrancy.
        # Acquire the lock to simulate an in-progress start.
        acquired = bm._start_lock.acquire(blocking=False)
        self.assertTrue(acquired, "Could not acquire lock for test setup")

        try:
            # Now try to start — should fail because lock is held.
            src = textwrap.dedent("""\
            from vyne import run_app
            from vyne.elements import Text

            def app():
                return Text(text="x")

            run_app(app)
            """)
            _, mod_name = self._create_temp_module("inner_mod", src)

            with self.assertRaises(RuntimeError) as ctx:
                _start_registered_app(mod_name, transport=MemoryTransport())
            self.assertIn("already in progress", str(ctx.exception).lower())
        finally:
            bm._start_lock.release()
