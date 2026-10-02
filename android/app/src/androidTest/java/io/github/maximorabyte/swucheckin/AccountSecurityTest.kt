package io.github.maximorabyte.swucheckin

import android.content.Context
import android.graphics.Bitmap
import android.security.keystore.KeyProperties
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.ByteArrayOutputStream
import java.io.File
import java.security.KeyStore
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

@RunWith(AndroidJUnit4::class)
class AccountSecurityTest {
    @Test fun encryptionTamperingAndMissingKeyFailClosed() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val namespace = "test_${UUID.randomUUID()}"
        val store = SecureAccountStore(context, namespace)
        val file = File(context.noBackupFilesDir, "$namespace.enc")
        val account = Account("synthetic-user", "synthetic-password")
        try {
            assertNull(store.load())
            store.save(account)
            val first = file.readBytes()
            assertFalse(String(first, Charsets.ISO_8859_1).contains(account.password))
            assertFalse(String(first, Charsets.ISO_8859_1).contains(account.username))
            assertEquals(account.password, SecureAccountStore(context, namespace).load()!!.password)
            store.save(account)
            val second = file.readBytes()
            assertFalse(first.contentEquals(second))
            second[second.lastIndex] = (second.last().toInt() xor 1).toByte()
            file.writeBytes(second)
            try { store.load(); fail("tampered ciphertext accepted") } catch (_: AccountStorageException) { }
            store.save(account)
            val keys = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            val alias = "${context.packageName}.credentials.v1.$namespace"
            assertNull(keys.getKey(alias, null).encoded)
            assertEquals(KeyProperties.KEY_ALGORITHM_AES, keys.getKey(alias, null).algorithm)
            keys.deleteEntry(alias)
            try { store.load(); fail("missing key accepted") } catch (_: AccountStorageException) { }
            assertFalse(keys.containsAlias(alias))
        } finally { store.delete() }
        assertFalse(file.exists())
        assertNull(store.load())
    }

    @Test fun captchaCancellationTimeoutAndStaleAnswer() {
        val image = ByteArrayOutputStream().also {
            Bitmap.createBitmap(2, 2, Bitmap.Config.ARGB_8888).compress(Bitmap.CompressFormat.PNG, 100, it)
        }.toByteArray()
        val executor = Executors.newSingleThreadExecutor()
        val broker = ManualCaptchaBroker(1)
        fun current(): ManualCaptchaBroker.Challenge {
            val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5)
            while (broker.pending == null && System.nanoTime() < deadline) Thread.sleep(10)
            return requireNotNull(broker.pending)
        }
        try {
            broker.begin()
            val answer = executor.submit<String?> { broker.request(image) }
            val first = current()
            assertFalse(broker.answer(first, "ＡＢ１２"))
            assertTrue(broker.answer(first, "Ab12"))
            assertEquals("Ab12", answer.get(5, TimeUnit.SECONDS))
            assertFalse(broker.answer(first, "Ab12"))
            broker.begin()
            val cancelled = executor.submit<String?> { broker.request(image) }
            current()
            broker.cancel()
            assertNull(cancelled.get(5, TimeUnit.SECONDS))
            assertTrue(broker.isCancelled())
            broker.begin()
            assertNull(executor.submit<String?> { broker.request(image) }.get(5, TimeUnit.SECONDS))
            assertTrue(broker.isCancelled())
            broker.begin()
            assertNull(broker.request(ByteArray(1_048_577)))
            assertNull(broker.request(byteArrayOf(0, 1, 2)))
        } finally { broker.cancel(); executor.shutdownNow() }
    }
}
