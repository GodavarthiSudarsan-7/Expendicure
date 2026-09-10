package com.expendicure.companion

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * The companion's ONLY persistent state. Backed by
 * [EncryptedSharedPreferences] (AES-256, key held in the Android Keystore) so
 * the ingest token is never written to plain SharedPreferences.
 *
 * What is stored:
 *   - backendUrl   (e.g. https://finance.example.com  or  http://192.168.1.10:5000)
 *   - senderId     (e.g. HDFCBK)
 *   - bankName     (display only)
 *   - ingestToken  (the Phase-15 per-connection X-Ingest-Token)
 *   - lastSyncAt / lastStatus  (short status strings for the UI)
 *
 * What is NEVER stored: SMS bodies, OTPs, account numbers, transaction
 * references, message history.
 */
class CompanionConfig private constructor(private val prefs: SharedPreferences) {

    companion object {
        private const val FILE = "expendicure_companion_secure"

        fun get(context: Context): CompanionConfig {
            val masterKey = MasterKey.Builder(context)
                .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                .build()
            val prefs = EncryptedSharedPreferences.create(
                context,
                FILE,
                masterKey,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
            )
            return CompanionConfig(prefs)
        }

        /** true only if the URL is https, or an http URL on a private/LAN host
         *  (explicit dev opt-in). Anything else is rejected. */
        fun isAcceptableUrl(raw: String?): Boolean {
            val url = raw?.trim().orEmpty()
            if (url.isEmpty()) return false
            val lower = url.lowercase()
            if (lower.startsWith("https://")) return true
            if (!lower.startsWith("http://")) return false
            val host = lower.removePrefix("http://").substringBefore('/').substringBefore(':')
            return host == "localhost" ||
                host == "127.0.0.1" ||
                host.startsWith("10.") ||
                host.startsWith("192.168.") ||
                Regex("^172\\.(1[6-9]|2\\d|3[01])\\.").containsMatchIn("$host.") ||
                host.endsWith(".local")
        }
    }

    var backendUrl: String
        get() = prefs.getString("backend_url", "").orEmpty()
        set(v) = prefs.edit().putString("backend_url", v.trim().trimEnd('/')).apply()

    var senderId: String
        get() = prefs.getString("sender_id", "").orEmpty()
        set(v) = prefs.edit().putString("sender_id", v.trim()).apply()

    var bankName: String
        get() = prefs.getString("bank_name", "").orEmpty()
        set(v) = prefs.edit().putString("bank_name", v.trim()).apply()

    var ingestToken: String
        get() = prefs.getString("ingest_token", "").orEmpty()
        set(v) = prefs.edit().putString("ingest_token", v.trim()).apply()

    var lastStatus: String
        get() = prefs.getString("last_status", "").orEmpty()
        set(v) = prefs.edit().putString("last_status", v).apply()

    var lastSyncAtMillis: Long
        get() = prefs.getLong("last_sync_at", 0L)
        set(v) = prefs.edit().putLong("last_sync_at", v).apply()

    val isConfigured: Boolean
        get() = backendUrl.isNotEmpty() && senderId.isNotEmpty() && ingestToken.isNotEmpty()

    fun clear() = prefs.edit().clear().apply()
}
