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
    // The iOS app links this as a static framework named Shared (migration step 3). Xcode builds
    // it through the embedAndSignAppleFrameworkForXcode task; see ios/project.yml.
    listOf(iosArm64(), iosSimulatorArm64()).forEach { target ->
        target.binaries.framework {
            baseName = "Shared"
            isStatic = true
        }
    }

    sourceSets {
        commonTest.dependencies {
            implementation(libs.kotlin.test)
        }
    }
}
