package io.github.maximorabyte.swucheckin

import android.os.Handler
import android.os.Looper
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.chaquo.python.Python
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/** Process-scoped diagnostics survive rotation without retaining an Activity. */
object ProbeRunner {
    private val worker = Executors.newSingleThreadExecutor()
    private val inFlight = AtomicBoolean(false)
    private val main = Handler(Looper.getMainLooper())
    var busy by mutableStateOf(false)
        private set
    var result by mutableStateOf("尚未运行。此 APK 仅验证运行环境，不能登录或签到。")
        private set

    fun run(privateDirectory: String, withHttps: Boolean) {
        if (!inFlight.compareAndSet(false, true)) return
        busy = true
        worker.execute {
            val output = try {
                Python.getInstance().getModule("android_probe")
                    .callAttr("run", privateDirectory, withHttps).toString()
            } catch (_: Exception) {
                // Never surface arbitrary Python/HTTP exceptions to UI or Logcat.
                "运行环境验证失败；请查看已脱敏的测试报告。"
            }
            main.post {
                result = output
                busy = false
                inFlight.set(false)
            }
        }
    }
}
