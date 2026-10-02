package io.github.maximorabyte.swucheckin

import android.content.Context
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

/** Start on a worker/test thread: first-run extraction must not block app startup. */
object PythonRuntime {
    @Synchronized
    fun instance(context: Context): Python {
        if (!Python.isStarted()) Python.start(AndroidPlatform(context.applicationContext))
        return Python.getInstance()
    }
}
