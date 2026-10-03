package io.github.maximorabyte.swucheckin

import android.content.Intent
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp

class CheckinActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        enableEdgeToEdge()
        setContent {
            SwuTheme {
                Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    val state = CheckinController
                    var confirming by remember { mutableStateOf(false) }
                    var present by remember { mutableStateOf(false) }
                    var usage by remember { mutableStateOf(false) }
                    CheckinScreen(
                        state = CheckinUiState(state.username, state.password, state.remember,
                            state.busy, state.pending, state.result),
                        actions = CheckinUiActions(
                            editUsername = state::editUsername, editPassword = state::editPassword,
                            rememberAccount = { state.setRemember(applicationContext, it) },
                            load = { state.load(applicationContext) }, forget = { state.forget(applicationContext) },
                            query = { state.run(applicationContext, "probe") },
                            checkin = { confirming = true; present = false },
                            diagnose = { state.run(applicationContext, "diagnose") },
                            cancel = state::cancel,
                            environment = { startActivity(Intent(this@CheckinActivity, MainActivity::class.java)) },
                            usage = { usage = true },
                        ),
                    )
                    if (usage) AlertDialog(
                        onDismissRequest = { usage = false },
                        icon = { SwuIcon(R.drawable.ic_info) }, title = { Text("使用前请了解") },
                        text = { Text("查询和只读诊断不会提交签到。\n\n手动签到会沿用学校返回的宿舍坐标，不读取手机 GPS，也不能证明本人在寝。请只在本人在寝且符合学校规定时提交。\n\n账号保存使用本设备的加密密钥；关闭保存或清除账号会删除已保存记录。") },
                        confirmButton = { TextButton(onClick = { usage = false }) { Text("知道了") } },
                    )
                    if (confirming) AlertDialog(
                        onDismissRequest = { confirming = false },
                        icon = { SwuIcon(R.drawable.ic_check) }, title = { Text("确认本次签到") },
                        text = { Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
                            Text("本次会向学校提交一次签到，并查询确认结果。使用学校宿舍坐标，不读取手机 GPS。")
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Checkbox(present, { present = it }, modifier = Modifier.testTag("present"))
                                Text("我确认本人当前在寝，并符合学校签到规定。",
                                    style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                            }
                        } },
                        confirmButton = { TextButton(enabled = present, onClick = {
                            confirming = false; state.run(applicationContext, "checkin", true)
                        }) { Text("确认提交一次") } },
                        dismissButton = { TextButton(onClick = { confirming = false }) { Text("返回查询") } },
                    )
                    val challenge = state.captcha.pending
                    if (challenge != null) {
                        var answer by remember(challenge) { mutableStateOf("") }
                        AlertDialog(onDismissRequest = state::cancel,
                            icon = { SwuIcon(R.drawable.ic_lock) }, title = { Text("填写当前验证码") },
                            text = { Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
                                Surface(shape = RoundedCornerShape(14.dp),
                                    color = MaterialTheme.colorScheme.surfaceVariant) {
                                    Image(challenge.image.asImageBitmap(), contentDescription = "当前登录会话验证码",
                                        contentScale = ContentScale.Fit,
                                        modifier = Modifier.fillMaxWidth().height(80.dp).padding(12.dp))
                                }
                                OutlinedTextField(answer, { answer = it.take(16) }, label = { Text("验证码") },
                                    singleLine = true, shape = RoundedCornerShape(14.dp),
                                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii),
                                    modifier = Modifier.fillMaxWidth().testTag("captcha"))
                                Text("输入图片中的英文字母和数字。两分钟未填写会取消本次登录。",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                            } },
                            confirmButton = { TextButton(enabled = answer.matches(Regex("[A-Za-z0-9]{3,16}")),
                                onClick = { state.captcha.answer(challenge, answer) }) { Text("提交验证码") } },
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
