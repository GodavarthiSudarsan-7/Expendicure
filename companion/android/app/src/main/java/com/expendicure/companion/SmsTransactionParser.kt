package com.expendicure.companion

import java.text.SimpleDateFormat
import java.util.Locale

/**
 * DETERMINISTIC on-device bank-SMS parser. Pure Kotlin — no Android APIs, no
 * network, no model — so it is fully unit-testable and runs in microseconds.
 *
 * Why it exists (privacy): when this parser succeeds the companion sends only
 * the STRUCTURED transaction (amount / direction / merchant / masked account /
 * reference / date) to the user's own Expendicure server. The raw SMS body then
 * never leaves the phone at all.
 *
 * What it is NOT:
 *  - It is not an LLM and never calls one. Amount and direction extraction is
 *    plain regex.
 *  - It is not authoritative. The backend re-validates everything, dedups, and
 *    creates a REVIEW-ONLY event. Nothing becomes a transaction without the
 *    user pressing Confirm.
 *  - It never computes balances, categories or affordability.
 */
object SmsTransactionParser {

    const val STATUS_CONFIDENT = "confident"
    const val STATUS_REVIEW = "review"
    const val STATUS_REJECTED = "rejected"

    const val DEBIT = "debit"
    const val CREDIT = "credit"

    /** Real bank alerts are short. Anything huge is not one. */
    private const val MAX_BODY_LEN = 1000

    data class ParsedTxn(
        val status: String,
        val reason: String = "",
        val direction: String? = null,
        /** Always a positive 2-decimal magnitude string, e.g. "1000.00". */
        val amount: String? = null,
        val merchant: String? = null,
        val maskedAccount: String? = null,
        val bankRef: String? = null,
        /** yyyy-MM-dd when the SMS states a date. */
        val occurredOn: String? = null,
        /** HH:mm:ss when the SMS states a time. */
        val occurredAt: String? = null,
        val templateId: String? = null,
    ) {
        val rejected: Boolean get() = status == STATUS_REJECTED

        /**
         * True when we extracted enough to send a structured event and leave
         * the raw text on the phone. Amount AND direction are the minimum the
         * backend needs to create a reviewable event.
         */
        val structuredReady: Boolean get() = !rejected && amount != null && direction != null
    }

    // ------------------------------------------------------------- reject filters
    private val OTP = Regex(
        "\\b(otp|one[\\s-]?time\\s?password|verification code|security code|" +
            "do not share|don'?t share|passcode|auth(entication)? code)\\b",
        RegexOption.IGNORE_CASE
    )
    private val PROMO = Regex(
        "\\b(\\d+%\\s*off|flat\\s*\\d+%|discount|cashback offer|mega sale|big sale|" +
            "coupon|promo code|pre[\\s-]?approved|apply now|congratulations|you\\s+won|" +
            "limited period|limited time|hurry|lowest price|best deal|festive offer|" +
            "upgrade your card|increase your limit|instant loan|personal loan offer)\\b",
        RegexOption.IGNORE_CASE
    )
    private val TXN_KEYWORD = Regex(
        "\\b(debited|credited|spent|withdrawn|deposited|received|paid|" +
            "transaction|txn|a/c|acct|account|upi|imps|neft|rtgs|ref no|avl bal|" +
            "available balance)\\b",
        RegexOption.IGNORE_CASE
    )
    private val COMPLETED_TXN = Regex(
        "\\b(debited|credited|spent|withdrawn|withdrawal|deposited|received|" +
            "refunded|transferred to|w/d|sent)\\b",
        RegexOption.IGNORE_CASE
    )

    // ------------------------------------------------------------------ direction
    private val DEBIT_RE = Regex(
        "\\b(debited|debit|spent|withdrawn|withdrawal|paid|payment of|purchase of|" +
            "purchased|sent|transferred to|transferred from|txn of|dr|deducted)\\b",
        RegexOption.IGNORE_CASE
    )

