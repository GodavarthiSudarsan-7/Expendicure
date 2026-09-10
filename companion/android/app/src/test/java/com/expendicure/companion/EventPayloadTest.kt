package com.expendicure.companion

import org.json.JSONObject
import org.junit.Assert.assertEquals
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
}
