"""CLI dependency editing contract tests (CLI-01, TL-1, TL-2).

Comprehensive coverage:
- InlineTable siblings/format preservation
- Scalar project.dependencies rejection
- Markers, URL, named-local references
- Case/normalization through PEP 508
- Exact bytes no-op
- Malformed forms with clear rejection
"""

from __future__ import annotations

import unittest

from vyne.cli.dependencies import ensure_vyne_dependency


class DependencyContractTests(unittest.TestCase):
    """TL-1/TL-2: Full dependency editing contract."""

    # -- InlineTable / scalar rejection -------------------------------------

    def test_rejects_scalar_dependencies(self):
        """Scalar project dependencies must be rejected, not silently ignored."""
        text = '[project]\nname = "x"\ndependencies = "single-string"\n'
        with self.assertRaises(RuntimeError) as ctx:
            ensure_vyne_dependency(text, "vyne>=1.0")
        self.assertIn("array", str(ctx.exception).lower())

    def test_preserves_inline_table_format(self):
        """Inline table siblings must survive mutation."""
        text = (
            '[project]\n'
            'name = "x"\n'
            'dependencies = ["requests"]\n'
            'requires-python = ">=3.12"\n'
        )
        result = ensure_vyne_dependency(text, "vyne>=1.0")
        self.assertIn('requires-python', result)
        self.assertIn('">=3.12"', result)

    def test_preserves_inline_table_when_name_is_first(self):
        """Inline table of [project] with name first survives editing."""
        text = (
            '[project]\n'
            'name = "myapp"\n'
            'version = "0.1.0"\n'
            'dependencies = ["click"]\n'
            'description = "A test app"\n'
        )
        result = ensure_vyne_dependency(text, "vyne>=1.0")
        self.assertIn('name = "myapp"', result)
        self.assertIn('version = "0.1.0"', result)
        self.assertIn('description = "A test app"', result)
        self.assertIn('vyne', result)

    # -- Markers ------------------------------------------------------------

    def test_insert_dependency_with_markers(self):
        """PEP 508 markers are preserved."""
        text = '[project]\nname = "x"\ndependencies = ["requests>=2.0; python_version >= \'3.8\'"]\n'
        result = ensure_vyne_dependency(text, 'vyne>=1.0; sys_platform == "linux"')
        import tomllib
        parsed = tomllib.loads(result)
        deps = parsed["project"]["dependencies"]
        self.assertTrue(any("vyne" in d for d in deps))

    def test_noop_with_marker_dependency(self):
        """Existing Vyne with markers is recognized."""
        text = '[project]\nname = "x"\ndependencies = [\n    "vyne>=1.0; python_version >= \'3.12\'",\n]\n'
        self.assertEqual(ensure_vyne_dependency(text, "vyne>=1.0"), text)

    # -- Named local references / paths -------------------------------------

    def test_insert_named_local_reference(self):
        """Path-based dependencies survive editing."""
        text = '[project]\nname = "x"\ndependencies = ["mylib"]\n'
        result = ensure_vyne_dependency(
            text, "vyne @ file:///home/user/vyne"
        )
        import tomllib
        parsed = tomllib.loads(result)
        deps = parsed["project"]["dependencies"]
        self.assertTrue(any("file://" in d for d in deps))

    def test_preserves_path_dependency(self):
        """Local path dependencies are not corrupted."""
        text = (
            '[project]\n'
            'name = "x"\n'
            'dependencies = ["mylib @ file:///home/user/mylib"]\n'
        )
        result = ensure_vyne_dependency(text, "vyne>=1.0")
        import tomllib
        parsed = tomllib.loads(result)
        deps = parsed["project"]["dependencies"]
        self.assertTrue(any("mylib" in d for d in deps))
        self.assertTrue(any("vyne" in d for d in deps))

    # -- URL-based dependencies ----------------------------------------------

    def test_preserves_git_url_dependency(self):
        """Git URL dependencies survive editing."""
        text = (
            '[project]\n'
            'name = "x"\n'
            'dependencies = ["pkg @ git+https://github.com/user/repo.git"]\n'
        )
        result = ensure_vyne_dependency(text, "vyne>=1.0")
        import tomllib
        parsed = tomllib.loads(result)
        deps = parsed["project"]["dependencies"]
        self.assertTrue(any("git+" in d for d in deps))

    # -- Byte-preserving no-op ----------------------------------------------

    def test_exact_bytes_noop(self):
        """No-op returns EXACT same bytes, not just same semantics."""
        text = '[project]\ndependencies = ["vyne==1.0"]\n'
        result = ensure_vyne_dependency(text, "vyne>=2.0")
        self.assertIs(result, text)  # same object
        self.assertEqual(result, text)  # same bytes

    def test_noop_with_extras_preserves_formatting(self):
        """Existing Vyne with extras should not trigger modification."""
        text = '[project]\ndependencies = [\n  "vyne[web]>=1.0",\n]\n'
        result = ensure_vyne_dependency(text, "vyne>=1.0")
        self.assertEqual(result, text)

    # -- Multiple unrelated packages ----------------------------------------

    def test_unrelated_packages_are_untouched(self):
        """Unrelated deps are left exactly as-is."""
        text = (
            '[project]\n'
            'name = "x"\n'
            'dependencies = [\n'
            '    "numpy>=1.25",\n'
            '    "pandas>=2.0",\n'
            '    "matplotlib>=3.7",\n'
            ']\n'
        )
        result = ensure_vyne_dependency(text, "vyne>=1.0")
        self.assertIn('"numpy>=1.25"', result)
        self.assertIn('"pandas>=2.0"', result)
        self.assertIn('"matplotlib>=3.7"', result)
        self.assertIn('"vyne>=1.0"', result)

    # -- Edge cases ----------------------------------------------------------

    def test_empty_pyproject_with_no_project_section(self):
        """Empty pyproject gets a new [project] with dependencies."""
        text = '# Just a comment\n'
        result = ensure_vyne_dependency(text, "vyne>=1.0")
        import tomllib
        parsed = tomllib.loads(result)
        self.assertIn("vyne>=1.0", parsed["project"]["dependencies"])

    def test_noop_on_various_vyne_name_forms(self):
        """All of these are canonical 'vyne' and should be no-ops."""
        variants = [
            "vyne",
            "VYNE",
            "Vyne",
            "vyne[extra]",
            "vyne>=1.0",
            "vyne==0.1.0",
            "VYNE[all]>=2.0",
        ]
        for variant in variants:
            with self.subTest(variant=variant):
                text = f'[project]\ndependencies = ["{variant}"]\n'
                result = ensure_vyne_dependency(text, "vyne>=1.0")
                self.assertEqual(result, text,
                                 f"Should be no-op for {variant}")


