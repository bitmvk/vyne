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

// The placeholder in the line below is replaced by `vyne new` with the app
// directory name rendered as a Kotlin string literal (quotes/backslashes,
// dollar signs, and control characters escaped).  Never substitute the raw
// directory name here.
rootProject.name = {nameLiteral}
include(":app")
