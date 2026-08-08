#!/usr/bin/env python
"""Generate canonical project template constants for ``vyne.cli.new``.

Produces ``packages/vyne/src/vyne/cli/_templates.py`` from parameterized
template definitions so every producer (new.py) and consumer (tests, docs)
shares one source of truth.

Usage:
    uv run python scripts/generate_project_templates.py          # write
    uv run python scripts/generate_project_templates.py --check  # drift-only
"""

from __future__ import annotations

import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Project root discovery
# ---------------------------------------------------------------------------

def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Canonical template constants
# ---------------------------------------------------------------------------

# These are the canonical parameterized package templates referenced by
# ``vyne.cli.new`` and consumed by ``_rendered_templates()`` below.
# Every string that appears in new.py as inline templates MUST be defined
# here; drift detection compares the concatenated output.

PYTHON_VERSION = "3.14"
DEFAULT_COMPILE_SDK = 35
DEFAULT_TARGET_SDK = 35
DEFAULT_MIN_SDK = 26
DEFAULT_VERSION = "0.1.0"
DEFAULT_VERSION_CODE = 1

MIN_SDK_MINIMUM = 26

# Android Kotlin/AGP version constants — one canonical source
AGP_VERSION = "8.7.3"
KOTLIN_VERSION = "2.0.21"
JAVA_TARGET = "17"
ANDROIDX_ANNOTATION_VERSION = "1.9.1"
CHAQUOPY_VERSION = "17.0.0"


# ---------------------------------------------------------------------------
# Template generators (must stay in sync with vyne.cli.new)
# ---------------------------------------------------------------------------

def _gradle_properties() -> str:
    return """android.useAndroidX=true
android.nonTransitiveRClass=true
org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8
"""


def _root_build_gradle() -> str:
    return f'''plugins {{
    id("com.android.application") version "{AGP_VERSION}" apply false
    id("org.jetbrains.kotlin.android") version "{KOTLIN_VERSION}" apply false
    id("com.chaquo.python") version "{CHAQUOPY_VERSION}" apply false
}}
'''


def _app_build_gradle() -> str:
    return f'''plugins {{
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}}

val appId = providers.gradleProperty("vyne.applicationId").orElse("com.example.vyneapp").get()
val appLabel = providers.gradleProperty("vyne.appLabel").orElse("Vyne App").get()
val appModule = providers.gradleProperty("vyne.appModule").orElse("app").get()
val appSourceFile = file(providers.gradleProperty("vyne.appSource").orElse("app.py").get())
val frameworkPythonDir = file(providers.gradleProperty("vyne.frameworkPythonDir").orElse("../../packages/vyne/src").get())
val hostSourceDir = file(providers.gradleProperty("vyne.hostSourceDir").orElse("../../android/host/src/main/java").get())
val hostResDir = file(providers.gradleProperty("vyne.hostResDir").orElse("../../android/host/src/main/res").get())
val extensionKotlinDirs = providers.gradleProperty("vyne.extensionKotlinDirs").orElse("").get().split(":").filter {{ it.isNotBlank() }}
val extensionResDirs = providers.gradleProperty("vyne.extensionResDirs").orElse("").get().split(":").filter {{ it.isNotBlank() }}
val extensionPythonDirs = providers.gradleProperty("vyne.extensionPythonDirs").orElse("").get().split(":").filter {{ it.isNotBlank() }}
val minSdkValue = providers.gradleProperty("vyne.minSdk").orElse("{DEFAULT_MIN_SDK}").get().toInt()
val targetSdkValue = providers.gradleProperty("vyne.targetSdk").orElse("{DEFAULT_TARGET_SDK}").get().toInt()
val compileSdkValue = providers.gradleProperty("vyne.compileSdk").orElse("{DEFAULT_COMPILE_SDK}").get().toInt()

android {{
    namespace = appId
    compileSdk = compileSdkValue

    defaultConfig {{
        applicationId = appId
        minSdk = minSdkValue
        targetSdk = targetSdkValue
        versionCode = providers.gradleProperty("vyne.versionCode").orElse("1").get().toInt()
        versionName = providers.gradleProperty("vyne.versionName").orElse("1.0").get()
        manifestPlaceholders["vyneAppLabel"] = appLabel
        manifestPlaceholders["vyneAppModule"] = appModule

        ndk {{
            abiFilters += listOf("arm64-v8a", "x86_64")
        }}

    }}

    sourceSets {{
        getByName("main") {{
            java.srcDir(hostSourceDir)
            res.srcDir(hostResDir)
            extensionKotlinDirs.forEach {{ java.srcDir(it) }}
            extensionResDirs.forEach {{ res.srcDir(it) }}
        }}
    }}

    compileOptions {{
        sourceCompatibility = JavaVersion.VERSION_{JAVA_TARGET}
        targetCompatibility = JavaVersion.VERSION_{JAVA_TARGET}
    }}

    kotlinOptions {{
        jvmTarget = "{JAVA_TARGET}"
    }}

    aaptOptions.ignoreAssetsPattern = "android-vyne-dont-ignore-anything"
}}

chaquopy {{
    defaultConfig {{
        version = "{PYTHON_VERSION}"
    }}
    sourceSets {{
        getByName("main") {{
            srcDir(frameworkPythonDir)
            srcDir(appSourceFile.parentFile)
            extensionPythonDirs.forEach {{ srcDir(it) }}
            exclude("android/**", ".venv/**", "tests/**", "**/__pycache__/**")
        }}
    }}
}}

dependencies {{
    implementation("androidx.annotation:annotation:{ANDROIDX_ANNOTATION_VERSION}")
}}
'''


