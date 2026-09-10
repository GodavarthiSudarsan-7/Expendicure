plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.expendicure.companion"
    compileSdk = 34
    // Pin to a build-tools release actually installed on this machine (AGP 8.5.2
    // would otherwise ask for 34.0.0). 35.0.0 is fully compatible with AGP 8.5.
    buildToolsVersion = "35.0.0"

    defaultConfig {
        applicationId = "com.expendicure.companion"
        minSdk = 26            // adaptive icons + modern Keystore; covers ~99% of devices
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        release {
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
        viewBinding = true
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")
    // Encrypted storage for the ingest token (Android Keystore-backed).
    implementation("androidx.security:security-crypto:1.1.0-alpha06")
    // Kotlin coroutines — used only for a short-lived forward task in the
    // receiver's goAsync() window. No persistent queue is created.
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
