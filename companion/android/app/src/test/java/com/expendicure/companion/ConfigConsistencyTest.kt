package com.expendicure.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Regression tests for the real-world ingestion bug:
 *
 *   "Test Connection" reported success while every real bank SMS timed out and
 *   the Flask server logged no POST at all.
 *
 * Cause: Test Connection posted to the URL TYPED IN THE FORM, while
 * SmsReceiver forwards using the URL PERSISTED in CompanionConfig. Editing the
 * server address (the PC's LAN IP changes often) and pressing Test Connection
 * without pressing Save left the two pointing at different hosts. The saved
 * host no longer existed, so the TCP connect got no answer and failed with
 * SocketTimeoutException — packets that never reached Flask.
 *
 * These tests pin the two invariants that make that impossible:
 *   1. a typed value and a saved value normalise identically, and
 *   2. any divergence between form and saved config is detectable.
 */
class ConfigConsistencyTest {

    // ---------------------------------------------------------- normalisation

    @Test fun normaliseUrlTrimsWhitespaceAndTrailingSlash() {
        assertEquals("http://10.3.17.251:5000", CompanionConfig.normaliseUrl("  http://10.3.17.251:5000/  "))
        assertEquals("http://10.3.17.251:5000", CompanionConfig.normaliseUrl("http://10.3.17.251:5000"))
        assertEquals("https://finance.example.com", CompanionConfig.normaliseUrl("https://finance.example.com///"))
        assertEquals("", CompanionConfig.normaliseUrl(null))
        assertEquals("", CompanionConfig.normaliseUrl("   "))
    }

    @Test fun theCurrentLanAddressIsAnAcceptableUrl() {
        // the address in the bug report
        assertTrue(CompanionConfig.isAcceptableUrl("http://10.3.17.251:5000"))
        // and the previous one, to show a stale value is equally "valid" —
        // validity is NOT reachability, which is why the UI must show it
        assertTrue(CompanionConfig.isAcceptableUrl("http://10.9.45.48:5000"))
    }

    // -------------------------------------------------- unsaved-change detection

    @Test fun identicalFormAndSavedConfigIsNotDirty() {
        assertFalse(
            CompanionConfig.hasUnsavedChanges(
                "http://10.3.17.251:5000", "http://10.3.17.251:5000",
                "HDFCBK", "HDFCBK", tokenEdited = false,
            )
        )
    }

    @Test fun trailingSlashAloneIsNotAnUnsavedChange() {
        assertFalse(
            CompanionConfig.hasUnsavedChanges(
                "http://10.3.17.251:5000/", "http://10.3.17.251:5000",
                " HDFCBK ", "HDFCBK", tokenEdited = false,
            )
        )
    }

    @Test fun aNewlyTypedServerAddressIsDetectedAsUnsaved() {
        // THE BUG: the user typed the new LAN IP and hit Test Connection only.
        assertTrue(
            CompanionConfig.hasUnsavedChanges(
                "http://10.3.17.251:5000", "http://10.9.45.48:5000",
                "HDFCBK", "HDFCBK", tokenEdited = false,
            )
        )
    }

    @Test fun aChangedSenderIsDetectedAsUnsaved() {
        assertTrue(
            CompanionConfig.hasUnsavedChanges(
                "http://10.3.17.251:5000", "http://10.3.17.251:5000",
                "ICICIB", "HDFCBK", tokenEdited = false,
            )
        )
    }

    @Test fun aFreshlyPastedTokenIsDetectedAsUnsaved() {
        assertTrue(
            CompanionConfig.hasUnsavedChanges(
                "http://10.3.17.251:5000", "http://10.3.17.251:5000",
                "HDFCBK", "HDFCBK", tokenEdited = true,
            )
        )
    }

    @Test fun anEmptySavedUrlIsAlwaysDirtyAgainstATypedOne() {
        assertTrue(
            CompanionConfig.hasUnsavedChanges(
                "http://10.3.17.251:5000", "",
                "HDFCBK", "HDFCBK", tokenEdited = false,
            )
        )
    }
}
