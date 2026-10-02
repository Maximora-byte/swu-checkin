package io.github.maximorabyte.swucheckin

import android.content.Context
import android.os.Handler
import android.os.Looper
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.chaquo.python.PyObject
import org.json.JSONObject
import java.io.File
import java.util.concurrent.Executors

/** Process memory survives rotation; passwords never enter saved instance state. */
object CheckinController {
    private val executor = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())
    val captcha = ManualCaptchaBroker()
    private var client: PyObject? = null
    private var synthetic = false
    var username by mutableStateOf("")
        private set
    var password by mutableStateOf("")
        private set
    var remember by mutableStateOf(false)
        private set
    var busy by mutableStateOf(false)
        private set
    var result by mutableStateOf("输入校园账号后，先查询今日状态。")
        private set
    var pending by mutableStateOf(false)
        private set

    fun editUsername(value: String) { if (!busy) { username = value.take(128); pending = false } }
    fun editPassword(value: String) { if (!busy) { password = value.take(1024); pending = false } }
    fun setRemember(context: Context, value: Boolean) {
        if (busy) return
        remember = value
        if (!value) storage(context) { delete(); "已关闭账号保存并删除加密记录。" }
    }

    fun load(context: Context) = storage(context) {
        val account = load()
        main.post {
            username = account?.username ?: ""
            password = account?.password ?: ""
            remember = account != null
            pending = false
        }
        if (account == null) "没有已保存的账号。" else "已读取加密账号，请主动查询。"
    }

    fun forget(context: Context) = storage(context) {
        delete()
        client?.callAttr("clear")
        main.post { username = ""; password = ""; remember = false; pending = false }
        "账号、密码和会话已清除。"
    }

    private fun storage(context: Context, operation: SecureAccountStore.() -> String) {
        if (busy) return
        busy = true
        val app = context.applicationContext
        executor.execute {
            val text = try { SecureAccountStore(app).operation() } catch (_: Exception) {
                "账号安全存储不可用，请重新输入或清除已保存账号。"
            }
            main.post { result = text; busy = false }
        }
    }

    fun run(context: Context, operation: String, confirmed: Boolean = false) {
        if (busy || username.isBlank() || password.isEmpty()) return
        if (operation == "checkin" && (!confirmed || !pending)) return
        val user = username.trim()
        val secret = password
        val save = remember
        val app = context.applicationContext
        busy = true
        pending = false
        result = if (operation == "checkin") "正在提交并确认服务端状态，请勿重复操作。" else "正在查询，请按提示填写验证码。"
        captcha.begin()
        executor.execute {
            val response = try {
                if (save && !synthetic) SecureAccountStore(app).save(Account(user, secret))
                val active = client ?: PythonRuntime.instance(app).getModule("android_client")
                    .get("AndroidClient")!!.call(captcha, File(app.noBackupFilesDir, "manual-checkin.lock").absolutePath)
                    .also { client = it }
                JSONObject(active.callAttr("run", operation, user, secret, confirmed).toString())
            } catch (_: AccountStorageException) {
                JSONObject().put("error", "storage_failed")
            } catch (_: Exception) {
                JSONObject().put("error", "operation_failed")
            }
            main.post {
                pending = !captcha.isCancelled() && response.optString("status") == "probe_pending"
                result = render(response)
                busy = false
            }
        }
    }

    private fun render(value: JSONObject): String {
        if (value.has("error")) return when (value.optString("error")) {
            "cancelled" -> "操作已取消。如果已发出提交请求，请刷新查询服务端状态。"
            "busy" -> "已有操作正在运行，请稍后查询。"
            "confirmation_required" -> "请先查询，再确认手动签到。"
            "storage_failed" -> "加密保存失败，本次操作已停止。可关闭保存后重新输入。"
            else -> "操作失败，请检查网络和账号后重新查询。"
        }
        if (value.optString("mode") == "diagnose") {
            val checks = value.optJSONObject("checks") ?: return "诊断结果异常。"
            return listOf("authentication" to "登录", "leave_policy" to "请假数据", "student_profile" to "账号身份",
                "dormitory_schema" to "宿舍数据", "checkin_api" to "签到查询").joinToString("\n") {
                "${it.second}：${if (checks.optBoolean(it.first)) "通过" else "未通过"}"
            }
        }
        // Do not display arbitrary Python/server messages in the account UI.
        return when (value.optString("status")) {
            "probe_pending" -> "今日待签到。确认本人在寝后，可手动提交。"
            "success" -> "签到成功，服务端已确认。"
            "already_checked_in" -> "今日已签到。"
            "on_leave" -> "请假期间无需签到。"
            "no_task" -> "今日暂无签到任务，请在规定时间内再查询。"
            "login_failed" -> "登录失败，请检查账号、密码和验证码。"
            else -> "网络或数据异常，请稍后查询；已提交时请先确认服务端状态。"
        }
    }

    fun cancel() { captcha.cancel() }

    /** Called only by the debug instrumentation helper; production has no hook. */
    internal fun useSyntheticClient(value: PyObject?) {
        check(!busy)
        client = value
        synthetic = value != null
        username = ""; password = ""; remember = false; pending = false
        result = "输入校园账号后，先查询今日状态。"
    }
}
