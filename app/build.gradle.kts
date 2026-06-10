plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "com.kelnine.merge48"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.kelnine.merge48"
        // Adaptive-icon-only resources require 26+; Saga/Seeker run Android 13/14.
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "1.0.0"
    }

    buildTypes {
        release {
            // Keep minification off for the first release; the dApp Store
            // accepts unobfuscated APKs and this avoids ProGuard/MWA issues.
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
    }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.core:core-ktx:1.15.0")

    // Solana Mobile Wallet Adapter (MWA) client
    implementation("com.solanamobile:mobile-wallet-adapter-clientlib-ktx:2.1.1")

    testImplementation("junit:junit:4.13.2")
}
