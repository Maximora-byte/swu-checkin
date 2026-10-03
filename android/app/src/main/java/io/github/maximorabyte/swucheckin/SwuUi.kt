package io.github.maximorabyte.swucheckin

import androidx.annotation.DrawableRes
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusDirection
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp

@Composable
internal fun SwuIcon(@DrawableRes resource: Int, description: String? = null,
    modifier: Modifier = Modifier.size(22.dp), tint: Color = LocalContentColor.current) {
    Icon(painterResource(resource), contentDescription = description, modifier = modifier, tint = tint)
}

@Composable
internal fun SwuCard(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Surface(modifier.fillMaxWidth(), shape = RoundedCornerShape(24.dp),
        color = MaterialTheme.colorScheme.surface,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.65f))) {
        Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp), content = content)
    }
}

@Composable
internal fun PageHeading(title: String, subtitle: String, onBack: (() -> Unit)? = null) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        if (onBack != null) IconButton(onClick = onBack) {
            SwuIcon(R.drawable.ic_arrow_back, "返回查寝")
        }
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            Text(title, style = MaterialTheme.typography.titleLarge)
            Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

internal data class CheckinUiState(
    val username: String, val password: String, val rememberAccount: Boolean,
    val busy: Boolean, val pending: Boolean, val result: String,
)

internal data class CheckinUiActions(
    val editUsername: (String) -> Unit, val editPassword: (String) -> Unit,
    val rememberAccount: (Boolean) -> Unit, val load: () -> Unit, val forget: () -> Unit,
    val query: () -> Unit, val checkin: () -> Unit, val diagnose: () -> Unit,
    val cancel: () -> Unit, val environment: () -> Unit, val usage: () -> Unit,
)

@Composable
internal fun CheckinScreen(state: CheckinUiState, actions: CheckinUiActions, previewNotice: String? = null) {
    val colors = MaterialTheme.colorScheme
    val ready = !state.busy && state.username.isNotBlank() && state.password.isNotEmpty()
    val focus = LocalFocusManager.current
    val keyboard = LocalSoftwareKeyboardController.current
    var revealPassword by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxSize().safeDrawingPadding().imePadding().verticalScroll(rememberScrollState())
        .padding(horizontal = 20.dp, vertical = 18.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        if (previewNotice != null) Text(previewNotice, style = MaterialTheme.typography.bodySmall, color = colors.onSurfaceVariant)
        Surface(shape = RoundedCornerShape(28.dp), color = Color.Transparent) {
            Row(Modifier.fillMaxWidth().background(Brush.linearGradient(listOf(Color(0xFF183D32), Color(0xFF35664B))))
                .padding(22.dp), verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(7.dp)) {
                    Text("SWU 查寝", style = MaterialTheme.typography.bodySmall, color = Color(0xFFCEE3D3))
                    Text("今日查寝", style = MaterialTheme.typography.headlineMedium, color = Color.White)
                    Text("先查询，再安心确认。", style = MaterialTheme.typography.bodyMedium, color = Color(0xFFDCEADF))
                }
                Image(painterResource(R.drawable.ic_swu_mark), contentDescription = null,
                    modifier = Modifier.size(72.dp).graphicsLayer(scaleX = 1.4f, scaleY = 1.4f))
            }
        }
        StatusCard(state)
        SwuCard {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                SwuIcon(R.drawable.ic_person, tint = colors.primary)
                Text("校园账号", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                SwuIcon(R.drawable.ic_shield, "支持本设备加密保存", tint = colors.onSurfaceVariant)
            }
            OutlinedTextField(value = state.username, onValueChange = actions.editUsername, enabled = !state.busy,
                label = { Text("校园账号") }, singleLine = true,
                leadingIcon = { SwuIcon(R.drawable.ic_person) },
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
                keyboardActions = KeyboardActions(onNext = { focus.moveFocus(FocusDirection.Down) }),
                shape = RoundedCornerShape(14.dp), modifier = Modifier.fillMaxWidth().testTag("username"))
            OutlinedTextField(value = state.password, onValueChange = actions.editPassword, enabled = !state.busy,
                label = { Text("密码") }, singleLine = true,
                leadingIcon = { SwuIcon(R.drawable.ic_lock) },
                trailingIcon = { IconButton(enabled = !state.busy, onClick = { revealPassword = !revealPassword }) {
                    SwuIcon(if (revealPassword) R.drawable.ic_eye_off else R.drawable.ic_eye,
                        if (revealPassword) "隐藏密码" else "显示密码")
                } },
                visualTransformation = if (revealPassword) VisualTransformation.None else PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = { keyboard?.hide(); focus.clearFocus() }),
                shape = RoundedCornerShape(14.dp), modifier = Modifier.fillMaxWidth().testTag("password"))
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Column(Modifier.weight(1f)) {
                    Text("记住账号", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium)
                    Text("仅在此设备加密保存", style = MaterialTheme.typography.bodySmall, color = colors.onSurfaceVariant)
                }
                Switch(checked = state.rememberAccount, onCheckedChange = actions.rememberAccount,
                    enabled = !state.busy, modifier = Modifier.testTag("remember-account"))
            }
            HorizontalDivider(color = colors.outlineVariant)
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                TextButton(enabled = !state.busy, onClick = { revealPassword = false; actions.load() }, modifier = Modifier.weight(1f)) {
                    SwuIcon(R.drawable.ic_restore, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(6.dp)); Text("读取账号", style = MaterialTheme.typography.bodySmall)
                }
                TextButton(enabled = !state.busy, onClick = { revealPassword = false; actions.forget() }, modifier = Modifier.weight(1f)) {
                    SwuIcon(R.drawable.ic_trash, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(6.dp)); Text("清除账号", style = MaterialTheme.typography.bodySmall)
                }
            }
        }
        SwuCard {
            Button(enabled = ready, modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp), onClick = {
                revealPassword = false; keyboard?.hide(); focus.clearFocus(); actions.query()
            }) {
                SwuIcon(R.drawable.ic_search); Spacer(Modifier.width(8.dp)); Text("查询今日状态")
            }
            OutlinedButton(enabled = ready && state.pending, modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = colors.primary),
                border = BorderStroke(1.dp, if (ready && state.pending) colors.primary.copy(alpha = 0.65f) else colors.outlineVariant),
                onClick = { keyboard?.hide(); focus.clearFocus(); actions.checkin() }) {
                SwuIcon(R.drawable.ic_check); Spacer(Modifier.width(8.dp)); Text("手动签到")
            }
            if (state.busy) TextButton(onClick = actions.cancel, modifier = Modifier.align(Alignment.CenterHorizontally)) {
                SwuIcon(R.drawable.ic_close, modifier = Modifier.size(18.dp)); Spacer(Modifier.width(6.dp)); Text("取消操作")
            }
            Text("查询不会提交签到。手动签到需要你再次确认。", style = MaterialTheme.typography.bodySmall,
                color = colors.onSurfaceVariant)
        }
        SwuCard {
            Text("帮助与检测", style = MaterialTheme.typography.titleMedium)
            UtilityAction(R.drawable.ic_tools, "只读诊断", "检查登录与学校接口，不提交签到", ready, actions.diagnose)
            HorizontalDivider(color = colors.outlineVariant)
            UtilityAction(R.drawable.ic_device, "运行环境检测", "排查本地运行和公共网络连接", !state.busy, actions.environment)
        }
        TextButton(onClick = actions.usage, modifier = Modifier.align(Alignment.CenterHorizontally)) {
            SwuIcon(R.drawable.ic_info, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(6.dp)); Text("使用前请确认本人在寝", style = MaterialTheme.typography.bodySmall)
        }
        Spacer(Modifier.height(8.dp))
    }
}

