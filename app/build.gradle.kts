plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace = "com.sorghum.capture"
    compileSdk {
        version = release(36)
    }

    defaultConfig {
        applicationId = "com.sorghum.capture"
        // CameraX supports API 23+; 24 matches the other projects on this machine.
        minSdk = 24
        targetSdk = 36
        versionCode = 1
        versionName = "0.1"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"))
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    buildFeatures {
        compose = true
    }
    androidResources {
        // The species model is memory-mapped straight from the APK, which needs it stored uncompressed.
        noCompress += "tflite"
    }
    kotlinOptions {
        jvmTarget = "11"
    }
}

dependencies {
    // All capture logic (frame, guidance, quality, sample) lives in the shared KMP core.
    implementation(project(":shared"))

    // Android and lifecycle basics.
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.activity.compose)

    // UI.
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.material3)

    // Camera: preview, analysis frames, and still capture. CameraX has no network access.
    implementation(libs.androidx.camera.core)
    implementation(libs.androidx.camera.camera2)
    implementation(libs.androidx.camera.lifecycle)
    implementation(libs.androidx.camera.view)

    // On-device model runner for the species model (ADR-0010). Runs locally; no network code.
    implementation(libs.litert)

    // Adapter-side pure code (e.g. pixel conversion) is tested on the JVM.
    testImplementation(libs.junit)
}
