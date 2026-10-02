package io.github.maximorabyte.swucheckin

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

/** Exercise the actual buttons and Activity recreation with synthetic data only. */
@RunWith(AndroidJUnit4::class)
class DiagnosticsUiTest {
    @get:Rule val compose = createAndroidComposeRule<MainActivity>()

    @Test fun diagnosticButtonsAndRecreation() {
        compose.onNodeWithText("Android / Python 3.13 可行性验证").assertIsDisplayed()
        compose.onNodeWithText("验证离线运行环境").performClick()
        compose.waitUntil(timeoutMillis = 120_000) { !ProbeRunner.busy && ProbeRunner.result.startsWith("{") }
        val offline = JSONObject(ProbeRunner.result)
        assertTrue(offline.toString(), offline.getBoolean("passed"))
        assertTrue(offline.getString("https") == "not_run")

        compose.activityRule.scenario.recreate()
        compose.onNodeWithText(ProbeRunner.result).assertIsDisplayed()
        compose.onNodeWithText("验证公共 HTTPS（python.org）").assertIsEnabled().performClick()
        compose.waitUntil(timeoutMillis = 120_000) { !ProbeRunner.busy }
        val online = JSONObject(ProbeRunner.result)
        assertTrue(online.toString(), online.getBoolean("passed"))
        assertTrue(online.getBoolean("https"))
        compose.onNodeWithText("验证离线运行环境").assertIsEnabled()
    }
}
