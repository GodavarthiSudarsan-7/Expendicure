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

    /**
     * Opt-in "private local-network fallback". When on-device parsing cannot
     * produce a usable transaction and this is ON, the RAW SMS body is sent to
     * the user's own Expendicure server so the backend parser can try.
     *
     * Default OFF. When it is off, an unparseable bank SMS is simply dropped
     * and nothing leaves the phone. This is NOT "the SMS never leaves your
     * phone" when it is on — in that mode the raw text does leave the device,
     * to the user's own local server.
     */
    var rawFallbackEnabled: Boolean
        get() = prefs.getBoolean("raw_fallback", false)
        set(v) = prefs.edit().putBoolean("raw_fallback", v).apply()

    // ---------------------------------------------------------------- diagnostics
    // Safe metadata ONLY: fixed stage labels and counters. Never an SMS body,
    // sender address, OTP, account number, reference or token.

    /** The last pipeline stage reached, as a fixed human-readable label. */
    var lastStage: String
        get() = prefs.getString("last_stage", "").orEmpty()
        set(v) = prefs.edit().putString("last_stage", v).apply()

    var smsSeen: Int
        get() = prefs.getInt("c_sms_seen", 0)
        set(v) = prefs.edit().putInt("c_sms_seen", v).apply()

    var senderMatched: Int
        get() = prefs.getInt("c_sender_matched", 0)
        set(v) = prefs.edit().putInt("c_sender_matched", v).apply()

    var parsedOk: Int
        get() = prefs.getInt("c_parsed_ok", 0)
        set(v) = prefs.edit().putInt("c_parsed_ok", v).apply()

    var forwarded: Int
        get() = prefs.getInt("c_forwarded", 0)
        set(v) = prefs.edit().putInt("c_forwarded", v).apply()

    /** Record a stage transition with a timestamp. Safe strings only. */
    fun note(stage: String) {
        lastStage = stage
        lastSyncAtMillis = System.currentTimeMillis()
    }

    fun resetDiagnostics() {
        prefs.edit()
            .putInt("c_sms_seen", 0).putInt("c_sender_matched", 0)
            .putInt("c_parsed_ok", 0).putInt("c_forwarded", 0)
            .putString("last_stage", "").putString("last_status", "")
            .putLong("last_sync_at", 0L)
            .apply()
    }

    val isConfigured: Boolean
        get() = backendUrl.isNotEmpty() && senderId.isNotEmpty() && ingestToken.isNotEmpty()

    fun clear() = prefs.edit().clear().apply()
}
