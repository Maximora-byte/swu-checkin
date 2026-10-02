package io.github.maximorabyte.swucheckin

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.Message
import android.os.Messenger
import android.os.Process
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

@RunWith(AndroidJUnit4::class)
class CrossProcessLockTest {
    @Test fun lockIsSharedAndProcessDeathReleasesIt() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val path = context.noBackupFilesDir.resolve("cross-process.lock").absolutePath
        val module = PythonRuntime.instance(context).getModule("android_lock_probe")
        val connected = CountDownLatch(1)
        val disconnected = CountDownLatch(1)
        var remote: Messenger? = null
        val connection = object : ServiceConnection {
            override fun onServiceConnected(name: ComponentName?, service: IBinder?) {
                remote = Messenger(service)
                connected.countDown()
            }
            override fun onServiceDisconnected(name: ComponentName?) {
                remote = null
                disconnected.countDown()
            }
        }
        assertTrue(context.bindService(Intent(context, LockProbeService::class.java), connection, Context.BIND_AUTO_CREATE))
        try {
            assertTrue("second process did not connect", connected.await(30, TimeUnit.SECONDS))
            fun request(command: Int): Boolean {
                val received = CountDownLatch(1)
                var acquired = false
                var remotePid = 0
                val reply = Messenger(Handler(Looper.getMainLooper()) { message ->
                    acquired = message.data.getBoolean("acquired")
                    remotePid = message.data.getInt("pid")
                    received.countDown()
                    true
                })
                remote!!.send(Message.obtain(null, command).apply { replyTo = reply })
                assertTrue("second process did not reply", received.await(30, TimeUnit.SECONDS))
                assertTrue("lock owner is not a distinct process", remotePid > 0 && remotePid != Process.myPid())
                return acquired
            }
            assertTrue(module.callAttr("hold", path).toBoolean())
            assertFalse("remote process bypassed held lock", request(1))
            module.callAttr("release")
            assertTrue("remote process could not acquire released lock", request(2))
            assertFalse("main process bypassed remote lock", module.callAttr("try_once", path).toBoolean())
            assertTrue(request(3)) // Kill only the synthetic :lockprobe process.
            assertTrue("lock owner did not die", disconnected.await(30, TimeUnit.SECONDS))
            var released = false
            for (attempt in 1..50) {
                if (module.callAttr("try_once", path).toBoolean()) { released = true; break }
                Thread.sleep(100)
            }
            assertTrue("OS lock survived owner process death", released)
        } finally {
            module.callAttr("release")
            context.unbindService(connection)
        }
    }
}
