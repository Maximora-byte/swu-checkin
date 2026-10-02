package io.github.maximorabyte.swucheckin

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

/** Feasibility gate only: no credentials, school network calls, or submit entry. */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Column(
                    modifier = Modifier.fillMaxSize().padding(24.dp),
                    verticalArrangement = Arrangement.spacedBy(16.dp),
                ) {
                    Text("Android / Python 3.13 可行性验证", style = MaterialTheme.typography.titleLarge)
                    Text("不保存账号密码，不访问学校服务，不请求位置权限。学校宿舍坐标不是真实 GPS，也不能证明本人在寝。")
                    Button(enabled = !ProbeRunner.busy, onClick = { ProbeRunner.run(applicationContext, false) }) { Text("验证离线运行环境") }
                    Button(enabled = !ProbeRunner.busy, onClick = { ProbeRunner.run(applicationContext, true) }) { Text("验证公共 HTTPS（python.org）") }
                    Text(ProbeRunner.result)
                }
            }
        }
    }

}
