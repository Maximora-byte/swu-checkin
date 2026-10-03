package io.github.maximorabyte.swucheckin

import android.app.Activity
import androidx.core.view.WindowCompat
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

private val LightColors = lightColorScheme(
    primary = Color(0xFF245C47), onPrimary = Color.White,
    primaryContainer = Color(0xFFDDEEE3), onPrimaryContainer = Color(0xFF194632),
    secondary = Color(0xFF596E61), onSecondary = Color.White,
    secondaryContainer = Color(0xFFE6EEE7), onSecondaryContainer = Color(0xFF334D3D),
    tertiary = Color(0xFF8A652C), tertiaryContainer = Color(0xFFFFEDCE),
    onTertiaryContainer = Color(0xFF624819),
    background = Color(0xFFF3F6F2), onBackground = Color(0xFF1D3028),
    surface = Color(0xFFFFFEFB), onSurface = Color(0xFF1D3028),
    surfaceVariant = Color(0xFFEDF2EB), onSurfaceVariant = Color(0xFF657269),
    outline = Color(0xFF85968A), outlineVariant = Color(0xFFDDE5DC),
    error = Color(0xFFAD3E38), errorContainer = Color(0xFFFFE9E5),
    onErrorContainer = Color(0xFF7A2D28),
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFF9AD8B5), onPrimary = Color(0xFF173C29),
    primaryContainer = Color(0xFF284F3A), onPrimaryContainer = Color(0xFFD9EFDF),
    secondary = Color(0xFFB7CDBD), onSecondary = Color(0xFF263D2D),
    secondaryContainer = Color(0xFF2C4033), onSecondaryContainer = Color(0xFFDCE7DD),
    tertiary = Color(0xFFDFC394), tertiaryContainer = Color(0xFF4A3B22),
    onTertiaryContainer = Color(0xFFF4DEB6),
    background = Color(0xFF101B15), onBackground = Color(0xFFE1EAE0),
    surface = Color(0xFF19271E), onSurface = Color(0xFFE1EAE0),
    surfaceVariant = Color(0xFF223128), onSurfaceVariant = Color(0xFFB0BDB1),
    outline = Color(0xFF849587), outlineVariant = Color(0xFF34453A),
    error = Color(0xFFFFB4A8), errorContainer = Color(0xFF50302B),
    onErrorContainer = Color(0xFFFFDAD3),
)

private val SwuTypography = Typography(
    headlineMedium = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.Bold,
        fontSize = 28.sp, lineHeight = 36.sp),
    titleLarge = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.SemiBold,
        fontSize = 21.sp, lineHeight = 29.sp),
    titleMedium = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.SemiBold,
        fontSize = 17.sp, lineHeight = 25.sp),
    bodyLarge = TextStyle(fontFamily = FontFamily.SansSerif, fontSize = 15.sp, lineHeight = 23.sp),
    bodyMedium = TextStyle(fontFamily = FontFamily.SansSerif, fontSize = 14.sp, lineHeight = 22.sp),
    bodySmall = TextStyle(fontFamily = FontFamily.SansSerif, fontSize = 12.sp, lineHeight = 19.sp),
    labelLarge = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.Medium,
        fontSize = 15.sp, lineHeight = 22.sp),
)

@Composable
internal fun SwuTheme(darkTheme: Boolean = isSystemInDarkTheme(), content: @Composable () -> Unit) {
    val view = LocalView.current
    SideEffect {
        (view.context as? Activity)?.let { activity ->
            WindowCompat.getInsetsController(activity.window, view).apply {
                isAppearanceLightStatusBars = !darkTheme
                isAppearanceLightNavigationBars = !darkTheme
            }
        }
    }
    MaterialTheme(
        colorScheme = if (darkTheme) DarkColors else LightColors,
        typography = SwuTypography,
        shapes = Shapes(small = RoundedCornerShape(12.dp), medium = RoundedCornerShape(18.dp),
            large = RoundedCornerShape(26.dp), extraLarge = RoundedCornerShape(30.dp)),
        content = content,
    )
}