    /**
     * A balance statement, not a transaction: "Balance is Rs.X", "Bal: Rs.X".
     * Deliberately requires "is" or ":" straight after the word, so the trailing
     * "Avl Bal Rs.X" on a REAL debit/credit alert is not caught by this.
     */
    private val BALANCE_ONLY_RE = Regex(
        "\\b(?:available\\s+balance|avl\\.?\\s*balance|balance|bal)\\b\\s*(?:is\\b|:)",
        RegexOption.IGNORE_CASE
    )
    private val CREDIT_RE = Regex(
        "\\b(credited|credit|received|deposited|refunded|refund|added to|cr|" +
            "money added|cashback of)\\b",
        RegexOption.IGNORE_CASE
    )

    // --------------------------------------------------------------------- amount
    // The currency token may be followed by '.', ':' or '-' before the digits.
    // Union Bank writes "Rs:100.00"; others write "Rs.100.00" or "Rs 100.00".
    // `\brs\b` keeps this anchored to the word "Rs" (so "24 hrs" never matches).
    private val AMOUNT = Regex(
        "(?:\\binr\\b|\\brs\\b|₹)\\s*[.:\\-]?\\s*" +
            "([0-9][0-9,]*(?:\\.[0-9]{1,2})?)(?:\\s*(k|lakh|lac|crore|cr)\\b)?",
        RegexOption.IGNORE_CASE
    )
    private val SCALE = mapOf(
        "k" to 1_000L, "lakh" to 100_000L, "lac" to 100_000L,
        "cr" to 10_000_000L, "crore" to 10_000_000L
    )

    // -------------------------------------------------------------- masked account
    private val ACCOUNT = Regex(
        "\\b(?:a/?c|acct|account|card)\\s*(?:no\\.?|number|ending in|ending)?\\s*" +
            "[:#]?\\s*(?:x+|\\*+)?\\s*(\\d{3,6})\\b",
        RegexOption.IGNORE_CASE
    )

    // ----------------------------------------------------------------- reference
    private val REF = Regex(
        "\\b(?:upi(?:\\s*(?:ref(?:erence)?)?(?:\\s*(?:no|id))?)?|ref(?:erence)?" +
            "(?:\\s*(?:no|id))?|txn(?:\\s*(?:no|id))?|transaction\\s*(?:no|id)|" +
            "rrn|utr)\\s*[:.\\-#]?\\s*([A-Za-z0-9]{6,40})\\b",
        RegexOption.IGNORE_CASE
    )

    // ------------------------------------------------------------------ merchant
    private val MERCHANT = Regex(
        "\\b(?:at|to|towards|via vpa|vpa|@)\\s+" +
            "([A-Za-z0-9][A-Za-z0-9 &._@'\\-]{1,60}?)" +
            // also stop at an opening bracket — "credited to payee@bank (UPI Ref no ...)"
            "(?=\\s+(?:on|ref|upi|txn|avl|bal|a/?c|dated|not you|call|if not|info)\\b" +
            "|\\s*\\(|[.,;\\n]|\$)",
        RegexOption.IGNORE_CASE
    )
    private val MERCHANT_STRIP = Regex("\\b(on|ref|upi|txn|dated|avl bal|a/?c)\\b.*\$", RegexOption.IGNORE_CASE)
    private val MERCHANT_NOISE = Regex(
        "^(your|the|my|a/?c|acct|account|bank|self|upi|rs\\.?|inr|₹|[0-9][0-9,. ]*)\$",
        RegexOption.IGNORE_CASE
    )

    // ---------------------------------------------------------------------- date
    private val DATE_TOKEN = Regex(
        "\\b(\\d{1,2}[-/. ](?:\\d{1,2}|[A-Za-z]{3,9})[-/. ]\\d{2,4}|\\d{4}-\\d{2}-\\d{2})\\b"
    )
    private val DATE_FORMATS = arrayOf(
        "dd-MM-yyyy", "dd-MM-yy", "dd-MMM-yyyy", "dd-MMM-yy", "yyyy-MM-dd"
    )
    private val TIME_TOKEN = Regex("\\b(\\d{1,2}):(\\d{2})(?::(\\d{2}))?\\s*(am|pm)?\\b", RegexOption.IGNORE_CASE)

