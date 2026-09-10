# Expendicure Companion — bank SMS forwarder

**The Expendicure web app cannot read your phone's SMS inbox.** A browser has no
access to SMS. To turn bank transaction alerts into reviewable entries in your
Financial Twin, you install a small **companion app** on the phone that receives
the bank's SMS and forwards *only* the transaction text to your Expendicure
server.

Correct product claim:

> *Expendicure can securely connect to a phone companion that forwards
> configured bank transaction notifications for review.*

Not: "Expendicure reads all your SMS." It does not, and cannot.

- `android/` — a real, buildable Android/Kotlin app (Gradle project).
- This document — setup, LAN testing, production HTTPS, and the privacy model.

---

## Three different values — do not confuse them

| Value | What it is | Where it comes from | Example |
|---|---|---|---|
| **Your mobile number** | the SIM's phone number | your telecom provider | `+91 98765 43210` |
| **Bank SMS sender ID** | the short alphabetic header the bank sends *from* | printed in the bank's own SMS | `HDFCBK`, `ICICIB`, `SBIINB` |
| **Ingest token** | a per-connection secret that authorises this phone to POST to your account | shown **once** in Expendicure → Connections → *Add / Manage bank* | `q1w2e3...` (24-byte URL-safe) |

**User mobile number ≠ Bank SMS sender ID ≠ Ingest token.** The companion never
uses your mobile number as the sender ID, and never logs or displays the token.

---

## What the companion sends

For each SMS whose sender matches your configured bank sender ID, the companion
POSTs **exactly this and nothing else** — no contacts, no message list, no
unrelated personal SMS:

```
POST  <your-expendicure-host>/api/bank/sms-events
X-Ingest-Token: <ingest token from Connections>
Content-Type: application/json

{ "sender": "HDFCBK", "body": "<the raw SMS text>", "received_at": "2026-09-10T09:15:00Z" }
```

`received_at` is sent for forward-compatibility; the current server ignores
unknown keys and derives the transaction date from the SMS text itself.

The **server** does the sender check, the deterministic amount/merchant/date
extraction, dedup, and validation. The companion does **not** parse amounts,
categorise, call an LLM, run RAG, dedup, or create transactions.

### Responses the companion handles (none crash it)

| Status | Meaning | Companion behaviour |
|---|---|---|
| `201` | transaction detected — now in the web **review** queue | show "forwarded"; discard body |
| `200 {duplicate:true}` | backend already has this one | show "already processed"; discard body |
| `202 {ignored:"…"}` | not a transaction (OTP / promo / noise) **or** sender not configured | show "ignored"; discard body |
| `401` | ingest token bad or missing | show "token rejected — re-check"; discard body |
| other `4xx` | malformed request | show "rejected"; discard body |
| `5xx` | backend error | show "backend error"; discard body — **no retry** |
| timeout / no network / DNS | server unreachable | show "not forwarded"; discard body — **no retry, no queue** |

**Nothing enters your Financial Twin until you press Confirm / Edit / Ignore in
the web app.** Phase 15 is review-only; there is no auto-confirm.

---

## Build

Requirements: JDK 17 (the Android Studio JBR works), Android SDK with
**platform 34** and **build-tools 35.0.0**, internet on first build to fetch
AndroidX.

```bash
cd companion/android
cp local.properties.example local.properties   # then edit sdk.dir, OR let Android Studio create it
./gradlew assembleDebug            # -> app/build/outputs/apk/debug/app-debug.apk
./gradlew testDebugUnitTest        # 32 offline unit tests
```

`local.properties` is machine-specific (`sdk.dir=…`) and git-ignored. Use
forward slashes even on Windows: `sdk.dir=C:/Users/you/AppData/Local/Android/Sdk`.

Install the debug APK on a phone:

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

---

## Configure (in the app)

1. **Expendicure server URL**
   - Production: `https://finance.example.com` — **HTTPS is required**.
   - Dev on your LAN: `http://192.168.1.10:5000` is allowed **only** for
     private hosts (`localhost`, `127.0.0.1`, `10.x`, `192.168.x`,
     `172.16–31.x`, `*.local`). A plain-HTTP public host is rejected by the
     app. Do **not** hard-code `localhost` — from a physical phone `localhost`
     is the phone itself; use your PC's LAN IP.
2. **Bank name** — display only.
3. **Bank sender ID** — e.g. `HDFCBK`. This is the header on the bank's SMS,
   **not your phone number**. Carrier-decorated forms (`AD-HDFCBK`,
   `VM-HDFCBK-S`) are matched automatically.
4. **Ingest token** — paste once from Expendicure → Connections. Stored in
   `EncryptedSharedPreferences` (AES-256, key in the Android Keystore); shown
   back only as a masked placeholder.
5. **Grant SMS permission** — the app requests only `RECEIVE_SMS` (+ `INTERNET`).
6. **Test Connection** — sends a harmless sentinel (non-transaction) body and
   reports: connected / token rejected / sender not configured / unreachable.
   This uses the normal endpoint and needs **no** backend change.

---

## LAN testing walk-through (dev)

1. Run the Expendicure backend on your PC, bound to `0.0.0.0` (e.g. Flask on
   `:5000`), same Wi-Fi as the phone.
2. Find the PC's LAN IP (`ipconfig` / `ip addr`) — say `192.168.1.10`.
3. In Expendicure web → Connections, add your bank, copy the ingest token.
4. In the companion: URL `http://192.168.1.10:5000`, sender `HDFCBK`, paste the
   token, **Test Connection** → expect "Connected".
5. Send yourself a test SMS from a number spoofing header `HDFCBK` (or use an
   emulator's `sms send HDFCBK "Rs 100 debited from a/c XX1234 ..."`).
6. The transaction appears in the web **review** queue. Confirm / Edit / Ignore.

## Production

- Terminate TLS in front of Expendicure; give the companion the `https://` URL.
- Rotate the ingest token from Connections if a phone is lost — the old token
  stops working immediately (hashed at rest, per-connection).

---

## Privacy architecture

- **Only** messages from your configured, enabled bank sender ID are forwarded.
  Every other SMS is dropped in `SmsReceiver` and never leaves the device.
- **Only** `{sender, body, received_at}` is sent, for those messages only. No
  contacts, no inbox listing, no unrelated SMS.
- **No raw-SMS storage.** There is no database, history, archive, or retry
  queue in the companion. The body lives only in a local variable for the
  duration of one forward attempt, then goes out of scope. If the server is
  unreachable the message is discarded — privacy over delivery.
- **Secure token storage.** `EncryptedSharedPreferences` only — never plain
  `SharedPreferences`. `android:allowBackup="false"` plus backup /
  data-extraction exclude rules keep the token off cloud backup and
  device-to-device transfer.
- **Safe logging.** Logs contain only fixed status strings
  ("Bank SMS received from configured sender", "Event forwarded successfully",
  …). The token, raw SMS, OTP, account numbers and transaction references are
  **never** logged.
- **No financial logic on the phone.** No amount maths, no categorisation, no
  LLM, no RAG, no transaction creation, no dedup — the backend owns all of it.
- **Review-only.** Every detected transaction waits for your explicit
  Confirm / Edit / Ignore in the web app.

## Permissions

| Permission | Why |
|---|---|
| `RECEIVE_SMS` | detect incoming bank transaction alerts |
| `INTERNET` | POST the transaction text to your Expendicure server |
| `ACCESS_NETWORK_STATE` | avoid a pointless POST while offline |

No `READ_SMS`, no `READ_CONTACTS`, no storage permissions.
