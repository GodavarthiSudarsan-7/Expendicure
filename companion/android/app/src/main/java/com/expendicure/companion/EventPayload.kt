package com.expendicure.companion

import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/**
 * Builds the request body for `POST /api/bank/sms-events`.
 *
 * The Phase-15 contract is `{ "sender", "body" }`. We also include
 * `received_at` (ISO-8601 UTC) for forward-compatibility; the current backend
 * ignores unknown keys and derives the transaction date from the SMS text
 * itself, so this is harmless and requires no backend change.
 *
 * Pure — no Android APIs — so it is unit-testable.
 */
object EventPayload {

    fun isoUtc(millis: Long): String {
        val fmt = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US)
        fmt.timeZone = TimeZone.getTimeZone("UTC")
        return fmt.format(Date(millis))
    }

    /** The exact configured sender is sent (not the decorated on-wire address),
     *  so it always matches the backend's `bank_connections.sender_id`. */
    fun build(configuredSender: String, body: String, receivedAtMillis: Long): String =
        JSONObject().apply {
            put("sender", configuredSender)
            put("body", body)
            put("received_at", isoUtc(receivedAtMillis))
        }.toString()
}
