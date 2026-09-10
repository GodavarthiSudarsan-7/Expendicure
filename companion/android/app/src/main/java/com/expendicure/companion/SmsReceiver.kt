package com.expendicure.companion

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Receives incoming SMS and forwards ONLY those from the configured bank
 * sender to the Phase-15 endpoint `POST /api/bank/sms-events`.
 *
 * Privacy guarantees enforced here:
 *  - Every other SMS is dropped locally and never leaves the device.
 *  - The raw body is held only in local variables for the duration of one
 *    forward attempt, then goes out of scope. Nothing is written to disk, no
 *    queue, no history, no log line ever contains the body / token / OTP /
 *    account number / reference.
 *  - If the backend is unavailable the message is discarded (privacy over
 *    delivery guarantees). Nothing is persisted for a later retry.
 *
 * The companion makes NO financial decision: it does not parse amounts,
 * categorise, dedupe, or create transactions. The backend does all of that and
 * every detected transaction still needs the user's Confirm / Edit / Ignore in
 * the web app.
 */
class SmsReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return

        val cfg = CompanionConfig.get(context.applicationContext)
        if (!cfg.isConfigured) return

        // Reassemble multipart SMS by sender.
        val parts = Telephony.Sms.Intents.getMessagesFromIntent(intent) ?: return
        val bySender = LinkedHashMap<String, StringBuilder>()
        for (m in parts) {
            val from = m.originatingAddress ?: continue
            bySender.getOrPut(from) { StringBuilder() }.append(m.messageBody ?: "")
        }

        for ((sender, sb) in bySender) {
            if (!SenderMatcher.matches(sender, cfg.senderId)) {
                SafeLog.status("Unconfigured sender ignored")
                continue
            }
            val body = sb.toString()
            SafeLog.status("Bank SMS received from configured sender")

            if (SenderMatcher.looksLikeObviousNoise(body)) {
                // Save a pointless round-trip. The backend would reject it anyway.
                SafeLog.status("Local pre-filter skipped a non-transaction message")
                cfg.lastStatus = "Skipped a non-transaction message"
                cfg.lastSyncAtMillis = System.currentTimeMillis()
                continue
            }

            forwardAsync(cfg, cfg.senderId, body)
        }
    }

    /**
     * Runs the single network call inside the receiver's goAsync() window.
     * `body` is a local — it is never persisted.
     */
    private fun forwardAsync(cfg: CompanionConfig, sender: String, body: String) {
        val pending = goAsync()
        val payload = EventPayload.build(sender, body, System.currentTimeMillis())
        val backendUrl = cfg.backendUrl
        val token = cfg.ingestToken

        CoroutineScope(Dispatchers.IO).launch {
            val result = withTimeoutOrNull(15_000) {
                BackendClient.postSmsEvent(backendUrl, token, payload)
            } ?: ForwardResult.Unreachable

            cfg.lastStatus = result.safeLog
            cfg.lastSyncAtMillis = System.currentTimeMillis()
            SafeLog.status(result.safeLog)

            @Suppress("DEPRECATION")
            pending.finish()
        }
    }
}