def _settings_gradle() -> str:
    return r'''pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "{name}"
include(":app")
'''


def _android_manifest() -> str:
    return '''<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <application
        android:name="com.chaquo.python.android.PyApplication"
        android:allowBackup="true"
        android:label="${vyneAppLabel}"
        android:supportsRtl="true"
        android:theme="@style/AppTheme">
        <meta-data
            android:name="dev.vyne.MODULE_NAME"
            android:value="${vyneAppModule}" />
        <activity
            android:name="dev.vyne.MainActivity"
            android:exported="true"
            android:launchMode="singleTop"
            android:configChanges="orientation|screenSize">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
'''


# ---------------------------------------------------------------------------
# Output format
# ---------------------------------------------------------------------------

_TEMPLATE_MODULE_HEADER = '''"""Generated project template constants — DO NOT EDIT.

This file is generated by ``scripts/generate_project_templates.py``.
Edit that script instead; run it with ``--check`` to verify drift.
"""

from __future__ import annotations

# fmt: off
# isort: skip_file
'''


def _rendered_module() -> str:
    """Produce the complete ``_templates.py`` file content."""
    # Escape any triple-double-quote sequences in the template values so
    # they do not collide with the outer Python \"\"\" delimiter.
    def _esc(s: str) -> str:
        return s.replace('"""', '\\"""')

    body = f'''{_TEMPLATE_MODULE_HEADER}

PYTHON_VERSION = {PYTHON_VERSION!r}
DEFAULT_COMPILE_SDK = {DEFAULT_COMPILE_SDK}
DEFAULT_TARGET_SDK = {DEFAULT_TARGET_SDK}
DEFAULT_MIN_SDK = {DEFAULT_MIN_SDK}
DEFAULT_VERSION = {DEFAULT_VERSION!r}
DEFAULT_VERSION_CODE = {DEFAULT_VERSION_CODE}

AGP_VERSION = {AGP_VERSION!r}
KOTLIN_VERSION = {KOTLIN_VERSION!r}
JAVA_TARGET = {JAVA_TARGET!r}
ANDROIDX_ANNOTATION_VERSION = {ANDROIDX_ANNOTATION_VERSION!r}
CHAQUOPY_VERSION = {CHAQUOPY_VERSION!r}

MIN_SDK_MINIMUM = {MIN_SDK_MINIMUM}

GRADLE_PROPERTIES = {_gradle_properties()!r}

ROOT_BUILD_GRADLE = """\\
{_esc(_root_build_gradle())}"""

APP_BUILD_GRADLE = """\\
{_esc(_app_build_gradle())}"""

SETTINGS_GRADLE = """\\
{_esc(_settings_gradle())}"""

ANDROID_MANIFEST = """\\
{_esc(_android_manifest())}"""
'''
    return body


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    check = "--check" in sys.argv

    module_text = _rendered_module()
    target = _project_root() / "packages" / "vyne" / "src" / "vyne" / "cli" / "_templates.py"

    if check:
        if not target.exists():
            print(f"ERROR: {target} does not exist. Run without --check to generate.", file=sys.stderr)
            sys.exit(1)
        current = target.read_text(encoding="utf-8")
        if current != module_text:
            print(f"ERROR: {target} is out of date.", file=sys.stderr)
            sys.exit(1)
        print(f"{target} is up to date.")
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(module_text, encoding="utf-8")
    print(f"Wrote {target}")


if __name__ == "__main__":
    main()
