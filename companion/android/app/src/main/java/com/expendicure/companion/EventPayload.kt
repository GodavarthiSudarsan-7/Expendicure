package com.expendicure.companion

import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/**
 * Builds the request body for `POST /api/bank/sms-events`.
 *
 * TWO shapes, and the difference is a privacy decision:
 *
 *  1. [buildStructured] — the PREFERRED production path. The SMS was parsed on
 *     the phone by [SmsTransactionParser] and only the structured transaction
 *     leaves the device. The raw message text is never transmitted.
 *
 *  2. [buildRaw] — a compatibility fallback that DOES transmit the raw SMS body
 *     to the user's own local server so the backend parser can try. It is OFF
 *     by default and requires explicit user opt-in
 *     ([CompanionConfig.rawFallbackEnabled]). It must be described as a
 *     "private local-network fallback" — never as "the SMS never leaves your
 *     phone", because in this mode it does leave the phone.
 *
 * Pure — no Android APIs — so it is unit-testable.
 */
object EventPayload {

    fun isoUtc(millis: Long): String {
        val fmt = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US)
        fmt.timeZone = TimeZone.getTimeZone("UTC")
        return fmt.format(Date(millis))
    }

    /**
     * Structured, privacy-preserving payload. The exact CONFIGURED sender is
     * sent (not the carrier-decorated on-wire address) so it always lines up
     * with the backend's `bank_connections.sender_id`.
     *
     * `direction` is emitted lowercase ("debit" / "credit"); the backend
     * normalises case either way.
     */
    fun buildStructured(
        configuredSender: String,
        parsed: SmsTransactionParser.ParsedTxn,
        receivedAtMillis: Long,
    ): String {
        val txn = JSONObject()
        txn.put("amount", parsed.amount)
        txn.put("direction", parsed.direction?.lowercase(Locale.US))
        parsed.merchant?.let { txn.put("merchant", it) }
        parsed.maskedAccount?.let { txn.put("masked_account", it) }
        parsed.bankRef?.let { txn.put("bank_ref", it) }
        parsed.occurredOn?.let { txn.put("occurred_on", it) }
        parsed.occurredAt?.let { txn.put("occurred_at", it) }
        parsed.templateId?.let { txn.put("template_id", it) }
        txn.put("parse_status", parsed.status)

        return JSONObject().apply {
            put("sender", configuredSender)
            put("received_at", isoUtc(receivedAtMillis))
            put("transaction", txn)
        }.toString()
    }

    /**
     * Raw-body payload — the opt-in "private local-network fallback".
     * Only used when on-device parsing could not produce a usable transaction
     * AND the user has explicitly enabled the fallback.
     */
    fun buildRaw(configuredSender: String, body: String, receivedAtMillis: Long): String =
        JSONObject().apply {
            put("sender", configuredSender)
            put("body", body)
            put("received_at", isoUtc(receivedAtMillis))
        }.toString()

    /** Retained name for the connectivity self-test, which sends a sentinel body. */
    fun build(configuredSender: String, body: String, receivedAtMillis: Long): String =
        buildRaw(configuredSender, body, receivedAtMillis)
}
