package io.github.maximorabyte.swucheckin

import android.util.Log
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.json.JSONObject
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.rules.RuleChain
import org.junit.rules.TestWatcher
import org.junit.rules.Timeout
import org.junit.runner.Description

/** Exercise the actual buttons and Activity recreation with synthetic data only. */
@RunWith(AndroidJUnit4::class)
class DiagnosticsUiTest {
    private val compose = createAndroidComposeRule<MainActivity>()
    @get:Rule val rules: RuleChain = RuleChain.outerRule(Timeout.seconds(300)).around(object : TestWatcher() {
        override fun starting(description: Description) {
            Log.i("FeasibilityUiTest", "launching activity")
            DeviceForeground.warm()
        }
    }).around(compose)

    @Test fun diagnosticButtonsAndRecreation() {
        Log.i("FeasibilityUiTest", "activity ready; checking title")
        compose.onNodeWithText("Android / Python 3.13 可行性验证").assertIsDisplayed()
        Log.i("FeasibilityUiTest", "clicking offline probe")
        compose.onNodeWithText("验证离线运行环境").performClick()
        compose.waitUntil(timeoutMillis = 120_000) { !ProbeRunner.busy && ProbeRunner.result.startsWith("{") }
        val offline = JSONObject(ProbeRunner.result)
        assertTrue(offline.toString(), offline.getBoolean("passed"))
        assertTrue(offline.getString("https") == "not_run")

        Log.i("FeasibilityUiTest", "recreating activity")
        compose.activityRule.scenario.recreate()
        compose.onNodeWithText(ProbeRunner.result).assertIsDisplayed()
        compose.onNodeWithText("验证公共 HTTPS（python.org）").assertIsEnabled().performClick()
        Log.i("FeasibilityUiTest", "waiting for verified HTTPS")
        compose.waitUntil(timeoutMillis = 120_000) { !ProbeRunner.busy }
        val online = JSONObject(ProbeRunner.result)
        assertTrue(online.toString(), online.getBoolean("passed"))
        assertTrue(online.getBoolean("https"))
        compose.onNodeWithText("验证离线运行环境").assertIsEnabled()
        Log.i("FeasibilityUiTest", "completed")
    }
}
