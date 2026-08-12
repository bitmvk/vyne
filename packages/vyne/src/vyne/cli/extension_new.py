"""Scaffold a new developer-written extension (``vyne extension new``).

Creates ``extensions/<name>/`` with a valid extension.toml, a Python entry
module, and a Kotlin registration object, so the extension compiles and is
discovered by ``vyne build`` immediately.
"""

from __future__ import annotations

from pathlib import Path

from vyne.cli.generation import PlanBuilder

from vyne.cli.extensions import is_valid_identifier


def create_extension(root: Path, name: str, *, force: bool = False) -> Path:
    """Scaffold ``extensions/<name>/`` under *root* (the project root)."""
    if not is_valid_identifier(name):
        raise RuntimeError(
            f"Extension name {name!r} must be a valid Python identifier"
        )
    if name in {"app", "vyne"}:
        raise RuntimeError(
            f"Extension name {name!r} collides with the app or framework "
            "bootstrap module name"
        )
    extension_dir = root / "extensions" / name
    if extension_dir.exists() and any(extension_dir.iterdir()) and not force:
        raise RuntimeError(
            f"Refusing to overwrite non-empty extension directory: {extension_dir}"
        )

    package = f"dev.vyne.ext.{name.lower()}"
    kotlin_object = f"{''.join(part.capitalize() for part in name.split('_'))}Extension"

    manifest = (
        f'android_register = "{package}.{kotlin_object}"\n'
    )
    python_entry = (
        '"""Extension entry module — runs on the device at app startup.\n'
        "\n"
        "The Python side declares NO kinds, props, or events: the Kotlin\n"
        "ElementSpec is the single source of truth, and the host registry\n"
        "is queried at startup. This module only provides widget\n"
        "constructors and the optional pre_launch capture hook.\n"
        "\"\"\"\n"
        "\n"
        "from __future__ import annotations\n"
        "\n"
        "from vyne.elements import Element\n"
        "\n"
        "\n"
        "def MyWidget(**base_props) -> Element:\n"
        "    \"\"\"A widget backed by this extension's native view.\"\"\"\n"
        "    return Element(\"MyWidget\", props={**base_props})\n"
        "\n"
        "\n"
        "def on_launch(context) -> None:\n"
        "    \"\"\"Capture function: compose into the app's pre_launch hook.\"\"\"\n"
        "    pass\n"
    )
    kotlin_source = (
        "/**\n"
        " * Extension registration — the single source of truth for the kind.\n"
        " * Python queries the frozen registry at startup and builds its\n"
        " * validation tables from this ElementSpec.\n"
        " */\n"
        f"package {package}\n"
        "\n"
        "import android.content.Context\n"
        "import dev.vyne.ElementRegistry\n"
        "import dev.vyne.ElementSpec\n"
        "\n"
        f"object {kotlin_object} {{\n"
        "\n"
        "    internal fun register(context: Context, registry: ElementRegistry) {\n"
        "        registry.register(\n"
        "            ElementSpec(\n"
        "                kind = \"MyWidget\",\n"
        "                create = {{ MyWidgetView(it.context) }},\n"
        "            ),\n"
        "        )\n"
        "    }\n"
        "}\n"
        "\n"
        "/** A minimal native view placeholder. */\n"
        f"class MyWidgetView(context: Context) : android.view.View(context)\n"
    )

    builder = PlanBuilder(extension_dir)
    builder.add_file("extension.toml", manifest)
    builder.add_file(f"python/{name}.py", python_entry)
    builder.add_file("android/MyWidgetView.kt", kotlin_source)
    plan = builder.preflight()
    try:
        plan.apply(force=force)
    finally:
        plan.cleanup()
    return extension_dir
