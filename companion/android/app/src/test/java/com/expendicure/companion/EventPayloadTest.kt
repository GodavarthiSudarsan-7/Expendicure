package com.expendicure.companion

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Payload construction for POST /api/bank/sms-events. */
class EventPayloadTest {

    @Test fun buildsTheExactPhase15Contract() {
        val json = JSONObject(EventPayload.build("HDFCBK", "Rs 100 debited", 0L))
        assertEquals("HDFCBK", json.getString("sender"))
        assertEquals("Rs 100 debited", json.getString("body"))
        assertTrue(json.has("received_at"))
    }

    @Test fun sendsTheConfiguredSenderNotTheDecoratedWireAddress() {
        // caller passes cfg.senderId ("HDFCBK"), never "AD-HDFCBK-S"
        val json = JSONObject(EventPayload.build("HDFCBK", "body", 123L))
        assertEquals("HDFCBK", json.getString("sender"))
    }

    @Test fun receivedAtIsIso8601Utc() {
        // 2021-01-01T00:00:00Z
        assertEquals("2021-01-01T00:00:00Z", EventPayload.isoUtc(1_609_459_200_000L))
    }

    @Test fun receivedAtFormatShapeIsStable() {
        val s = EventPayload.isoUtc(System.currentTimeMillis())
        assertTrue(s.matches(Regex("^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}Z$")))
    }

    @Test fun bodyWithQuotesAndNewlinesStaysValidJson() {
        val raw = "Rs 1,200.50 spent\n\"card\" XX99\tref 4471"
        val json = JSONObject(EventPayload.build("HDFCBK", raw, 0L))
        assertEquals(raw, json.getString("body"))
    }

    @Test fun onlyTheThreeExpectedKeysArePresent() {
        val json = JSONObject(EventPayload.build("HDFCBK", "x", 0L))
        val keys = json.keys().asSequence().toSet()
        assertEquals(setOf("sender", "body", "received_at"), keys)
    }

    // --- buildRaw: the opt-in "private local-network fallback" ----------------

    @Test fun buildRawCarriesTheRawBody() {
        val json = JSONObject(EventPayload.buildRaw("HDFCBK", "Rs 100 debited", 0L))
        assertEquals("HDFCBK", json.getString("sender"))
        assertEquals("Rs 100 debited", json.getString("body"))
        assertEquals(setOf("sender", "body", "received_at"),
            json.keys().asSequence().toSet())
    }

    // --- buildStructured: the preferred path — the raw SMS never leaves the phone

    private fun parsed(
        status: String = SmsTransactionParser.STATUS_CONFIDENT,
        direction: String? = SmsTransactionParser.DEBIT,
        amount: String? = "5000.00",
        merchant: String? = "AMAZON",
        maskedAccount: String? = "4821",
        bankRef: String? = "402312345678",
        occurredOn: String? = "2026-09-10",
        occurredAt: String? = "14:30:00",
        templateId: String? = "hdfc_debit_v1",
    ) = SmsTransactionParser.ParsedTxn(
        status = status, direction = direction, amount = amount, merchant = merchant,
        maskedAccount = maskedAccount, bankRef = bankRef, occurredOn = occurredOn,
        occurredAt = occurredAt, templateId = templateId,
    )

    @Test fun buildStructuredNeverIncludesTheRawBody() {
        val json = JSONObject(EventPayload.buildStructured("HDFCBK", parsed(), 0L))
        assertFalse(json.has("body"))
        assertEquals(setOf("sender", "received_at", "transaction"),
            json.keys().asSequence().toSet())
    }

    @Test fun buildStructuredNestsTheTransactionFields() {
        val json = JSONObject(EventPayload.buildStructured("HDFCBK", parsed(), 1_609_459_200_000L))
        assertEquals("HDFCBK", json.getString("sender"))
        assertEquals("2021-01-01T00:00:00Z", json.getString("received_at"))
        val txn = json.getJSONObject("transaction")
        assertEquals("5000.00", txn.getString("amount"))
        assertEquals("debit", txn.getString("direction"))
        assertEquals("AMAZON", txn.getString("merchant"))
        assertEquals("4821", txn.getString("masked_account"))
        assertEquals("402312345678", txn.getString("bank_ref"))
        assertEquals("2026-09-10", txn.getString("occurred_on"))
        assertEquals("14:30:00", txn.getString("occurred_at"))
        assertEquals("hdfc_debit_v1", txn.getString("template_id"))
        assertEquals("confident", txn.getString("parse_status"))
    }

    @Test fun buildStructuredLowercasesDirection() {
        val json = JSONObject(EventPayload.buildStructured("HDFCBK", parsed(direction = "CREDIT"), 0L))
        assertEquals("credit", json.getJSONObject("transaction").getString("direction"))
    }

    @Test fun buildStructuredOmitsUnknownOptionalFields() {
        val thin = parsed(
            status = SmsTransactionParser.STATUS_REVIEW,
            merchant = null, maskedAccount = null, bankRef = null,
            occurredOn = null, occurredAt = null, templateId = null,
        )
        val txn = JSONObject(EventPayload.buildStructured("HDFCBK", thin, 0L)).getJSONObject("transaction")
        assertEquals(setOf("amount", "direction", "parse_status"),
            txn.keys().asSequence().toSet())
        assertEquals("review", txn.getString("parse_status"))
    }
}