    // ----------------------------------------------------------------- templates
    private val TEMPLATES = listOf(
        // Union Bank first: its signature footer makes these unambiguous, and
        // the looser generic templates below would otherwise claim them.
        // Debit is checked before credit because a UPI debit alert reads
        // "... Debited ... and credited to <payee>".
        "union_debit_v1" to Regex(
            "\\bdebited\\b[\\s\\S]*\\bunion bank\\b|\\bunion bank\\b[\\s\\S]*\\bdebited\\b",
            RegexOption.IGNORE_CASE
        ),
        "union_credit_v1" to Regex(
            "\\bcredited\\b[\\s\\S]*\\bunion bank\\b|\\bunion bank\\b[\\s\\S]*\\bcredited\\b",
            RegexOption.IGNORE_CASE
        ),
        "hdfc_debit_v1" to Regex(
            "(?:rs\\.?|inr)\\s*[\\d,]+(?:\\.\\d{1,2})?\\s+debited\\s+from\\s+a/?c\\s*x*\\d{3,6}[\\s\\S]*?\\bto\\b",
            RegexOption.IGNORE_CASE
        ),
        "sbi_credit_v1" to Regex(
            "\\bcredited\\b[\\s\\S]*?(?:rs\\.?|inr)\\s*[\\d,]+(?:\\.\\d{1,2})?[\\s\\S]*?\\ba/?c\\b",
            RegexOption.IGNORE_CASE
        ),
        "icici_txn_v1" to Regex(
            "\\bacct?\\s*x*\\d{3,6}\\b[\\s\\S]*?(?:debited|credited)\\b[\\s\\S]*?(?:rs\\.?|inr)\\s*[\\d,]+",
            RegexOption.IGNORE_CASE
        ),
        "upi_generic_v1" to Regex(
            "\\bupi\\b[\\s\\S]*?(?:debited|credited|paid|received)[\\s\\S]*?(?:rs\\.?|inr|₹)\\s*[\\d,]+",
            RegexOption.IGNORE_CASE
        ),
    )

    // ---------------------------------------------------------------------- API

    /** Structure one bank SMS. Never throws. */
    fun parse(body: String?): ParsedTxn {
        val text = body?.trim().orEmpty()
        if (text.isEmpty()) return ParsedTxn(STATUS_REJECTED, "empty message")
        if (text.length > MAX_BODY_LEN) return ParsedTxn(STATUS_REJECTED, "message too long to be a bank alert")

        val completed = COMPLETED_TXN.containsMatchIn(text)
        if (OTP.containsMatchIn(text) && !completed) {
            return ParsedTxn(STATUS_REJECTED, "looks like an OTP / verification message")
        }
        if (PROMO.containsMatchIn(text) && !TXN_KEYWORD.containsMatchIn(text)) {
            return ParsedTxn(STATUS_REJECTED, "looks like a promotional message")
        }

        val direction = directionOf(text)
        val amount = amountOf(text)
        if (direction == null && amount == null) {
            return ParsedTxn(STATUS_REJECTED, "not a transaction message")
        }
        // A balance enquiry carries an amount but no completed debit/credit.
        // Without this it would become a bogus "money in or out?" review item.
        if (direction == null && !completed && BALANCE_ONLY_RE.containsMatchIn(text)) {
            return ParsedTxn(STATUS_REJECTED, "balance information only, not a transaction")
        }
        if (amount == null) return ParsedTxn(STATUS_REJECTED, "no amount found in the message")

        val occurredOn = dateOf(text)
        val merchant = merchantOf(text)
        val account = accountOf(text)
        val ref = refOf(text)
        val template = templateOf(text)
        val time = timeOf(text)

        if (direction == null) {
            return ParsedTxn(
                STATUS_REVIEW, "couldn't tell if this was money in or out",
                null, amount, merchant, account, ref, occurredOn, time, template
            )
        }

        val reasons = mutableListOf<String>()
        if (occurredOn == null) reasons.add("date not found")
        if (ref == null && !(merchant != null && account != null)) reasons.add("merchant / reference not clear")

        val status = if (reasons.isEmpty()) STATUS_CONFIDENT else STATUS_REVIEW
        return ParsedTxn(
            status, reasons.joinToString("; "),
            direction, amount, merchant, account, ref, occurredOn, time, template
        )
    }

