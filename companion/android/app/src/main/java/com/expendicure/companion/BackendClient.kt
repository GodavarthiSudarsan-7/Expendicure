package com.expendicure.companion

import org.json.JSONObject
import java.io.BufferedReader
import java.net.HttpURLConnection
import java.net.URL
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.net.ConnectException
import java.net.SocketException

/**
 * Safe HTTP client for forwarding structured bank-SMS events
 * to the user's own Expendicure backend.
 *
 * PRIVACY:
 * - Never logs the backend URL.
 * - Never logs the ingest token.
 * - Never logs the request payload.
 * - Never logs SMS body, merchant, account number or bank reference.
 */
sealed class ForwardResult(val safeLog: String) {

    object Created :
        ForwardResult("Event forwarded successfully")

    object Duplicate :
        ForwardResult("Event already processed by backend")

    class Ignored(val reason: String) :
        ForwardResult("Event ignored by backend")

    object Unauthorized :
        ForwardResult("Ingest token was rejected — re-check the token")

    class Rejected(val code: Int) :
        ForwardResult("Event rejected by backend")

    class ServerError(val code: Int) :
        ForwardResult("Backend error while forwarding")

    object Unreachable :
        ForwardResult("Could not reach Expendicure — event not forwarded")

    /**
     * The TCP connect or the response read timed out: packets went out but
     * nothing answered. Almost always a wrong / stale server address, or the
     * phone not being on the same network as the server. Kept separate from
     * [Unreachable] so the UI can say something actionable.
     */
    object Timeout :
        ForwardResult("Backend did not respond — check the saved server address")
}

object BackendClient {

    private const val CONNECT_TIMEOUT_MS = 8_000
    private const val READ_TIMEOUT_MS = 12_000

    /**
     * Convert an HTTP response into a safe application result.
     *
     * No response body is logged.
     */
    fun classify(
        status: Int,
        jsonBody: String?
    ): ForwardResult {

        val json = runCatching {
            if (jsonBody.isNullOrBlank()) {
                null
            } else {
                JSONObject(jsonBody)
            }
        }.getOrNull()

        return when {
            status == 201 -> {
                ForwardResult.Created
            }

            status == 200 && json?.optBoolean("duplicate") == true -> {
                ForwardResult.Duplicate
            }

            status == 200 -> {
                ForwardResult.Duplicate
            }

            status == 202 -> {
                ForwardResult.Ignored(
                    json?.optString("ignored")
                        .orEmpty()
                        .ifBlank { "ignored" }
                )
            }

            status == 401 -> {
                ForwardResult.Unauthorized
            }

            status in 400..499 -> {
                ForwardResult.Rejected(status)
            }

            status in 500..599 -> {
                ForwardResult.ServerError(status)
            }

            else -> {
                ForwardResult.Rejected(status)
            }
        }
    }

    /**
     * POST a bank-SMS event to:
     *
     *     /api/bank/sms-events
     *
     * The caller decides whether the payload is structured or raw.
     * In normal production operation the companion sends the structured
     * on-device parsed transaction.
     */
    fun postSmsEvent(
        backendUrl: String,
        ingestToken: String,
        jsonPayload: String
    ): ForwardResult {

        var conn: HttpURLConnection? = null

        try {
            /*
             * Defensive validation.
             *
             * We don't log the URL if validation fails.
             */
            if (backendUrl.isBlank()) {
                SafeLog.warn("Backend URL is not configured")
                return ForwardResult.Unreachable
            }

            if (ingestToken.isBlank()) {
                SafeLog.warn("Ingest token is not configured")
                return ForwardResult.Unauthorized
            }

            if (jsonPayload.isBlank()) {
                SafeLog.warn("Empty event payload")
                return ForwardResult.Rejected(400)
            }

            /*
             * Build URL from the configured backend address.
             *
             * Nothing is hardcoded to localhost.
             */
            val baseUrl = backendUrl.trimEnd('/')

            val url = URL("$baseUrl/api/bank/sms-events")

            SafeLog.status("Forwarding event to Expendicure backend")

            conn = (url.openConnection() as HttpURLConnection).apply {

                requestMethod = "POST"

                connectTimeout = CONNECT_TIMEOUT_MS
                readTimeout = READ_TIMEOUT_MS

                doOutput = true
                doInput = true

                useCaches = false

                setRequestProperty(
                    "Content-Type",
                    "application/json; charset=UTF-8"
                )

                setRequestProperty(
                    "Accept",
                    "application/json"
                )

                setRequestProperty(
                    "X-Ingest-Token",
                    ingestToken
                )

                setRequestProperty(
                    "User-Agent",
                    "ExpendicureCompanion/1.0"
                )
            }

            /*
             * Send request body.
             *
             * IMPORTANT:
             * jsonPayload is never logged.
             */
            SafeLog.status("Sending event to Expendicure backend")

            conn.outputStream.use { output ->
                output.write(
                    jsonPayload.toByteArray(Charsets.UTF_8)
                )
                output.flush()
            }

            SafeLog.status("Event request sent; waiting for backend response")

            /*
             * responseCode may block until the backend responds.
             */
            val status = conn.responseCode

            SafeLog.status("Backend responded to event request")

            /*
             * Read the response body.
             *
             * Response body is used only for classification and is
             * never logged.
             */
            val stream =
                if (status in 200..299) {
                    conn.inputStream
                } else {
                    conn.errorStream
                }

            val body = stream
                ?.bufferedReader()
                ?.use(BufferedReader::readText)

            return classify(status, body)

        } catch (e: SocketTimeoutException) {

            /*
             * Do NOT log e.message.
             * It could contain networking information.
             */
            SafeLog.warn("Backend request timed out")
            return ForwardResult.Timeout

        } catch (e: UnknownHostException) {

            SafeLog.warn("Backend host could not be resolved")
            return ForwardResult.Unreachable

        } catch (e: ConnectException) {

            SafeLog.warn("Could not connect to Expendicure backend")
            return ForwardResult.Unreachable

        } catch (e: SocketException) {

            SafeLog.warn("Backend connection failed")
            return ForwardResult.Unreachable

        } catch (e: SecurityException) {

            SafeLog.warn("Android blocked the backend connection")
            return ForwardResult.Unreachable

        } catch (e: Throwable) {

            /*
             * Final defensive catch.
             *
             * Never log the exception message.
             */
            SafeLog.failure("forward", e)
            return ForwardResult.Unreachable

        } finally {

            conn?.disconnect()
        }
    }
}