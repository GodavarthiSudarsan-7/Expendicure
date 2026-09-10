package com.expendicure.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Backend response handling. [BackendClient.classify] is a pure function of
 * (HTTP status, JSON body) so every branch is covered without a network.
 */
class BackendClientResponseTest {

    @Test fun status201IsCreated() {
        assertTrue(BackendClient.classify(201, """{"id":42,"status":"review"}""") is ForwardResult.Created)
    }

    @Test fun status200IsTreatedAsDuplicate() {
        assertTrue(BackendClient.classify(200, """{"duplicate":true}""") is ForwardResult.Duplicate)
        assertTrue(BackendClient.classify(200, null) is ForwardResult.Duplicate)
        assertTrue(BackendClient.classify(200, "not json") is ForwardResult.Duplicate)
    }

    @Test fun status202CarriesTheIgnoredReason() {
        val r = BackendClient.classify(202, """{"ignored":"not a transaction message"}""")
        assertTrue(r is ForwardResult.Ignored)
        assertEquals("not a transaction message", (r as ForwardResult.Ignored).reason)
    }

    @Test fun status202WithNoReasonStillIgnored() {
        val r = BackendClient.classify(202, "{}")
        assertTrue(r is ForwardResult.Ignored)
        assertEquals("ignored", (r as ForwardResult.Ignored).reason)
    }

    @Test fun status401IsUnauthorized() {
        assertTrue(BackendClient.classify(401, """{"error":"bad token"}""") is ForwardResult.Unauthorized)
    }

    @Test fun other4xxIsRejectedWithCode() {
        val r = BackendClient.classify(400, """{"error":"missing body"}""")
        assertTrue(r is ForwardResult.Rejected)
        assertEquals(400, (r as ForwardResult.Rejected).code)

        assertTrue(BackendClient.classify(404, null) is ForwardResult.Rejected)
        assertTrue(BackendClient.classify(422, null) is ForwardResult.Rejected)
    }

    @Test fun status5xxIsServerErrorWithCode() {
        val r = BackendClient.classify(503, null)
        assertTrue(r is ForwardResult.ServerError)
        assertEquals(503, (r as ForwardResult.ServerError).code)

        assertTrue(BackendClient.classify(500, "boom") is ForwardResult.ServerError)
    }

    @Test fun unexpectedStatusIsRejectedNotACrash() {
        assertTrue(BackendClient.classify(302, null) is ForwardResult.Rejected)
        assertTrue(BackendClient.classify(0, null) is ForwardResult.Rejected)
    }

    @Test fun malformedJsonBodyNeverThrows() {
        // 202 with junk body: reason falls back, no exception
        val r = BackendClient.classify(202, "{ this is not json ")
        assertTrue(r is ForwardResult.Ignored)
    }

    @Test fun safeLogStringsCarryNoSensitiveData() {
        // The status strings surfaced to the UI/log must be fixed and generic.
        listOf(
            ForwardResult.Created,
            ForwardResult.Duplicate,
            ForwardResult.Ignored("not a transaction message"),
            ForwardResult.Unauthorized,
            ForwardResult.Rejected(400),
            ForwardResult.ServerError(500),
            ForwardResult.Unreachable
        ).forEach {
            assertTrue(it.safeLog.isNotBlank())
            assertFalse(it.safeLog.contains("token", ignoreCase = true) && it != ForwardResult.Unauthorized)
        }
        // Unauthorized intentionally says "re-check the token" — no token value, just advice.
        assertFalse(ForwardResult.Unauthorized.safeLog.any { it.isDigit() })
    }
}
