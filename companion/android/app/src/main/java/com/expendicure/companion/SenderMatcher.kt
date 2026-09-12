package com.expendicure.companion

import java.util.Locale

/**
 * Pure logic (no Android APIs) so it is trivially unit-testable.
 *
 * Two jobs, both LOCAL and both conservative:
 *
 *   1. [matches] — is this SMS from the sender the user configured? The
 *      configured sender is an ALLOWLIST of one. Indian carriers decorate the
 *      DLT header in several ways (`HDFCBK`, `AD-HDFCBK`, `VM-HDFCBK-S`,
 *      `JD-HDFCBK`, `BP.HDFCBK`), and Android reports it in whatever case the
 *      operator used. We therefore normalise case and carrier decoration, then
 *      require the configured token to equal a WHOLE SEGMENT of the incoming
 *      header. We never do substring matching, so `HDFCBKX`, `MYHDFCBK` and
 *      arbitrary phone numbers are rejected.
 *
 *   2. [looksLikeObviousNoise] — a cheap pre-filter for plainly-not-a-transaction
 *      messages (OTP / promo). It only saves a needless network round-trip; the
 *      on-device parser and then the backend both re-check.
 *
 * The companion never decides whether a transaction is "real" and never
 * categorises or computes anything financial.
 */
object SenderMatcher {

    /** Carrier decoration separators seen on Indian DLT headers. */
    private val SEPARATORS = charArrayOf('-', '_', '.', ' ', '/')

    /** Uppercase, trim, drop characters that are never part of a DLT header. */
    private fun normalise(raw: String?): String =
        raw?.trim()?.uppercase(Locale.US).orEmpty()

    /** Split a header into its meaningful segments, stripping stray punctuation. */
    private fun segments(header: String): List<String> =
        header.split(*SEPARATORS)
            .map { it.trim().trim('+', '*', '#', ':') }
            .filter { it.isNotBlank() }

    /**
     * The part of a configured value that identifies the bank. If the user
     * pasted a decorated header (`AD-HDFCBK`), use its longest alphabetic
     * segment; otherwise use the value as-is.
     */
    private fun configuredToken(configured: String): String {
        val segs = segments(configured)
        if (segs.size <= 1) return configured
        // Telecom prefixes/suffixes are 1-2 chars; the bank token is the longest.
        return segs.maxByOrNull { it.length } ?: configured
    }

    /** True when [actualSender] carries [configured] as a whole header segment. */
    fun matches(actualSender: String?, configured: String?): Boolean {
        val a = normalise(actualSender)
        val c = normalise(configured)
        if (a.isEmpty() || c.isEmpty()) return false

        val token = configuredToken(c)
        if (token.isEmpty()) return false
        // A numeric-only "sender" is a phone number, never a bank DLT header.
        if (token.all { it.isDigit() }) return false

        if (a == c || a == token) return true
        return segments(a).any { it == token }
    }

    private val OTP = Regex(
        "\\b(otp|one[ -]?time[ -]?password|verification code|security code|" +
            "do not share|passcode)\\b",
        RegexOption.IGNORE_CASE
    )
    private val COMPLETED_TXN = Regex(
        "\\b(debited|credited|spent|withdrawn|deposited|received|sent|w/d)\\b",
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
     * true  -> skip the network call entirely.
     * false -> let the on-device parser (then the backend) decide.
     * When in doubt it returns false.
     */
    fun looksLikeObviousNoise(body: String?): Boolean {
        val t = body?.trim().orEmpty()
        if (t.isEmpty()) return true
        if (OTP.containsMatchIn(t) && !COMPLETED_TXN.containsMatchIn(t)) return true
        if (PROMO.containsMatchIn(t) && !TXN_HINT.containsMatchIn(t)) return true
        return false
    }
}
