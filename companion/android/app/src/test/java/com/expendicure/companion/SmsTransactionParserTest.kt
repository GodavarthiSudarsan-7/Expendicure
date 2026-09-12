package com.expendicure.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Local, offline tests for the DETERMINISTIC on-device bank-SMS parser.
 * Pure JVM — no Android, no network, no model. Only synthetic samples are used;
 * nothing here comes from a real device.
 *
 * This mirrors the backend's `ingestion/sms_parser.py`; when a rule changes on
 * one side it should change on the other.
 */
class SmsTransactionParserTest {

    private val P = SmsTransactionParser

    // ------------------------------------------------------------- reject filters

    @Test fun rejectsEmptyOrBlank() {
        assertTrue(P.parse(null).rejected)
        assertTrue(P.parse("").rejected)
        assertTrue(P.parse("     ").rejected)
    }

    @Test fun rejectsSomethingFarTooLongToBeABankAlert() {
        assertTrue(P.parse("debited ".repeat(400)).rejected)
    }

    @Test fun rejectsAPlainOtpMessage() {
        val r = P.parse("123456 is your OTP for login. Do not share it with anyone. -HDFCBK")
        assertTrue(r.rejected)
    }

    @Test fun rejectsAPromotionalMessageWithNoTransactionWords() {
        assertTrue(P.parse("Get 50% OFF! Use code SAVE50. Limited time offer, hurry!").rejected)
        assertTrue(P.parse("You are pre-approved for a personal loan offer. Apply now.").rejected)
    }

    @Test fun aCompletedTransactionThatAlsoSaysDoNotShareIsNotRejectedAsOtp() {
        val r = P.parse("Rs 900.00 spent on card XX12 at CAFE. Do not share card details with anyone.")
        assertFalse(r.rejected)
        assertEquals(SmsTransactionParser.DEBIT, r.direction)
        assertEquals("900.00", r.amount)
    }

    @Test fun rejectsTextWithNeitherAmountNorDirection() {
        assertTrue(P.parse("Your account statement for August is now ready to view.").rejected)
    }

    @Test fun rejectsWhenADirectionIsPresentButNoAmount() {
        assertTrue(P.parse("Your salary has been credited. Check your balance.").rejected)
    }

    // ---------------------------------------------------------------- direction

    @Test fun readsDebitWords() {
        assertEquals(SmsTransactionParser.DEBIT, P.directionOf("Rs 10 debited from a/c"))
        assertEquals(SmsTransactionParser.DEBIT, P.directionOf("You spent Rs 10"))
        assertEquals(SmsTransactionParser.DEBIT, P.directionOf("Rs 10 withdrawn at ATM"))
        assertEquals(SmsTransactionParser.DEBIT, P.directionOf("payment of Rs 10 done"))
    }

    @Test fun readsCreditWords() {
        assertEquals(SmsTransactionParser.CREDIT, P.directionOf("Rs 10 credited to a/c"))
        assertEquals(SmsTransactionParser.CREDIT, P.directionOf("Rs 10 received from UPI"))
        assertEquals(SmsTransactionParser.CREDIT, P.directionOf("Rs 10 refunded to your card"))
    }

    @Test fun whenBothAppearTheEarlierWordWins() {
        assertEquals(SmsTransactionParser.DEBIT,
            P.directionOf("Rs 10 debited; earlier credited amount reversed"))
        assertEquals(SmsTransactionParser.CREDIT,
            P.directionOf("Rs 10 credited after the debited txn failed"))
    }

    @Test fun noDirectionWordReturnsNull() {
        assertNull(P.directionOf("Rs 2,000.00 transaction on a/c XX7788"))
    }

    // ------------------------------------------------------------------- amount

    @Test fun parsesPlainAmounts() {
        assertEquals("5000.00", P.amountOf("Rs.5000.00 debited"))
        assertEquals("1200.50", P.amountOf("INR 1,200.50 spent"))
        assertEquals("100.00", P.amountOf("₹100 paid"))
    }

    @Test fun appliesShorthandScales() {
        assertEquals("2000.00", P.amountOf("Rs 2k credited"))
        assertEquals("150000.00", P.amountOf("Rs 1.5 lakh credited"))
        assertEquals("10000000.00", P.amountOf("INR 1 crore transferred"))
    }

    @Test fun rejectsZeroOrMissingAmount() {
        assertNull(P.amountOf("Rs 0 debited"))
        assertNull(P.amountOf("debited from your account"))
    }

    // ----------------------------------------------------------------- merchant

    @Test fun extractsMerchantAfterAtOrTo() {
        assertEquals("AMAZON", P.merchantOf("Rs 10 debited to AMAZON. UPI Ref 12345678"))
        assertEquals("Blue Tokai Coffee", P.merchantOf("Rs 10 spent at Blue Tokai Coffee on 10-09-2026"))
    }

