plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.chaquo.python")
}

val releaseStore = providers.environmentVariable("SWU_ANDROID_KEYSTORE").orNull
val releasePassword = providers.environmentVariable("SWU_ANDROID_KEYSTORE_PASSWORD").orNull
val releaseAlias = providers.environmentVariable("SWU_ANDROID_KEY_ALIAS").orNull
val releaseCredentials = listOf(releaseStore, releasePassword, releaseAlias)
require(releaseCredentials.all { it == null } || releaseCredentials.all { !it.isNullOrBlank() }) {
    "Provide all Android release signing variables together."
}
val signedRelease = releaseCredentials.all { !it.isNullOrBlank() }
val testedBuildType = providers.gradleProperty("swuTestBuildType").getOrElse("debug")
require(testedBuildType in setOf("debug", "release")) { "Unsupported Android test build type." }

android {
    namespace = "io.github.maximorabyte.swucheckin"
    compileSdk = 36
    defaultConfig {
        applicationId = "io.github.maximorabyte.swucheckin"
        minSdk = 24
        targetSdk = 36
        versionCode = 5
        versionName = "1.0.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
    }
    buildFeatures { compose = true; buildConfig = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    signingConfigs {
        if (signedRelease) create("previewRelease") {
            storeFile = file(releaseStore!!)
            storePassword = releasePassword
            keyAlias = releaseAlias
            keyPassword = releasePassword
            enableV1Signing = true
            enableV2Signing = true
            enableV3Signing = true
        }
    }
    buildTypes {
        getByName("debug") {
            applicationIdSuffix = ".feasibility"
            versionNameSuffix = "-debug"
        }
        getByName("release") {
            isMinifyEnabled = false
            isDebuggable = false
            if (signedRelease) signingConfig = signingConfigs.getByName("previewRelease")
        }
    }
    testBuildType = testedBuildType
    sourceSets.getByName("release").assets.srcDir("build/generated/release-provenance")
}

// Debug CI needs no release secrets. A release build must never silently emit
// an unsigned or temporary-debug-signed distribution candidate.
tasks.matching { it.name == "preReleaseBuild" }.configureEach {
    doFirst { require(signedRelease) { "Android release build requires the protected persistent signing key." } }
}

chaquopy {
    defaultConfig {
        version = "3.13"
        pip { install("-r", "../requirements-android.txt") }
    }
    sourceSets {
        getByName("main") {
            srcDir("../../src")
        }
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2025.12.01")
    implementation(composeBom)
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.compose.material3:material3")
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:rules:1.6.1")
    androidTestImplementation(composeBom)
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
}
