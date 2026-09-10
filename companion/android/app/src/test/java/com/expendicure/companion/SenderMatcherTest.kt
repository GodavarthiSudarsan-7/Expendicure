package com.expendicure.companion

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Local, offline tests for the sender-matching and noise pre-filter logic.
 * No SMS content from a real device is used — only synthetic samples.
 */
class SenderMatcherTest {

    // --- sender matching: the configured token IS the sender ---------------

    @Test fun exactMatchIgnoringCase() {
        assertTrue(SenderMatcher.matches("HDFCBK", "hdfcbk"))
        assertTrue(SenderMatcher.matches("  hdfcbk ", "HDFCBK"))
    }

    @Test fun matchesDecoratedCarrierHeaderSegments() {
        assertTrue(SenderMatcher.matches("AD-HDFCBK", "HDFCBK"))
        assertTrue(SenderMatcher.matches("VM-HDFCBK-S", "HDFCBK"))
        assertTrue(SenderMatcher.matches("JD-HDFCBK", "HDFCBK"))
        assertTrue(SenderMatcher.matches("BP.HDFCBK", "HDFCBK"))
        assertTrue(SenderMatcher.matches("BW HDFCBK", "HDFCBK"))
    }

    // --- configured-sender rejection --------------------------------------

    @Test fun rejectsDifferentBank() {
        assertFalse(SenderMatcher.matches("AD-ICICIB", "HDFCBK"))
        assertFalse(SenderMatcher.matches("SBIINB", "HDFCBK"))
    }

    @Test fun rejectsPartialSubstringThatIsNotAWholeSegment() {
        // "HDFCBK" must not match "HDFCBKX" or "XHDFCBK" as a segment
        assertFalse(SenderMatcher.matches("AD-HDFCBKX", "HDFCBK"))
        assertFalse(SenderMatcher.matches("MYHDFCBK", "HDFCBK"))
    }

    @Test fun rejectsWhenEitherSideIsBlank() {
        assertFalse(SenderMatcher.matches(null, "HDFCBK"))
        assertFalse(SenderMatcher.matches("HDFCBK", null))
        assertFalse(SenderMatcher.matches("", "HDFCBK"))
        assertFalse(SenderMatcher.matches("HDFCBK", "   "))
    }

    @Test fun rejectsAPhoneNumberAsSender() {
        // A user mobile number must never be treated as the bank sender ID.
        assertFalse(SenderMatcher.matches("+919876543210", "HDFCBK"))
        assertFalse(SenderMatcher.matches("9876543210", "HDFCBK"))
    }

    // --- obvious-noise pre-filter (OTP / promo) --------------------------

    @Test fun flagsObviousOtpMessages() {
        assertTrue(SenderMatcher.looksLikeObviousNoise("123456 is your OTP for login. Do not share it with anyone."))
        assertTrue(SenderMatcher.looksLikeObviousNoise("Your one-time password is 998812"))
        assertTrue(SenderMatcher.looksLikeObviousNoise("Use verification code 4471 to proceed"))
    }

    @Test fun flagsObviousPromoMessages() {
        assertTrue(SenderMatcher.looksLikeObviousNoise("FLAT 50% off this weekend only. Hurry, apply now!"))
        assertTrue(SenderMatcher.looksLikeObviousNoise("You are pre-approved for a personal loan. Apply now."))
    }

    @Test fun flagsEmptyBody() {
        assertTrue(SenderMatcher.looksLikeObviousNoise(""))
        assertTrue(SenderMatcher.looksLikeObviousNoise("   "))
        assertTrue(SenderMatcher.looksLikeObviousNoise(null))
    }

    @Test fun doesNotFlagRealDebitOrCreditAlerts() {
        assertFalse(SenderMatcher.looksLikeObviousNoise(
            "Rs 450.00 debited from a/c XX1234 on 09-Sep for UPI/merchant. Avl bal Rs 1200.00"))
        assertFalse(SenderMatcher.looksLikeObviousNoise(
            "INR 25000 credited to account XX9988 by NEFT. Avl bal INR 41200"))
    }

    @Test fun doesNotFlagATransactionThatAlsoSaysDoNotShare() {
        // OTP keyword present, but a completed-txn verb wins -> let backend decide.
        assertFalse(SenderMatcher.looksLikeObviousNoise(
            "Rs 900 spent on card XX12. Do not share card details with anyone."))
    }

    @Test fun whenInDoubtReturnsFalse() {
        assertFalse(SenderMatcher.looksLikeObviousNoise("Your statement is ready to view."))
    }
}
