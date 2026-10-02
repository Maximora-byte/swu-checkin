package io.github.maximorabyte.swucheckin

import android.app.Service
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.Message
import android.os.Messenger
import android.os.Process
import com.chaquo.python.Python

/** Instrumentation-only lock owner; contains no authentication or submit path. */
class LockProbeService : Service() {
    private val channel = Messenger(Handler(Looper.getMainLooper()) { message ->
        val path = noBackupFilesDir.resolve("cross-process.lock").absolutePath
        val module = Python.getInstance().getModule("android_lock_probe")
        val acquired = when (message.what) {
            1 -> module.callAttr("try_once", path).toBoolean()
            2 -> module.callAttr("hold", path).toBoolean()
            3 -> true
            else -> false
        }
        message.replyTo?.send(Message.obtain(null, message.what).apply {
            data = Bundle().apply {
                putBoolean("acquired", acquired)
                putInt("pid", Process.myPid())
            }
        })
        if (message.what == 3) Process.killProcess(Process.myPid())
        true
    })

    override fun onBind(intent: Intent?): IBinder = channel.binder
    override fun onDestroy() {
        Python.getInstance().getModule("android_lock_probe").callAttr("release")
        super.onDestroy()
    }
}
