package com.expendicure.companion

/**
 * Pure logic (no Android APIs) so it is trivially unit-testable.
 *
 * Two jobs, both LOCAL and both conservative:
 *   1. [matches]  — is this SMS from a sender the user configured? Indian bank
 *      sender IDs arrive in many decorated forms (`HDFCBK`, `AD-HDFCBK`,
 *      `VM-HDFCBK-S`, `JD-HDFCBK`). We match the configured token as a
 *      whole-segment of the actual sender, case-insensitively.
 *   2. [looksLikeObviousNoise] — a cheap pre-filter for the plainly-not-a-txn
 *      cases (OTP / promo). This ONLY saves a needless network call; it is NOT
 *      authoritative. The Phase-15 backend parser is the source of truth and
 *      re-checks everything.
 *
 * The companion never parses amounts, never categorises, never decides whether
 * a transaction is "real".
 */
object SenderMatcher {

    /** True when [actualSender] is (or contains as a header-segment) [configured]. */
    fun matches(actualSender: String?, configured: String?): Boolean {
        val a = actualSender?.trim()?.uppercase().orEmpty()
        val c = configured?.trim()?.uppercase().orEmpty()
        if (a.isEmpty() || c.isEmpty()) return false
        if (a == c) return true
        // split on the usual carrier decorations: "-", "_", ".", spaces
        val segments = a.split('-', '_', '.', ' ').filter { it.isNotBlank() }
        return segments.any { it == c }
    }

    private val OTP = Regex(
        "\\b(otp|one[ -]?time[ -]?password|verification code|security code|" +
            "do not share|passcode)\\b",
        RegexOption.IGNORE_CASE
    )
    private val COMPLETED_TXN = Regex(
        "\\b(debited|credited|spent|withdrawn|deposited|received|w/d)\\b",
        RegexOption.IGNORE_CASE
    )
    private val PROMO = Regex(
        "\\b(\\d+% ?off|flat \\d+%|discount|cashback offer|sale|coupon|" +
            "pre[ -]?approved|apply now|lowest price|limited (time|period)|hurry)\\b",
        RegexOption.IGNORE_CASE
    )
    private val TXN_HINT = Regex(
        "\\b(debited|credited|a/c|acct|account|upi|imps|neft|txn|avl bal)\\b",
        RegexOption.IGNORE_CASE
    )

    /**
     * A local, best-effort "this is obviously not a bank transaction" check.
     * Returning true means "skip the network call". Returning false means
     * "let the backend decide". When in doubt it returns false.
     */
    fun looksLikeObviousNoise(body: String?): Boolean {
        val t = body?.trim().orEmpty()
        if (t.isEmpty()) return true
        if (OTP.containsMatchIn(t) && !COMPLETED_TXN.containsMatchIn(t)) return true
        if (PROMO.containsMatchIn(t) && !TXN_HINT.containsMatchIn(t)) return true
        return false
    }
}
