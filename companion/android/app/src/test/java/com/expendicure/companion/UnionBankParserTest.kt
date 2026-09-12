package com.expendicure.companion

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Union Bank of India formats.
 *
 * Live logcat showed "On-device parser rejected a non-transaction message" for
 * a genuine Union Bank transaction alert. Root cause: Union Bank writes the
 * amount as `Rs:100.00` (COLON), and the amount regex only allowed `Rs.` /
 * `Rs ` / `INR `, so no amount was found and parse() bailed out with
 * "no amount found in the message".
 *
 * Every sample below is SANITIZED — the account digits, references, amounts,
 * dates and counterparties are invented. No real customer data is in this file.
 */
class UnionBankParserTest {

    // Union Bank UPI debit: amount written as "Rs:", payee after "credited to".
    private val UB_UPI_DEBIT =
        "A/c XX4821 Debited for Rs:100.00 on 12-09-2026 10:30:15 and credited to " +
            "someone@okbank (UPI Ref no 123456789012)-Union Bank of India"

    // Union Bank IMPS credit.
    private val UB_IMPS_CREDIT =
        "Dear Customer, Your A/c XX4821 is Credited for Rs.500.00 on 12-09-2026 by " +
            "A/c linked to mobile XXXXXXXX90 (IMPS Ref no 123456789012) -Union Bank of India"

    // Union Bank account-to-account transfer out.
    private val UB_TRANSFER_DEBIT =
        "Rs.500.00 transferred from your A/c XX4821 to A/c XXXXX5678 on 12-09-2026. " +
            "Ref 123456789012. If not you, call 18002222244 -Union Bank of India"

    // Union Bank credit with the colon amount form.
    private val UB_COLON_CREDIT =
        "A/c XX4821 Credited for Rs:250.50 on 12-09-2026 by UPI Ref no 123456789012 " +
            "-Union Bank of India"

    // ------------------------------------------------------------- the regression

    @Test fun theColonAmountFormIsParsed() {
        // THE BUG: "Rs:100.00" used to yield no amount at all.
        assertEquals("100.00", SmsTransactionParser.amountOf(UB_UPI_DEBIT))
        assertEquals("250.50", SmsTransactionParser.amountOf(UB_COLON_CREDIT))
    }

    @Test fun unionBankUpiDebitIsFullyStructured() {
        val p = SmsTransactionParser.parse(UB_UPI_DEBIT)
        assertFalse(p.rejected)
        assertEquals(SmsTransactionParser.STATUS_CONFIDENT, p.status)
        assertEquals(SmsTransactionParser.DEBIT, p.direction)
        assertEquals("100.00", p.amount)
        assertEquals("4821", p.maskedAccount)
        assertEquals("123456789012", p.bankRef)
        assertEquals("2026-09-12", p.occurredOn)
        assertEquals("10:30:15", p.occurredAt)
        assertEquals("someone@okbank", p.merchant)
        assertEquals("union_debit_v1", p.templateId)
        assertTrue(p.structuredReady)
    }

    @Test fun unionBankImpsCreditIsFullyStructured() {
        val p = SmsTransactionParser.parse(UB_IMPS_CREDIT)
        assertEquals(SmsTransactionParser.STATUS_CONFIDENT, p.status)
        assertEquals(SmsTransactionParser.CREDIT, p.direction)
        assertEquals("500.00", p.amount)
        assertEquals("4821", p.maskedAccount)
        assertEquals("123456789012", p.bankRef)
        assertEquals("2026-09-12", p.occurredOn)
        assertEquals("union_credit_v1", p.templateId)
        assertTrue(p.structuredReady)
    }

    @Test fun unionBankTransferOutIsADebit() {
        // "transferred from your A/c" previously produced no direction at all.
        val p = SmsTransactionParser.parse(UB_TRANSFER_DEBIT)
        assertEquals(SmsTransactionParser.DEBIT, p.direction)
        assertEquals("500.00", p.amount)
        assertEquals("4821", p.maskedAccount)
        assertEquals("123456789012", p.bankRef)
        assertTrue(p.structuredReady)
    }

    @Test fun unionBankColonCreditIsACredit() {
        val p = SmsTransactionParser.parse(UB_COLON_CREDIT)
        assertEquals(SmsTransactionParser.CREDIT, p.direction)
        assertEquals("250.50", p.amount)
        assertEquals("union_credit_v1", p.templateId)
        assertTrue(p.structuredReady)
    }

    @Test fun aUpiDebitPrefersDebitEvenThoughItAlsoSaysCreditedTo() {
        // "... Debited ... and credited to <payee>" — the earlier verb wins.
        assertEquals(SmsTransactionParser.DEBIT, SmsTransactionParser.directionOf(UB_UPI_DEBIT))
        assertEquals("union_debit_v1", SmsTransactionParser.templateOf(UB_UPI_DEBIT))
    }