class DependencyEditingTests(unittest.TestCase):
    """Insertion, tool-table, multiline, and rejection paths."""

    def test_insert_into_empty_project_table(self):
        text = '[project]\nname = "my-app"\n'
        result = ensure_vyne_dependency(text, "vyne>=1.0")
        self.assertIn("vyne>=1.0", result)
        self.assertIn('name = "my-app"', result)
        import tomllib
        parsed = tomllib.loads(result)
        self.assertIn("vyne>=1.0", parsed["project"]["dependencies"])

    def test_insert_into_empty_dependencies_array(self):
        text = '[project]\nname = "x"\ndependencies = []\n'
        result = ensure_vyne_dependency(text, "vyne>=1.0")
        import tomllib
        parsed = tomllib.loads(result)
        self.assertIn("vyne>=1.0", parsed["project"]["dependencies"])

    def test_insert_into_populated_dependencies(self):
        text = '[project]\nname = "x"\ndependencies = ["requests>=2", "click"]\n'
        result = ensure_vyne_dependency(text, "vyne>=1.0")
        import tomllib
        parsed = tomllib.loads(result)
        deps = parsed["project"]["dependencies"]
        self.assertIn("requests>=2", deps)
        self.assertIn("click", deps)
        self.assertIn("vyne>=1.0", deps)

    def test_creates_project_table_when_missing(self):
        text = '[tool.uv]\npackage = false\n'
        result = ensure_vyne_dependency(text, "vyne>=1.0")
        import tomllib
        parsed = tomllib.loads(result)
        self.assertIn("vyne>=1.0", parsed["project"]["dependencies"])

    def test_inline_project_table_is_preserved(self):
        text = (
            'project = { name = "demo", version = "1.0", '
            'dependencies = ["requests"] }\n'
        )
        result = ensure_vyne_dependency(text, "vyne>=1.0")
        import tomllib
        parsed = tomllib.loads(result)
        self.assertEqual(parsed["project"]["name"], "demo")
        self.assertEqual(parsed["project"]["version"], "1.0")
        self.assertEqual(
            parsed["project"]["dependencies"],
            ["requests", "vyne>=1.0"],
        )

    def test_inline_project_without_dependencies_is_preserved(self):
        text = 'project = { name = "demo", version = "1.0" }\n'
        result = ensure_vyne_dependency(text, "vyne>=1.0")
        import tomllib
        parsed = tomllib.loads(result)
        self.assertEqual(parsed["project"]["name"], "demo")
        self.assertEqual(parsed["project"]["version"], "1.0")
        self.assertEqual(parsed["project"]["dependencies"], ["vyne>=1.0"])

    def test_noop_existing_vyne_direct_url(self):
        text = '[project]\ndependencies = ["vyne @ https://example.test/vyne.whl"]\n'
        self.assertEqual(ensure_vyne_dependency(text, "vyne @ file:///tmp/pkg"), text)

    def test_noop_existing_vyne_underscore_normalized(self):
        text = '[project]\ndependencies = ["vy_ne>=1.0"]\n'
        # "vy_ne" canonicalizes to "vy-ne", not "vyne" — so this inserts.
        result = ensure_vyne_dependency(text, "vyne>=1.0")
        import tomllib
        parsed = tomllib.loads(result)
        deps = parsed["project"]["dependencies"]
        self.assertIn("vy_ne>=1.0", deps)
        self.assertIn("vyne>=1.0", deps)

    def test_vyness_is_not_vyne(self):
        text = '[project]\ndependencies = ["vyness>=1.0"]\n'
        result = ensure_vyne_dependency(text, "vyne>=1.0")
        import tomllib
        parsed = tomllib.loads(result)
        deps = parsed["project"]["dependencies"]
        self.assertIn("vyness>=1.0", deps)
        self.assertIn("vyne>=1.0", deps)

    def test_vyne_core_is_not_vyne(self):
        text = '[project]\ndependencies = ["vyne-core>=1.0"]\n'
        result = ensure_vyne_dependency(text, "vyne>=1.0")
        import tomllib
        parsed = tomllib.loads(result)
        deps = parsed["project"]["dependencies"]
        self.assertIn("vyne-core>=1.0", deps)
        self.assertIn("vyne>=1.0", deps)

    def test_tool_table_before_project_is_preserved(self):
        text = (
            '[tool.example]\n'
            'dependencies = ["other"]\n'
            '\n'
            '[project]\n'
            'name = "x"\n'
        )
        result = ensure_vyne_dependency(text, "vyne>=1.0")
        import tomllib
        parsed = tomllib.loads(result)
        self.assertEqual(parsed["tool"]["example"]["dependencies"], ["other"])
        self.assertIn("vyne>=1.0", parsed["project"]["dependencies"])

    def test_tool_table_after_project_is_preserved(self):
        text = (
            '[project]\n'
            'name = "x"\n'
            'dependencies = ["requests"]\n'
            '\n'
            '[tool.example]\n'
            'dependencies = ["other"]\n'
        )
        result = ensure_vyne_dependency(text, "vyne>=1.0")
        import tomllib
        parsed = tomllib.loads(result)
        self.assertEqual(parsed["tool"]["example"]["dependencies"], ["other"])
        self.assertIn("requests", parsed["project"]["dependencies"])
        self.assertIn("vyne>=1.0", parsed["project"]["dependencies"])

    def test_multiline_array_is_preserved(self):
        text = (
            '[project]\n'
            'name = "x"\n'
            'dependencies = [\n'
            '    "requests>=2.34",\n'
            ']\n'
        )
        result = ensure_vyne_dependency(text, "vyne>=1.0")
        self.assertIn("requests>=2.34", result)
        self.assertIn("vyne>=1.0", result)
        import tomllib
        parsed = tomllib.loads(result)
        self.assertIn("requests>=2.34", parsed["project"]["dependencies"])
        self.assertIn("vyne>=1.0", parsed["project"]["dependencies"])

    def test_comments_are_preserved(self):
        text = (
            '# Top comment\n'
            '[project]\n'
            'name = "x"  # inline\n'
        )
        result = ensure_vyne_dependency(text, "vyne>=1.0")
        self.assertIn("# Top comment", result)

    def test_insert_direct_url_dependency(self):
        text = '[project]\nname = "x"\ndependencies = []\n'
        result = ensure_vyne_dependency(
            text, "vyne @ file:///tmp/vyne-checkout"
        )
        import tomllib
        parsed = tomllib.loads(result)
        self.assertIn(
            "vyne @ file:///tmp/vyne-checkout",
            parsed["project"]["dependencies"],
        )

    def test_rejects_malformed_toml(self):
        text = "this is not toml [[["
        with self.assertRaises(RuntimeError):
            ensure_vyne_dependency(text, "vyne>=1.0")

    def test_rejects_non_string_dependency_entry(self):
        text = '[project]\ndependencies = [42]\n'
        with self.assertRaises(RuntimeError):
            ensure_vyne_dependency(text, "vyne>=1.0")

    def test_rejects_invalid_pep508_entry(self):
        text = '[project]\ndependencies = ["not a valid requirement !!!"]\n'
        with self.assertRaises(RuntimeError):
            ensure_vyne_dependency(text, "vyne>=1.0")


if __name__ == "__main__":
    unittest.main()
