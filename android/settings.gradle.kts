/**
 * Framework checkout Gradle settings.
 *
 * The host application packages Python with Chaquopy and owns the direct
 * Python/Kotlin bridge.
 */
pluginManagement {
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

rootProject.name = "Vyne"
include(":host")
