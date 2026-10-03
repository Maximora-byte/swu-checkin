package io.github.maximorabyte.swucheckin

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier

/** Debug-only screenshot surface: synthetic data, no controller or network access. */
class DesignPreviewActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val kind = intent.getStringExtra("state") ?: "empty"
        setContent {
            SwuTheme(darkTheme = intent.getBooleanExtra("dark", false)) {
                var state by remember {
                    mutableStateOf(CheckinUiState(
                        username = if (kind == "empty") "" else "demo.student",
                        password = if (kind == "empty") "" else "synthetic-password",
                        rememberAccount = kind != "empty", busy = kind == "busy", pending = kind == "pending",
                        result = when (kind) {
                            "pending" -> "今日待签到。确认本人在寝后，可手动提交。"
                            "complete" -> "今日已签到。"
                            "busy" -> "正在查询，请按提示填写验证码。"
                            "error" -> "登录失败，请检查账号、密码和验证码。"
                            else -> "输入校园账号后，先查询今日状态。"
                        },
                    ))
                }
                Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    CheckinScreen(state, CheckinUiActions(
                        editUsername = { state = state.copy(username = it, pending = false) },
                        editPassword = { state = state.copy(password = it, pending = false) },
                        rememberAccount = { state = state.copy(rememberAccount = it) },
                        load = {}, forget = { state = state.copy(username = "", password = "", rememberAccount = false) },
                        query = {}, checkin = {}, diagnose = {}, cancel = {}, environment = {}, usage = {},
                    ), previewNotice = "界面预览 · 合成账号与状态")
                }
            }
        }
    }
}
