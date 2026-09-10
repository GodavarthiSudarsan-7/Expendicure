package com.expendicure.companion

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Config validation: which backend URLs the companion will accept.
 * HTTPS is always allowed; plain HTTP only on a private/LAN host (dev opt-in).
 * `CompanionConfig.isAcceptableUrl` touches no Android APIs, so it runs here.
 */
class CompanionConfigUrlTest {

    @Test fun acceptsAnyHttpsUrl() {
        assertTrue(CompanionConfig.isAcceptableUrl("https://finance.example.com"))
        assertTrue(CompanionConfig.isAcceptableUrl("https://expendicure.example.com:8443/base"))
        assertTrue(CompanionConfig.isAcceptableUrl("  HTTPS://Example.com  "))
    }

    @Test fun acceptsHttpOnlyOnPrivateOrLanHosts() {
        assertTrue(CompanionConfig.isAcceptableUrl("http://localhost:5000"))
        assertTrue(CompanionConfig.isAcceptableUrl("http://127.0.0.1:5000"))
        assertTrue(CompanionConfig.isAcceptableUrl("http://192.168.1.10:5000"))
        assertTrue(CompanionConfig.isAcceptableUrl("http://10.0.0.4:5000"))
        assertTrue(CompanionConfig.isAcceptableUrl("http://172.16.5.9:5000"))
        assertTrue(CompanionConfig.isAcceptableUrl("http://172.31.9.9"))
        assertTrue(CompanionConfig.isAcceptableUrl("http://my-pc.local:5000"))
    }

    @Test fun rejectsPlainHttpOnPublicHosts() {
        assertFalse(CompanionConfig.isAcceptableUrl("http://finance.example.com"))
        assertFalse(CompanionConfig.isAcceptableUrl("http://8.8.8.8"))
        assertFalse(CompanionConfig.isAcceptableUrl("http://172.32.0.1")) // outside 172.16/12
        assertFalse(CompanionConfig.isAcceptableUrl("http://192.169.1.1"))
    }

    @Test fun rejectsMalformedOrEmptyConfig() {
        assertFalse(CompanionConfig.isAcceptableUrl(null))
        assertFalse(CompanionConfig.isAcceptableUrl(""))
        assertFalse(CompanionConfig.isAcceptableUrl("   "))
        assertFalse(CompanionConfig.isAcceptableUrl("finance.example.com"))
        assertFalse(CompanionConfig.isAcceptableUrl("ftp://192.168.1.10"))
        assertFalse(CompanionConfig.isAcceptableUrl("javascript:alert(1)"))
    }
}
