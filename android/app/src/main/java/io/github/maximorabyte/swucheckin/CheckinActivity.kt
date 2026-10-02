package io.github.maximorabyte.swucheckin

import android.content.Intent
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp

class CheckinActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        enableEdgeToEdge()
        setContent {
            MaterialTheme {
                Surface {
                    val state = CheckinController
                    var confirming by remember { mutableStateOf(false) }
                    var present by remember { mutableStateOf(false) }
                    Column(Modifier.fillMaxSize().safeDrawingPadding().verticalScroll(rememberScrollState()).padding(20.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        Text("SWU 查寝", style = MaterialTheme.typography.headlineMedium)
                        Text("查询不会提交签到。仅支持你主动确认的手动签到。")
                        OutlinedTextField(state.username, state::editUsername, enabled = !state.busy,
                            label = { Text("校园账号") }, singleLine = true,
                            modifier = Modifier.fillMaxWidth().testTag("username"))
                        OutlinedTextField(state.password, state::editPassword, enabled = !state.busy,
                            label = { Text("密码") }, singleLine = true,
                            visualTransformation = PasswordVisualTransformation(),
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                            modifier = Modifier.fillMaxWidth().testTag("password"))
                        Row {
                            Checkbox(state.remember, { state.setRemember(applicationContext, it) }, enabled = !state.busy)
                            Text("在此设备加密保存账号与密码", modifier = Modifier.padding(top = 12.dp))
                        }
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            TextButton(enabled = !state.busy, onClick = { state.load(applicationContext) }) { Text("读取已保存账号") }
                            TextButton(enabled = !state.busy, onClick = { state.forget(applicationContext) }) { Text("清除账号") }
                        }
                        val ready = !state.busy && state.username.isNotBlank() && state.password.isNotEmpty()
                        Button(enabled = ready, modifier = Modifier.fillMaxWidth(), onClick = { state.run(applicationContext, "probe") }) { Text("查询今日状态") }
                        Button(enabled = ready && state.pending, modifier = Modifier.fillMaxWidth(), onClick = { confirming = true; present = false }) { Text("手动签到") }
                        TextButton(enabled = ready, onClick = { state.run(applicationContext, "diagnose") }) { Text("只读诊断") }
                        if (state.busy) {
                            CircularProgressIndicator()
                            TextButton(onClick = state::cancel) { Text("取消操作") }
                        }
                        Text(state.result, modifier = Modifier.testTag("result"))
                        Text("提交沿用学校返回的宿舍坐标，不会读取手机 GPS，也不能证明本人在寝。请只在本人在寝且符合学校规定时签到。",
                            style = MaterialTheme.typography.bodySmall)
                        TextButton(enabled = !state.busy, onClick = { startActivity(Intent(this@CheckinActivity, MainActivity::class.java)) }) { Text("运行环境检测") }
                    }
                    if (confirming) AlertDialog(
                        onDismissRequest = { confirming = false }, title = { Text("确认本次签到") },
                        text = { Column {
                            Text("本次会向学校提交签到，并再次查询确认结果。使用学校宿舍坐标，不读取手机 GPS。")
                            Row { Checkbox(present, { present = it }, modifier = Modifier.testTag("present")); Text("我确认本人当前在寝，并符合学校签到规定。") }
                        } },
                        confirmButton = { TextButton(enabled = present, onClick = { confirming = false; state.run(applicationContext, "checkin", true) }) { Text("确认提交一次") } },
                        dismissButton = { TextButton(onClick = { confirming = false }) { Text("返回查询") } },
                    )
                    val challenge = state.captcha.pending
                    if (challenge != null) {
                        var answer by remember(challenge) { mutableStateOf("") }
                        AlertDialog(onDismissRequest = state::cancel,
                            title = { Text("填写当前验证码") },
                            text = { Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                                Image(challenge.image.asImageBitmap(), contentDescription = "当前登录会话验证码")
                                OutlinedTextField(answer, { answer = it.take(16) }, label = { Text("验证码") }, singleLine = true,
                                    modifier = Modifier.testTag("captcha"))
                                Text("请输入图片中的英文字母和数字；两分钟未填写会取消本次登录。")
                            } },
                            confirmButton = { TextButton(enabled = answer.matches(Regex("[A-Za-z0-9]{3,16}")), onClick = { state.captcha.answer(challenge, answer) }) { Text("提交验证码") } },
                            dismissButton = { TextButton(onClick = state::cancel) { Text("取消登录") } },
                        )
                    }
                }
            }
        }
    }

    override fun onStop() {
        super.onStop()
        // Rotation retains only process memory; leaving the foreground cancels
        // pending captcha and blocks any not-yet-sent submit in the Python gate.
        if (!isChangingConfigurations && CheckinController.busy) CheckinController.cancel()
    }
}
