package io.github.maximorabyte.swucheckin

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Invoked separately on a newly installed disposable release app, across adb install -r. */
@RunWith(AndroidJUnit4::class)
class ReleaseUpgradeTest {
    private fun store() = SecureAccountStore(
        ApplicationProvider.getApplicationContext<Context>(), "release_upgrade"
    )

    @Test fun storeSyntheticUpgradeAccount() {
        val storage = store()
        assertNull(storage.load())
        storage.save(Account("synthetic-upgrade-user", "synthetic-upgrade-password"))
        assertEquals("synthetic-upgrade-user", storage.load()!!.username)
    }

    @Test fun verifySyntheticUpgradeAccount() {
        val storage = store()
        try {
            val account = requireNotNull(storage.load())
            assertEquals("synthetic-upgrade-user", account.username)
            assertEquals("synthetic-upgrade-password", account.password)
        } finally { storage.delete() }
        assertNull(storage.load())
    }
}
