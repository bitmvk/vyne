import com.android.build.api.dsl.ManagedVirtualDevice

/**
 * Build configuration for the Vyne host app.
 *
 * Responsibilities:
 * - Compile the Kotlin host code (Renderer, MainActivity, etc.).
 * - Let Chaquopy package and initialize Python.
 * - Add the Vyne framework and the user's app module to Python sources.
 */
plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

val appId = providers.gradleProperty("vyne.applicationId").orElse("dev.vyne").get()
val appLabel = providers.gradleProperty("vyne.appLabel").orElse("Vyne").get()
val appModule = providers.gradleProperty("vyne.appModule").orElse("app").get()
val appSourcePath = providers.gradleProperty("vyne.appSource").orNull
val appSourceFile = if (appSourcePath != null) {
    file(appSourcePath)
} else {
    rootProject.file("../examples/app.py")
}
val frameworkPythonPath = providers.gradleProperty("vyne.frameworkPythonDir").orNull
val frameworkPythonDir = if (frameworkPythonPath != null) {
    file(frameworkPythonPath)
} else {
    rootProject.file("../packages/vyne/src")
}
val materialPythonPath = providers.gradleProperty("vyne.materialPythonDir").orNull
val materialPythonDir = if (materialPythonPath != null) {
    file(materialPythonPath)
} else {
    rootProject.file("../packages/vyne-material/src")
}
val extensionKotlinDirs = providers.gradleProperty("vyne.extensionKotlinDirs")
    .orElse("").get().split(":").filter { it.isNotBlank() }
val extensionResDirs = providers.gradleProperty("vyne.extensionResDirs")
    .orElse("").get().split(":").filter { it.isNotBlank() }
val extensionPythonDirs = providers.gradleProperty("vyne.extensionPythonDirs")
    .orElse("").get().split(":").filter { it.isNotBlank() }
val minSdkValue = providers.gradleProperty("vyne.minSdk").orElse("26").get().toInt()
val targetSdkValue = providers.gradleProperty("vyne.targetSdk").orElse("35").get().toInt()
val compileSdkValue = providers.gradleProperty("vyne.compileSdk").orElse("35").get().toInt()

android {
    namespace = appId
    compileSdk = compileSdkValue

    defaultConfig {
        applicationId = appId
        minSdk = minSdkValue
        targetSdk = targetSdkValue
        versionCode = 1
        versionName = "0.1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        manifestPlaceholders["vyneAppLabel"] = appLabel
        manifestPlaceholders["vyneAppModule"] = appModule

        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }

    }

    sourceSets {
        getByName("main") {
            extensionKotlinDirs.forEach { java.srcDir(it) }
            extensionResDirs.forEach { res.srcDir(it) }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    testOptions {
        // Main-source diagnostics (android.util.Log) must be callable from
        // JVM unit tests; unmocked calls would throw instead of no-op.
        unitTests.isReturnDefaultValues = true
        managedDevices {
            devices {
                for (api in listOf(26, 29, 30, 35)) {
                    maybeCreate<ManagedVirtualDevice>("api$api").apply {
                        device = "Pixel 2"
                        apiLevel = api
                        systemImageSource = "aosp"
                    }
                }
            }
            groups {
                maybeCreate("supportedApiMatrix").apply {
                    targetDevices.addAll(
                        listOf(
                            devices["api26"], devices["api29"],
                            devices["api30"], devices["api35"],
                        )
                    )
                }
            }
        }
    }

    lint {
        warningsAsErrors = true
        // Dependency updates are reviewed separately from source correctness.
        disable += "GradleDependency"
    }

    aaptOptions.ignoreAssetsPattern = "android-vyne-dont-ignore-anything"
}

chaquopy {
    defaultConfig {
        version = "3.14"
    }
    sourceSets {
        getByName("main") {
            srcDir(frameworkPythonDir)
            srcDir(appSourceFile.parentFile)
            if (materialPythonDir.isDirectory) {
                srcDir(materialPythonDir)
            }
            extensionPythonDirs.forEach { srcDir(it) }
        }
    }
}

dependencies {
    implementation("androidx.annotation:annotation:1.8.2")
    implementation("androidx.activity:activity:1.8.1")
    testImplementation(kotlin("test"))
    testImplementation("org.json:json:20240303")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation(kotlin("test"))
}