    @Test fun dropsNoiseWordsAsMerchant() {
        assertNull(P.merchantOf("Rs 10 debited to your a/c on 10-09-2026"))
    }

    // ------------------------------------------------------------ masked account

    @Test fun extractsLastDigitsOfAMaskedAccountOrCard() {
        assertEquals("4821", P.accountOf("debited from a/c XX4821 today"))
        assertEquals("1234", P.accountOf("spent on card ending 1234"))
        assertEquals("998812", P.accountOf("A/c no XXXXXX998812 credited"))
    }

    // ----------------------------------------------------------------- reference

    @Test fun extractsABankReferenceThatContainsDigits() {
        assertEquals("402312345678", P.refOf("UPI Ref 402312345678"))
        assertEquals("N123456789", P.refOf("NEFT UTR: N123456789 processed"))
    }

    @Test fun ignoresAReferenceTokenWithNoDigits() {
        assertNull(P.refOf("Ref no ABCDEF for your records"))
    }

    // ---------------------------------------------------------------------- date

    @Test fun parsesTheCommonIndianDateForms() {
        assertEquals("2026-09-10", P.dateOf("on 10-09-2026 to"))
        assertEquals("2026-09-05", P.dateOf("on 05-Sep-2026 by NEFT"))
        assertEquals("2026-09-10", P.dateOf("dated 2026-09-10."))
        assertEquals("2026-09-10", P.dateOf("on 10/09/26 at ATM"))
    }

    @Test fun returnsNullWhenNoDateToken() {
        assertNull(P.dateOf("Rs 10 debited from a/c XX4821"))
    }

    // ---------------------------------------------------------------------- time

    @Test fun parses24HourAnd12HourTimes() {
        assertEquals("14:30:00", P.timeOf("at 14:30:00 on"))
        assertEquals("14:05:00", P.timeOf("at 2:05 PM"))
        assertEquals("00:15:00", P.timeOf("at 12:15 am"))
    }

    // ------------------------------------------------------- end-to-end / status

    @Test fun aCompleteDebitAlertIsConfidentAndStructuredReady() {
        val r = P.parse(
            "Rs.5000.00 debited from a/c XX4821 on 10-09-2026 to AMAZON. " +
                "UPI Ref 402312345678. Not you? Call 18002586161"
        )
        assertEquals(SmsTransactionParser.STATUS_CONFIDENT, r.status)
        assertEquals(SmsTransactionParser.DEBIT, r.direction)
        assertEquals("5000.00", r.amount)
        assertEquals("AMAZON", r.merchant)
        assertEquals("4821", r.maskedAccount)
        assertEquals("402312345678", r.bankRef)
        assertEquals("2026-09-10", r.occurredOn)
        assertEquals("hdfc_debit_v1", r.templateId)
        assertTrue(r.structuredReady)
    }

    @Test fun aCreditWithRefAndDateIsConfident() {
        val r = P.parse(
            "Dear Customer, Rs.15000.00 credited to your A/c XXXXX1234 on 05-Sep-2026 " +
                "by NEFT. Avl Bal Rs.42350.10. Ref no 99887766."
        )
        assertEquals(SmsTransactionParser.STATUS_CONFIDENT, r.status)
        assertEquals(SmsTransactionParser.CREDIT, r.direction)
        assertEquals("15000.00", r.amount)
        assertEquals("99887766", r.bankRef)
        assertTrue(r.structuredReady)
    }

    @Test fun missingDateDropsItToReviewButStillStructuredReady() {
        val r = P.parse("Rs.5000.00 debited from a/c XX4821 to AMAZON. UPI Ref 402312345678")
        assertEquals(SmsTransactionParser.STATUS_REVIEW, r.status)
        assertTrue(r.reason.contains("date"))
        assertTrue(r.structuredReady)
    }

    @Test fun missingRefAndWeakIdentityDropsItToReview() {
        val r = P.parse("Rs 450.00 debited on 10-09-2026.")
        assertEquals(SmsTransactionParser.STATUS_REVIEW, r.status)
        assertTrue(r.structuredReady)
    }

    @Test fun amountButNoDirectionIsReviewAndNotStructuredReady() {
        val r = P.parse("Rs 2,000.00 transaction on a/c XX7788 on 12/09/2026.")
        assertEquals(SmsTransactionParser.STATUS_REVIEW, r.status)
        assertNull(r.direction)
        assertFalse(r.structuredReady)
    }

    @Test fun parseNeverThrowsOnGarbage() {
        for (junk in listOf(" ", "Rs credited a/c", "debited " + "x".repeat(50), "₹₹₹")) {
            P.parse(junk)   // must not throw
        }
    }
}
