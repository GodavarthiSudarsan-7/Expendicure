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
 * Receives incoming SMS and forwards ONLY messages from the configured bank
 * sender to the user's own Expendicure server.
 *
 * Pipeline (each stage is recorded as a safe label so the user can see where a
 * message stopped, without any message content being stored):
 *
 *   SMS_RECEIVED
 *     -> reassemble multipart PDUs per originating address
 *     -> SenderMatcher: configured sender allowlist (everything else dropped)
 *     -> SenderMatcher: obvious OTP / promo pre-filter
 *     -> SmsTransactionParser: DETERMINISTIC on-device extraction
 *     -> structured event  ......................... raw text never leaves the phone
 *        (or, only if the user opted in, raw body ... "private local-network fallback")
 *     -> POST /api/bank/sms-events -> review queue -> user Confirm/Edit/Ignore
 *
 * Privacy guarantees enforced here:
 *  - Every non-matching SMS is dropped locally and never leaves the device.
 *  - The raw body lives only in local variables for one forward attempt.
 *    Nothing is written to disk: no queue, no history, no retry store.
 *  - No log line ever contains a body, sender address, OTP, account number,
 *    reference or token — only fixed stage labels and counters.
 *  - If the backend is unreachable the message is discarded (privacy over
 *    delivery).
 *
 * The companion makes NO financial decision: it does not categorise, dedupe or
 * create transactions, and it never calls a model. The backend re-validates and
 * every detected transaction still needs Confirm / Edit / Ignore in the web app.
 */
class SmsReceiver : BroadcastReceiver() {

    private companion object {
        const val FORWARD_TIMEOUT_MS = 15_000L
    }

    override fun onReceive(context: Context, intent: Intent) {
        // A BroadcastReceiver that throws is killed silently and the message is
        // lost with no trace. Everything below is defensive for that reason:
        // e.g. the Keystore-backed config is unavailable before the first
        // unlock after a reboot.
        try {
            handle(context, intent)
        } catch (t: Throwable) {
            SafeLog.failure("onReceive", t)
        }
    }

    private fun handle(context: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return

        val cfg = try {
            CompanionConfig.get(context.applicationContext)
        } catch (t: Throwable) {
            // Locked device / corrupted keystore. Nothing we can safely do.
            SafeLog.failure("config", t)
            return
        }

        cfg.smsSeen += 1
        if (!cfg.isConfigured) {
            cfg.note("Companion not configured — message ignored")
            return
        }

        // Reassemble multipart SMS: concatenate every PDU per originating address.
        val parts = Telephony.Sms.Intents.getMessagesFromIntent(intent)
        if (parts.isNullOrEmpty()) {
            cfg.note("No readable message in broadcast")
            return
        }
        val bySender = LinkedHashMap<String, StringBuilder>()
        for (m in parts) {
            val from = m.originatingAddress ?: continue
            bySender.getOrPut(from) { StringBuilder() }.append(m.messageBody ?: "")
        }
        if (bySender.isEmpty()) {
            cfg.note("No readable message in broadcast")
            return
        }

        var anyMatched = false
        for ((sender, sb) in bySender) {
            if (!SenderMatcher.matches(sender, cfg.senderId)) {
                SafeLog.status("Unconfigured sender ignored")
                continue
            }
            anyMatched = true
            cfg.senderMatched += 1
            SafeLog.status("Bank SMS received from configured sender")
            cfg.note("Bank SMS received from configured sender")

            val body = sb.toString()

            if (SenderMatcher.looksLikeObviousNoise(body)) {
                SafeLog.status("Local pre-filter skipped a non-transaction message")
                cfg.lastStatus = "Skipped a non-transaction message"
                cfg.note("Skipped: OTP / promotional message")
                continue
            }

            // --- DETERMINISTIC ON-DEVICE PARSING (no model, no network) ---
            val parsed = SmsTransactionParser.parse(body)

            when {
                parsed.structuredReady -> {
                    cfg.parsedOk += 1
                    cfg.note("Parsed on device — sending structured transaction")
                    SafeLog.status("Parsed on device; forwarding structured event")
                    forwardAsync(
                        cfg,
                        EventPayload.buildStructured(cfg.senderId, parsed, System.currentTimeMillis()),
                        structured = true,
                    )
                }

                parsed.rejected -> {
                    SafeLog.status("On-device parser rejected a non-transaction message")
                    cfg.lastStatus = "Not a transaction message"
                    cfg.note("Skipped: not a transaction message")
                }

                cfg.rawFallbackEnabled -> {
                    // Explicit user opt-in. The RAW text leaves the phone here,
                    // to the user's own local server only.
                    cfg.note("Could not parse on device — using local-network fallback")
                    SafeLog.status("On-device parse incomplete; using raw local-network fallback")
                    forwardAsync(
                        cfg,
                        EventPayload.buildRaw(cfg.senderId, body, System.currentTimeMillis()),
                        structured = false,
                    )
                }

                else -> {
                    cfg.lastStatus = "Could not read this message on the phone"
                    cfg.note("Could not parse on device — raw fallback is off, message dropped")
                    SafeLog.status("On-device parse incomplete; raw fallback disabled, dropped")
                }
            }
        }

        if (!anyMatched) {
            cfg.note("Message from an unconfigured sender — ignored")
        }
    }

    /**
     * Runs the single network call inside the receiver's goAsync() window.
     * The payload is a local — nothing is persisted for a retry.
     */
    private fun forwardAsync(cfg: CompanionConfig, payload: String, structured: Boolean) {
        val pending = goAsync()

        // The receiver forwards using the PERSISTED configuration only. An edit
        // typed into the app but never saved is invisible here — which is why
        // Test Connection now commits the form before testing.
        val backendUrl = cfg.backendUrl
        val token = cfg.ingestToken

        SafeLog.status("SMS forwarding started")
        if (backendUrl.isBlank()) {
            SafeLog.warn("Backend URL is not configured")
            cfg.note("No saved server address — event not forwarded")
            @Suppress("DEPRECATION") pending.finish()
            return
        }
        SafeLog.status("Backend URL configured")

        CoroutineScope(Dispatchers.IO).launch {
            try {
                val result = withTimeoutOrNull(FORWARD_TIMEOUT_MS) {
                    BackendClient.postSmsEvent(backendUrl, token, payload)
                } ?: ForwardResult.Timeout

                cfg.lastStatus = result.safeLog
                cfg.note(
                    (if (structured) "Structured event sent — " else "Local-network fallback sent — ")
                        + result.safeLog
                )
                if (result is ForwardResult.Created) cfg.forwarded += 1
                SafeLog.status(result.safeLog)
            } catch (t: Throwable) {
                SafeLog.failure("forwardAsync", t)
                cfg.lastStatus = "Could not reach Expendicure — event not forwarded"
                cfg.note("Send failed — event not forwarded")
            } finally {
                @Suppress("DEPRECATION")
                pending.finish()
            }
        }
    }
}