@Composable
private fun StatusCard(state: CheckinUiState) {
    val colors = MaterialTheme.colorScheme
    val complete = state.result == "签到成功，服务端已确认。" || state.result == "今日已签到。"
    val failure = state.result.startsWith("登录失败") || state.result.startsWith("操作失败") ||
        state.result.startsWith("网络或数据异常") || state.result.startsWith("加密保存失败")
    val title = when {
        state.busy -> "正在处理中"
        state.pending -> "今日待签到"
        complete -> "今日已完成"
        state.result == "请假期间无需签到。" -> "请假期间"
        state.result.startsWith("今日暂无签到任务") -> "暂无签到任务"
        failure -> "请检查后重试"
        else -> "等待查询"
    }
    val icon = if (complete) R.drawable.ic_check else if (failure) R.drawable.ic_info else R.drawable.ic_clock
    val accent = if (failure) colors.error else if (state.pending) colors.tertiary else colors.primary
    val background = if (failure) colors.errorContainer else if (state.pending) colors.tertiaryContainer else colors.primaryContainer
    SwuCard {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            Box(Modifier.size(46.dp).clip(RoundedCornerShape(16.dp)).background(background), contentAlignment = Alignment.Center) {
                if (state.busy) CircularProgressIndicator(Modifier.size(22.dp), color = accent, strokeWidth = 2.dp)
                else SwuIcon(icon, tint = accent)
            }
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                Text("今日状态", style = MaterialTheme.typography.bodySmall, color = colors.onSurfaceVariant)
                Text(title, style = MaterialTheme.typography.titleMedium)
            }
        }
        Text(state.result, style = MaterialTheme.typography.bodyMedium, color = colors.onSurfaceVariant,
            modifier = Modifier.testTag("result"))
    }
}

@Composable
internal fun UtilityAction(@DrawableRes icon: Int, title: String, subtitle: String,
    enabled: Boolean = true, onClick: () -> Unit) {
    TextButton(enabled = enabled, onClick = onClick, modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(horizontal = 0.dp, vertical = 8.dp)) {
        SwuIcon(icon); Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            Text(subtitle, style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = if (enabled) 1f else 0.6f))
        }
        SwuIcon(R.drawable.ic_chevron_right, modifier = Modifier.size(18.dp))
    }
}