    // --------------------------------------------------- still strict: rejections

    @Test fun unionBankBalanceEnquiryIsRejected() {
        val p = SmsTransactionParser.parse(
            "Your A/c XX4821 Balance is Rs.10000.00 as on 12-09-2026 -Union Bank of India"
        )
        assertTrue(p.rejected)
        assertTrue(p.reason.contains("balance", ignoreCase = true))
    }

    @Test fun unionBankBalanceWithColonIsRejected() {
        val p = SmsTransactionParser.parse(
            "A/c XX4821 Bal: Rs:10000.00 as on 12-09-2026 -Union Bank of India"
        )
        assertTrue(p.rejected)
    }

    @Test fun unionBankOtpIsRejected() {
        val p = SmsTransactionParser.parse(
            "123456 is the OTP for your transaction of Rs.500.00. Do not share " +
                "-Union Bank of India"
        )
        assertTrue(p.rejected)
        assertTrue(p.reason.contains("OTP", ignoreCase = true))
    }

    @Test fun unionBankPromotionIsRejected() {
        val p = SmsTransactionParser.parse(
            "Get flat 20% off on your next purchase. Apply now for a pre-approved " +
                "personal loan offer -Union Bank of India"
        )
        assertTrue(p.rejected)
    }

    @Test fun unionBankServiceNoticeIsRejected() {
        val p = SmsTransactionParser.parse(
            "Dear Customer, net banking will be unavailable on 12-09-2026 from " +
                "01:00 to 04:00 for maintenance -Union Bank of India"
        )
        assertTrue(p.rejected)
    }

    @Test fun aTrailingAvailableBalanceOnARealDebitIsNotTreatedAsBalanceOnly() {
        // The balance rule must not swallow genuine alerts that quote Avl Bal.
        val p = SmsTransactionParser.parse(
            "A/c XX4821 Debited for Rs:100.00 on 12-09-2026. Avl Bal Rs.9900.00. " +
                "UPI Ref no 123456789012 -Union Bank of India"
        )
        assertFalse(p.rejected)
        assertEquals(SmsTransactionParser.DEBIT, p.direction)
        assertEquals("100.00", p.amount)   // the transacted amount, not the balance
    }

    @Test fun theWordHrsIsNeverReadAsRupees() {
        // `\brs\b` guard: "24 hrs" must not produce an amount.
        assertNull(SmsTransactionParser.amountOf("Service resumes in 24 hrs 30 minutes"))
    }

    // ------------------------------------- privacy: structured payload, no raw body

    @Test fun unionBankDebitProducesAStructuredPayloadWithoutTheRawSms() {
        val parsed = SmsTransactionParser.parse(UB_UPI_DEBIT)
        assertTrue(parsed.structuredReady)

        val json = JSONObject(EventPayload.buildStructured("UNIONB", parsed, 0L))

        // the raw SMS is NOT in the payload, under any key
        assertFalse(json.has("body"))
        assertEquals(setOf("sender", "received_at", "transaction"),
            json.keys().asSequence().toSet())
        assertFalse(json.toString().contains("Union Bank of India"))
        assertFalse(json.toString().contains("Debited for"))
        assertFalse(json.toString().contains("18002222244"))

        val txn = json.getJSONObject("transaction")
        assertEquals("100.00", txn.getString("amount"))
        assertEquals("debit", txn.getString("direction"))
        assertEquals("4821", txn.getString("masked_account"))
        assertEquals("123456789012", txn.getString("bank_ref"))
        assertEquals("2026-09-12", txn.getString("occurred_on"))
        assertEquals("10:30:15", txn.getString("occurred_at"))
        assertEquals("union_debit_v1", txn.getString("template_id"))
        assertEquals("confident", txn.getString("parse_status"))
    }

    @Test fun unionBankCreditProducesAStructuredPayloadWithoutTheRawSms() {
        val parsed = SmsTransactionParser.parse(UB_IMPS_CREDIT)
        val json = JSONObject(EventPayload.buildStructured("UNIONB", parsed, 0L))
        assertFalse(json.has("body"))
        assertFalse(json.toString().contains("Dear Customer"))
        assertEquals("credit", json.getJSONObject("transaction").getString("direction"))
        assertEquals("500.00", json.getJSONObject("transaction").getString("amount"))
    }

    @Test fun aRejectedUnionBankMessageIsNeverStructuredReady() {
        // nothing is eligible to be sent for OTP / promo / balance messages
        listOf(
            "123456 is the OTP for your transaction. Do not share -Union Bank of India",
            "Your A/c XX4821 Balance is Rs.10000.00 -Union Bank of India",
            "Get flat 20% off. Hurry -Union Bank of India",
        ).forEach {
            assertFalse(SmsTransactionParser.parse(it).structuredReady)
        }
    }
}
