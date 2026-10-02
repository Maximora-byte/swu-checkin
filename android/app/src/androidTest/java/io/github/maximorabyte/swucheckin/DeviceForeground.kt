package io.github.maximorabyte.swucheckin

import androidx.test.platform.app.InstrumentationRegistry
import java.io.FileInputStream

/** OEM phones may reject ActivityScenario after the previous scenario closes. */
object DeviceForeground {
    fun warm() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val target = instrumentation.targetContext.packageName
        instrumentation.uiAutomation.executeShellCommand(
            "am start -W -n $target/io.github.maximorabyte.swucheckin.MainActivity"
        ).use { descriptor -> FileInputStream(descriptor.fileDescriptor).use { it.readBytes() } }
    }
}