    // ------------------------------------------------------------------ internals

    internal fun directionOf(text: String): String? {
        val d = DEBIT_RE.find(text)
        val c = CREDIT_RE.find(text)
        return when {
            d != null && c != null -> if (d.range.first <= c.range.first) DEBIT else CREDIT
            d != null -> DEBIT
            c != null -> CREDIT
            else -> null
        }
    }

    internal fun amountOf(text: String): String? {
        val m = AMOUNT.find(text) ?: return null
        val raw = m.groupValues[1].replace(",", "")
        val base = raw.toBigDecimalOrNull() ?: return null
        val scale = m.groupValues.getOrNull(2)?.lowercase().orEmpty()
        val value = if (SCALE.containsKey(scale)) base.multiply(SCALE[scale]!!.toBigDecimal()) else base
        if (value.signum() <= 0) return null
        return value.setScale(2, java.math.RoundingMode.HALF_UP).toPlainString()
    }

    internal fun merchantOf(text: String): String? {
        val m = MERCHANT.find(text) ?: return null
        var name = MERCHANT_STRIP.replace(m.groupValues[1], "").trim(' ', '.', '-', '_')
        name = name.split(Regex("\\s+")).filter { it.isNotBlank() }.joinToString(" ")
        if (name.length < 2 || MERCHANT_NOISE.matches(name)) return null
        return name.take(120)
    }

    internal fun accountOf(text: String): String? =
        ACCOUNT.find(text)?.groupValues?.get(1)?.takeLast(6)

    internal fun refOf(text: String): String? {
        for (m in REF.findAll(text)) {
            val ref = m.groupValues[1]
            if (ref.any { it.isDigit() } && ref.lowercase() !in setOf("no", "id", "number")) return ref
        }
        return null
    }

    internal fun templateOf(text: String): String? =
        TEMPLATES.firstOrNull { it.second.containsMatchIn(text) }?.first

    internal fun dateOf(text: String): String? {
        val out = SimpleDateFormat("yyyy-MM-dd", Locale.US)
        for (match in DATE_TOKEN.findAll(text)) {
            val cleaned = match.groupValues[1].trim().replace('.', '-').replace('/', '-').replace(' ', '-')
            for (fmt in DATE_FORMATS) {
                try {
                    val parser = SimpleDateFormat(fmt, Locale.US)
                    parser.isLenient = false
                    val d = parser.parse(cleaned) ?: continue
                    val year = out.format(d).substring(0, 4).toInt()
                    if (year in 2000..2100) return out.format(d)
                } catch (_: Exception) {
                    // try the next format
                }
            }
        }
        return null
    }

    internal fun timeOf(text: String): String? {
        val m = TIME_TOKEN.find(text) ?: return null
        var hour = m.groupValues[1].toIntOrNull() ?: return null
        val minute = m.groupValues[2].toIntOrNull() ?: return null
        val second = m.groupValues[3].toIntOrNull() ?: 0
        val meridiem = m.groupValues[4].lowercase()
        if (meridiem == "pm" && hour < 12) hour += 12
        if (meridiem == "am" && hour == 12) hour = 0
        if (hour !in 0..23 || minute !in 0..59 || second !in 0..59) return null
        return String.format(Locale.US, "%02d:%02d:%02d", hour, minute, second)
    }
}
