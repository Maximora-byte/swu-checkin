package io.github.maximorabyte.swucheckin

import android.view.WindowManager
import android.util.Log
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.lifecycle.Lifecycle
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.chaquo.python.PyObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.RuleChain
import org.junit.rules.Timeout
import org.junit.rules.TestWatcher
import org.junit.runner.Description
import org.junit.runner.RunWith
import java.io.File

/** Full manual UI uses the real Python login/core but all transport is synthetic. */
@RunWith(AndroidJUnit4::class)
class CheckinUiTest {
    private val compose = createAndroidComposeRule<CheckinActivity>()
    @get:Rule val rules: RuleChain = RuleChain.outerRule(Timeout.seconds(300)).around(object : TestWatcher() {
        override fun starting(description: Description) { DeviceForeground.warm() }
    }).around(compose)

    @Test fun manualLoginQueryConfirmationAndCancellation() {
        Log.i("ManualUiTest", "preparing synthetic login")
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val python = PythonRuntime.instance(context)
        val script = InstrumentationRegistry.getInstrumentation().context.assets.open("android_demo.py").bufferedReader().use { it.readText() }
        val globals = python.getModule("__main__").get("__dict__")!!
        python.getModule("builtins").callAttr("exec", script, globals)
        val adapter = python.getModule("__main__").callAttr("make_android_demo", CheckinController.captcha,
            File(context.noBackupFilesDir, "synthetic-ui.lock").absolutePath)
        val backend: PyObject = adapter.get("demo_backend")!!
        compose.runOnIdle {
            assertTrue(compose.activity.window.attributes.flags and WindowManager.LayoutParams.FLAG_SECURE != 0)
            CheckinController.useSyntheticClient(adapter)
        }
        try {
            compose.onNodeWithTag("username").performTextInput("synthetic-user")
            compose.onNodeWithTag("password").performTextInput("synthetic-password")
            compose.onNodeWithText("手动签到").assertIsNotEnabled()
            compose.onNodeWithText("查询今日状态").performScrollTo().performClick()
            Log.i("ManualUiTest", "waiting for captcha")
            compose.waitUntil(120_000) { CheckinController.captcha.pending != null }
            compose.activityRule.scenario.recreate()
            compose.onNodeWithTag("captcha").performTextInput("Ab12")
            compose.onNodeWithText("提交验证码").performClick()
            Log.i("ManualUiTest", "checking pending task")
            compose.waitUntil(120_000) { !CheckinController.busy }
            assertTrue(CheckinController.pending)
            assertEquals(0, backend.get("submissions")!!.toInt())
            compose.onNodeWithText("手动签到").performScrollTo().performClick()
            compose.onNodeWithText("确认提交一次").assertIsNotEnabled()
            compose.onNodeWithText("返回查询").performClick()
            assertEquals(0, backend.get("submissions")!!.toInt())
            compose.onNodeWithText("手动签到").performClick()
            compose.onNodeWithTag("present").performClick()
            compose.onNodeWithText("确认提交一次").performClick()
            Log.i("ManualUiTest", "checking confirmed submit")
            compose.waitUntil(120_000) { !CheckinController.busy }
            assertEquals("签到成功，服务端已确认。", CheckinController.result)
            assertEquals(1, backend.get("submissions")!!.toInt())
            compose.onNodeWithText("手动签到").assertIsNotEnabled()
            compose.onNodeWithText("查询今日状态").performScrollTo().performClick()
            compose.waitUntil(120_000) { !CheckinController.busy }
            assertEquals("今日已签到。", CheckinController.result)
            compose.onNodeWithText("只读诊断").performScrollTo().performClick()
            compose.waitUntil(120_000) { !CheckinController.busy }
            assertFalse(CheckinController.result.contains("未通过"))
            assertEquals(1, backend.get("submissions")!!.toInt())
            adapter.callAttr("clear")
            compose.onNodeWithText("查询今日状态").performScrollTo().performClick()
            compose.waitUntil(120_000) { CheckinController.captcha.pending != null }
            compose.activityRule.scenario.moveToState(Lifecycle.State.CREATED)
            Log.i("ManualUiTest", "checking background cancellation")
            compose.activityRule.scenario.moveToState(Lifecycle.State.RESUMED)
            compose.waitUntil(120_000) { !CheckinController.busy }
            assertTrue(CheckinController.result.startsWith("操作已取消"))
            assertEquals(1, backend.get("submissions")!!.toInt())
            Log.i("ManualUiTest", "completed")
        } finally {
            compose.runOnIdle { CheckinController.cancel() }
            compose.waitUntil(120_000) { !CheckinController.busy }
            compose.runOnIdle { CheckinController.useSyntheticClient(null) }
        }
    }
}
