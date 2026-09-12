package com.expendicure.companion

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.text.format.DateUtils
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.expendicure.companion.databinding.ActivityMainBinding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import androidx.lifecycle.lifecycleScope

/**
 * The whole companion UI: a status card + a configuration form + a
 * "Test Connection" button. No SMS history, no transaction amounts, no logs
 * shown. The ingest token field shows a masked placeholder once a token is
 * stored; the real token is never rendered back.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var b: ActivityMainBinding
    private lateinit var cfg: CompanionConfig
    private var tokenTouched = false

    private val requestSms = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { render() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        b = ActivityMainBinding.inflate(layoutInflater)
        setContentView(b.root)
        cfg = CompanionConfig.get(applicationContext)

        b.tokenInput.setOnFocusChangeListener { _, hasFocus ->
            if (hasFocus && !tokenTouched) { b.tokenInput.setText(""); tokenTouched = true }
        }
        b.grantPermissionButton.setOnClickListener {
            requestSms.launch(Manifest.permission.RECEIVE_SMS)
        }
        b.testButton.setOnClickListener { onTest() }
        b.saveButton.setOnClickListener { onSave() }
        b.rawFallbackSwitch.setOnCheckedChangeListener { _, checked ->
            cfg.rawFallbackEnabled = checked
            render()
        }
        b.resetDiagButton.setOnClickListener { cfg.resetDiagnostics(); render() }

        loadForm()
        render()
    }

    override fun onResume() { super.onResume(); render() }

    private fun hasSmsPermission() =
        ContextCompat.checkSelfPermission(this, Manifest.permission.RECEIVE_SMS) ==
            PackageManager.PERMISSION_GRANTED

    private fun loadForm() {
        b.urlInput.setText(cfg.backendUrl)
        b.bankNameInput.setText(cfg.bankName)
        b.senderInput.setText(cfg.senderId)
        b.tokenInput.setText(if (cfg.ingestToken.isEmpty()) "" else getString(R.string.token_stored_placeholder))
        tokenTouched = cfg.ingestToken.isEmpty()
    }

    /** Read the form, validating URL + sender. Returns null on error (and shows it). */
    private fun readForm(): FormValues? {
        val url = b.urlInput.text?.toString()?.trim().orEmpty()
        val sender = b.senderInput.text?.toString()?.trim().orEmpty()
        val bank = b.bankNameInput.text?.toString()?.trim().orEmpty()
        val typedToken = b.tokenInput.text?.toString()?.trim().orEmpty()

        if (!CompanionConfig.isAcceptableUrl(url)) {
            b.statusText.text = getString(R.string.error_bad_url)
            return null
        }
        if (sender.isEmpty() || sender.length > 40) {
            b.statusText.text = getString(R.string.error_bad_sender)
            return null
        }
        // keep the existing token if the user didn't type a new one
        val token = if (!tokenTouched || typedToken == getString(R.string.token_stored_placeholder) || typedToken.isEmpty())
            cfg.ingestToken else typedToken
        if (token.isEmpty()) {
            b.statusText.text = getString(R.string.error_no_token)
            return null
        }
        return FormValues(url, sender, bank, token)
    }

    private fun onSave() {
        val v = readForm() ?: return
        cfg.backendUrl = v.url
        cfg.senderId = v.sender
        cfg.bankName = v.bank
        cfg.ingestToken = v.token
        b.statusText.text = getString(R.string.saved)
        loadForm()
        render()
    }

    private fun onTest() {
        val v = readForm() ?: return
        b.testButton.isEnabled = false
        b.statusText.text = getString(R.string.testing)
        lifecycleScope.launch {
            // A sentinel body: a real bank-connection + valid token returns
            // 202 {ignored:"not a transaction message"}; a bad token -> 401;
            // a wrong sender -> 202 {ignored:"sender is not a configured..."}.
            val payload = EventPayload.build(v.sender, "expendicure companion connectivity check", System.currentTimeMillis())
            val result = withContext(Dispatchers.IO) {
                BackendClient.postSmsEvent(v.url, v.token, payload)
            }
            b.testButton.isEnabled = true
            b.statusText.text = when (result) {
                is ForwardResult.Unauthorized -> getString(R.string.test_bad_token)
                is ForwardResult.Unreachable -> getString(R.string.test_unreachable)
                is ForwardResult.Ignored ->
                    if (result.reason.contains("not a configured", true) || result.reason.contains("does not match", true))
                        getString(R.string.test_sender_mismatch)
                    else getString(R.string.test_ok)
                is ForwardResult.Created, is ForwardResult.Duplicate -> getString(R.string.test_ok)
                is ForwardResult.ServerError -> getString(R.string.test_server_error)
                is ForwardResult.Rejected -> getString(R.string.test_rejected)
            }
        }
    }

    private fun render() {
        val permission = hasSmsPermission()
        val configured = cfg.isConfigured
        b.grantPermissionButton.visibility = if (permission) android.view.View.GONE else android.view.View.VISIBLE
        b.permissionState.text = getString(
            if (permission) R.string.perm_granted else R.string.perm_needed
        )

        b.connectionState.text = when {
            !configured -> getString(R.string.state_not_configured)
            !permission -> getString(R.string.state_permission_missing)
            else -> getString(R.string.state_ready)
        }
        b.configuredBank.text = if (cfg.bankName.isNotEmpty()) cfg.bankName else "—"
        b.configuredSender.text = if (cfg.senderId.isNotEmpty()) cfg.senderId else "—"
        b.lastSync.text = if (cfg.lastSyncAtMillis == 0L) "—" else
            DateUtils.getRelativeTimeSpanString(cfg.lastSyncAtMillis).toString() +
                (if (cfg.lastStatus.isNotEmpty()) "  ·  ${cfg.lastStatus}" else "")

        b.rawFallbackSwitch.setOnCheckedChangeListener(null)
        b.rawFallbackSwitch.isChecked = cfg.rawFallbackEnabled
        b.rawFallbackSwitch.setOnCheckedChangeListener { _, checked ->
            cfg.rawFallbackEnabled = checked
            render()
        }
        b.rawFallbackNote.text = getString(
            if (cfg.rawFallbackEnabled) R.string.raw_fallback_on else R.string.raw_fallback_off
        )

        // Safe diagnostics: fixed stage labels + counters only. No message
        // content, no sender address, no token.
        b.diagStage.text = if (cfg.lastStage.isEmpty()) getString(R.string.diag_none) else cfg.lastStage
        b.diagCounters.text = getString(
            R.string.diag_counters, cfg.smsSeen, cfg.senderMatched, cfg.parsedOk, cfg.forwarded
        )
    }

    private data class FormValues(val url: String, val sender: String, val bank: String, val token: String)
}
