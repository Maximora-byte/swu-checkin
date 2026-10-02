package io.github.maximorabyte.swucheckin

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class RuntimeFeasibilityTest {
    @Test fun embeddedPythonCoreStorageTimezoneAndLock() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val report = JSONObject(PythonRuntime.instance(context).getModule("android_probe")
            .callAttr("run", context.noBackupFilesDir.absolutePath, false).toString())
        assertTrue(report.toString(), report.getBoolean("passed"))
        for (key in listOf("python_313", "core_import", "ocr_not_loaded", "timezone",
            "private_storage", "formal_lock_contention", "formal_lock_released", "tls_verification")) {
            assertTrue(key, report.getBoolean(key))
        }
        assertFalse(context.applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_ALLOW_BACKUP != 0)
    }

    @Test fun verifiedPublicHttpsFromEmbeddedPython() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val report = JSONObject(PythonRuntime.instance(context).getModule("android_probe")
            .callAttr("run", context.noBackupFilesDir.absolutePath, true).toString())
        assertTrue(report.toString(), report.getBoolean("passed"))
        assertTrue(report.getBoolean("https"))
    }
}
