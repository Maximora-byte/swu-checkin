package io.github.maximorabyte.swucheckin

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Handler
import android.os.Looper
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/** The Python login session gives this broker only the current image bytes. */
class ManualCaptchaBroker(private val timeoutSeconds: Long = 120) {
    class Challenge(val image: Bitmap) {
        internal val done = CountDownLatch(1)
        internal var answer: String? = null
    }
    private val main = Handler(Looper.getMainLooper())
    private val cancelled = AtomicBoolean(false)
    private val active = AtomicReference<Challenge?>(null)
    var pending by mutableStateOf<Challenge?>(null)
        private set

    fun begin() { check(active.get() == null); cancelled.set(false) }
    fun isCancelled(): Boolean = cancelled.get()

    /** Callable from Chaquopy on its worker. Bounded wait, never the UI thread. */
    fun request(bytes: ByteArray): String? {
        check(Looper.myLooper() != Looper.getMainLooper())
        if (cancelled.get() || bytes.size !in 1..1_048_576) return null
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0 ||
            bounds.outWidth.toLong() * bounds.outHeight > 2_000_000) return null
        val bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: return null
        val challenge = Challenge(bitmap)
        if (!active.compareAndSet(null, challenge)) return null
        main.post { if (active.get() === challenge && !cancelled.get()) pending = challenge }
        try {
            if (cancelled.get()) challenge.done.countDown()
            if (!challenge.done.await(timeoutSeconds, TimeUnit.SECONDS)) cancelled.set(true)
            return if (cancelled.get()) null else challenge.answer
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
            cancelled.set(true)
            return null
        } finally {
            active.compareAndSet(challenge, null)
            main.post { if (pending === challenge) pending = null }
        }
    }

    fun answer(challenge: Challenge, text: String): Boolean {
        if (!text.matches(Regex("[A-Za-z0-9]{3,16}")) || cancelled.get()) return false
        if (!active.compareAndSet(challenge, null)) return false
        challenge.answer = text
        pending = null
        challenge.done.countDown()
        return true
    }

    fun cancel() {
        cancelled.set(true)
        active.getAndSet(null)?.done?.countDown()
        main.post { pending = null }
    }
}
