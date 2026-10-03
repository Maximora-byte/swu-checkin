package io.github.maximorabyte.swucheckin

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import org.json.JSONObject

/** Credential-free checks only; no school requests or submission. */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            SwuTheme {
                Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    Column(Modifier.fillMaxSize().safeDrawingPadding().verticalScroll(rememberScrollState())
                        .padding(horizontal = 20.dp, vertical = 18.dp),
                        verticalArrangement = Arrangement.spacedBy(16.dp)) {
                        PageHeading("运行环境", "帮助排查本地运行与网络连接", onBack = ::finish)
                        SwuCard {
                            Text("本地环境", style = MaterialTheme.typography.titleMedium)
                            Text("检查应用核心、时间、文件存取与重复操作保护。",
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Button(enabled = !ProbeRunner.busy, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
                                onClick = { ProbeRunner.run(applicationContext, false) }) {
                                SwuIcon(R.drawable.ic_device); Spacer(Modifier.width(8.dp)); Text("检查本地环境")
                            }
                        }
                        SwuCard {
                            Text("网络连接", style = MaterialTheme.typography.titleMedium)
                            Text("只连接公共站点 python.org，不登录学校账号或提交签到。",
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                            OutlinedButton(enabled = !ProbeRunner.busy, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
                                colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.primary),
                                onClick = { ProbeRunner.run(applicationContext, true) }) {
                                SwuIcon(R.drawable.ic_globe); Spacer(Modifier.width(8.dp)); Text("检查网络连接")
                            }
                        }
                        EnvironmentResult(ProbeRunner.result, ProbeRunner.busy)
                        Text("检测结果只用于排查运行问题，不代表学校登录或签到已经通过。",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
    }
}

@Composable
private fun EnvironmentResult(result: String, busy: Boolean) {
    val report = remember(result) { runCatching { JSONObject(result) }.getOrNull() }
    var details by remember { mutableStateOf(false) }
    val colors = MaterialTheme.colorScheme
    SwuCard {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            if (busy) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
            else SwuIcon(if (report?.optBoolean("passed") == true) R.drawable.ic_check else R.drawable.ic_info,
                tint = colors.primary)
            Text(when {
                busy -> "正在检测"
                report == null -> "检测结果"
                !report.optBoolean("passed") -> "检测未通过"
                report.optBoolean("https") -> "本地与网络检测通过"
                else -> "本地检测通过"
            }, style = MaterialTheme.typography.titleMedium)
        }
        if (busy) Text("请稍等，检测完成后会在这里显示结果。",
            style = MaterialTheme.typography.bodyMedium, color = colors.onSurfaceVariant)
        else if (report == null) Text(result, style = MaterialTheme.typography.bodyMedium, color = colors.onSurfaceVariant)
        else {
            EnvironmentCheck("应用核心", report.optBoolean("python_313") && report.optBoolean("core_import") && report.optBoolean("ocr_not_loaded"))
            EnvironmentCheck("时区与时间", report.optBoolean("timezone"))
            EnvironmentCheck("本地文件存取", report.optBoolean("private_storage"))
            EnvironmentCheck("重复操作保护", report.optBoolean("formal_lock_contention") && report.optBoolean("formal_lock_released"))
            EnvironmentCheck("连接证书校验", report.optBoolean("tls_verification"))
            EnvironmentCheck("公共网络连接", if (report.optString("https") == "not_run") null else report.optBoolean("https"))
            TextButton(onClick = { details = !details }) { Text(if (details) "收起技术报告" else "查看技术报告") }
            if (details) Text(result, fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall,
                color = colors.onSurfaceVariant)
        }
    }
}

@Composable
private fun EnvironmentCheck(label: String, passed: Boolean?) {
    val colors = MaterialTheme.colorScheme
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(label, modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
        SwuIcon(if (passed == true) R.drawable.ic_check else if (passed == false) R.drawable.ic_info else R.drawable.ic_clock,
            modifier = Modifier.size(16.dp), tint = if (passed == false) colors.error else colors.primary)
        Text(if (passed == null) "未检测" else if (passed) "通过" else "未通过",
            style = MaterialTheme.typography.bodySmall,
            color = if (passed == false) colors.error else colors.onSurfaceVariant)
    }
}
