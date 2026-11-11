package io.github.maximorabyte.swucheckin

import androidx.activity.compose.setContent
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.lifecycle.Lifecycle
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertSame
import org.junit.Rule
import org.junit.Test
import org.junit.rules.RuleChain
import org.junit.rules.TestWatcher
import org.junit.rules.Timeout
import org.junit.runner.Description
import org.junit.runner.RunWith
import java.util.Calendar
import java.util.TimeZone
import java.util.concurrent.atomic.AtomicLong

/** Synthetic wall clock only: never changes the device clock or contacts school services. */
@RunWith(AndroidJUnit4::class)
class CheckinDateTest {
    private val compose = createAndroidComposeRule<MainActivity>()
    @get:Rule val rules: RuleChain = RuleChain.outerRule(Timeout.seconds(60)).around(object : TestWatcher() {
        override fun starting(description: Description) { DeviceForeground.warm() }
    }).around(compose)

    private fun timestamp(day: Int, hour: Int = 12, minute: Int = 0,
        second: Int = 0, millis: Int = 0): Long = Calendar.getInstance(TimeZone.getTimeZone("Asia/Shanghai")).apply {
        clear()
        set(2026, Calendar.NOVEMBER, day, hour, minute, second)
        set(Calendar.MILLISECOND, millis)
    }.timeInMillis

    private fun showDate(clock: AtomicLong) {
        compose.activityRule.scenario.onActivity { activity ->
            activity.setContent { SwuTheme { CheckinDateLabel(now = clock::get) } }
        }
    }

    private fun expectDate(text: String) {
        compose.waitUntil(5_000) {
            compose.onAllNodesWithText(text).fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNodeWithTag("today-date").assertTextEquals(text)
    }

    @Test fun foregroundMidnightRefreshesWithoutRecreation() {
        val clock = AtomicLong(timestamp(11, 23, 59, 59, 800))
        showDate(clock)
        expectDate("SWU 查寝 · 11月11日 周三")
        val activity = compose.activity
        clock.set(timestamp(12, 0, 0, 0, 100))
        expectDate("SWU 查寝 · 11月12日 周四")
        assertSame(activity, compose.activity)
    }

    @Test fun resumeAfterMidnightRefreshesWithoutRecreation() {
        val clock = AtomicLong(timestamp(11))
        showDate(clock)
        expectDate("SWU 查寝 · 11月11日 周三")
        val activity = compose.activity
        compose.activityRule.scenario.moveToState(Lifecycle.State.CREATED)
        clock.set(timestamp(12))
        compose.activityRule.scenario.moveToState(Lifecycle.State.RESUMED)
        expectDate("SWU 查寝 · 11月12日 周四")
        assertSame(activity, compose.activity)
    }

    @Test fun dateUsesShanghaiWhenDeviceTimezoneDiffers() {
        val original = TimeZone.getDefault()
        try {
            TimeZone.setDefault(TimeZone.getTimeZone("America/Los_Angeles"))
            showDate(AtomicLong(timestamp(12, 0, 0, 0)))
            expectDate("SWU 查寝 · 11月12日 周四")
        } finally {
            TimeZone.setDefault(original)
        }
    }
}
