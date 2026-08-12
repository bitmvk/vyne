plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

val appId = providers.gradleProperty("vyne.applicationId").orElse("com.example.vyneapp").get()
val appLabel = providers.gradleProperty("vyne.appLabel").orElse("Vyne App").get()
val appModule = providers.gradleProperty("vyne.appModule").orElse("app").get()
val appSourceFile = file(providers.gradleProperty("vyne.appSource").orElse("app.py").get())
val frameworkPythonDir = file(providers.gradleProperty("vyne.frameworkPythonDir").orElse("../../packages/vyne/src").get())
val materialPythonPath = providers.gradleProperty("vyne.materialPythonDir").orNull
val materialPythonDir = if (materialPythonPath != null) file(materialPythonPath) else null
val hostSourceDir = file(providers.gradleProperty("vyne.hostSourceDir").orElse("../../android/host/src/main/java").get())
val hostResDir = file(providers.gradleProperty("vyne.hostResDir").orElse("../../android/host/src/main/res").get())
val extensionKotlinDirs = providers.gradleProperty("vyne.extensionKotlinDirs").orElse("").get().split(":").filter { it.isNotBlank() }
val extensionResDirs = providers.gradleProperty("vyne.extensionResDirs").orElse("").get().split(":").filter { it.isNotBlank() }
val extensionPythonDirs = providers.gradleProperty("vyne.extensionPythonDirs").orElse("").get().split(":").filter { it.isNotBlank() }
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
        versionCode = providers.gradleProperty("vyne.versionCode").orElse("1").get().toInt()
        versionName = providers.gradleProperty("vyne.versionName").orElse("1.0").get()
        manifestPlaceholders["vyneAppLabel"] = appLabel
        manifestPlaceholders["vyneAppModule"] = appModule

        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }

    }

    sourceSets {
        getByName("main") {
            java.srcDir(hostSourceDir)
            res.srcDir(hostResDir)
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
            if (materialPythonDir != null) {
                srcDir(materialPythonDir)
            }
            extensionPythonDirs.forEach { srcDir(it) }
            exclude("android/**", ".venv/**", "tests/**", "**/__pycache__/**")
        }
    }
}

dependencies {
    implementation("androidx.activity:activity:1.8.1")
    implementation("androidx.annotation:annotation:1.9.1")
}
