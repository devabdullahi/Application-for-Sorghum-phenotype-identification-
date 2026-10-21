// Shared KMP core: all capture logic, used by the Android app now and by the iOS app after
// migration step 3 (docs/architecture/ARCHITECTURE.md section 8). commonMain may only use the
// Kotlin standard library, so the same code compiles for the JVM and for iOS.
plugins {
    alias(libs.plugins.kotlin.multiplatform)
}

kotlin {
    // The Android app consumes the JVM target; it must match the app's bytecode level.
    jvm {
        compilerOptions {
            jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_11)
        }
    }
    // iOS targets compile now so any non-portable API in commonMain fails the build early.
    // The XCFramework for the iOS app is added in migration step 3.
    iosArm64()
    iosSimulatorArm64()

    sourceSets {
        commonTest.dependencies {
            implementation(libs.kotlin.test)
        }
    }
}
