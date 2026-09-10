package com.expendicure.companion

import android.util.Log

/**
 * The ONLY logger the companion uses. It exists to make it hard to accidentally
 * log something sensitive.
 *
 * It NEVER accepts an SMS body, a token, an OTP, an account number or a
 * transaction reference. Callers pass short, fixed status strings only:
 *   "Bank SMS received from configured sender"
 *   "Event forwarded successfully"
 *   "Event rejected by backend"
 *   "Unconfigured sender ignored"
 */
object SafeLog {
    private const val TAG = "ExpendicureCompanion"

    /** Fixed status messages only — no dynamic financial/PII content. */
    fun status(message: String) = Log.i(TAG, message)

    fun warn(message: String) = Log.w(TAG, message)

    /** For an exception we log its class name only, never its message (which
     *  could contain a URL, host or other detail). */
    fun failure(context: String, t: Throwable) =
        Log.w(TAG, "$context: ${t.javaClass.simpleName}")
}
