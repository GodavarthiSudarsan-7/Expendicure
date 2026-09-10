package com.expendicure.companion

import org.json.JSONObject
import java.io.BufferedReader
import java.net.HttpURLConnection
import java.net.URL

/**
 * Tiny HTTP client for `POST /api/bank/sms-events`. Uses [HttpURLConnection]
 * (no third-party HTTP dependency).
 *
 * The response-classification logic is a pure function ([classify]) so it can
 * be unit-tested without a network.
 */
sealed class ForwardResult(val safeLog: String) {
    /** 201 — a new event is now in the web review queue. */
    object Created : ForwardResult("Event forwarded successfully")

    /** 200 {duplicate:true} — the backend already has this transaction. */
    object Duplicate : ForwardResult("Event already processed by backend")

    /** 202 {ignored:...} — backend chose not to create an event (unconfigured
     *  sender, OTP/promo/noise). Not an error. */
    class Ignored(val reason: String) : ForwardResult("Event ignored by backend")

    /** 401 — bad/expired ingest token. Setup needs attention. */
    object Unauthorized : ForwardResult("Ingest token was rejected — re-check the token")

    /** 400/4xx — malformed request. */
    class Rejected(val code: Int) : ForwardResult("Event rejected by backend")

    /** 5xx — backend error. */
    class ServerError(val code: Int) : ForwardResult("Backend error while forwarding")

    /** No connectivity / timeout / DNS. Nothing is retried, nothing stored. */
    object Unreachable : ForwardResult("Could not reach Expendicure — event not forwarded")
}

object BackendClient {

    private const val CONNECT_TIMEOUT_MS = 8_000
    private const val READ_TIMEOUT_MS = 12_000

    /** Pure: map an HTTP status + (optional) JSON body to a [ForwardResult]. */
    fun classify(status: Int, jsonBody: String?): ForwardResult {
        val json = runCatching { if (jsonBody.isNullOrBlank()) null else JSONObject(jsonBody) }.getOrNull()
        return when {
            status == 201 -> ForwardResult.Created
            status == 200 && json?.optBoolean("duplicate") == true -> ForwardResult.Duplicate
            status == 200 -> ForwardResult.Duplicate // backend only returns 200 for dedupe
            status == 202 -> ForwardResult.Ignored(json?.optString("ignored").orEmpty().ifBlank { "ignored" })
            status == 401 -> ForwardResult.Unauthorized
            status in 400..499 -> ForwardResult.Rejected(status)
            status in 500..599 -> ForwardResult.ServerError(status)
            else -> ForwardResult.Rejected(status)
        }
    }

    /** Fire one request. Never throws; network failures map to [ForwardResult.Unreachable]. */
    fun postSmsEvent(backendUrl: String, ingestToken: String, jsonPayload: String): ForwardResult {
        var conn: HttpURLConnection? = null
        return try {
            val url = URL("$backendUrl/api/bank/sms-events")
            conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = CONNECT_TIMEOUT_MS
                readTimeout = READ_TIMEOUT_MS
                doOutput = true
                setRequestProperty("Content-Type", "application/json")
                setRequestProperty("Accept", "application/json")
                setRequestProperty("X-Ingest-Token", ingestToken)
                setRequestProperty("User-Agent", "ExpendicureCompanion/1.0")
            }
            conn.outputStream.use { it.write(jsonPayload.toByteArray(Charsets.UTF_8)) }

            val status = conn.responseCode
            val stream = if (status in 200..299) conn.inputStream else conn.errorStream
            val body = stream?.bufferedReader()?.use(BufferedReader::readText)
            classify(status, body)
        } catch (t: Throwable) {
            SafeLog.failure("forward", t)
            ForwardResult.Unreachable
        } finally {
            conn?.disconnect()
        }
    }
}
