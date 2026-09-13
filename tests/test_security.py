"""
安全性测试：确保敏感信息不会泄露到日志
"""
import os
import sys
from io import StringIO
from unittest.mock import patch

# 确保 SWUDK_DEBUG_CREDENTIALS 未设置（模拟生产环境）
os.environ.pop('SWUDK_DEBUG_CREDENTIALS', None)


def test_no_token_in_normal_output():
    """测试：正常模式下不输出 token"""
    from swu_checkin.get_info import safe_print
    
    # 捕获标准输出
    captured_output = StringIO()
    sys.stdout = captured_output
    
    # 模拟包含 token 的日志
    safe_print("获取到 token: abc123xyz", ["token"])
    safe_print("这是普通日志")
    
    sys.stdout = sys.__stdout__
    output = captured_output.getvalue()
    
    # 验证：包含 token 的行不应该被输出
    assert "token" not in output.lower()
    assert "abc123xyz" not in output
    # 验证：普通日志应该正常输出
    assert "普通日志" in output
    print("[PASS] 测试通过：正常模式下不输出包含 token 的日志")


def test_mask_sensitive_data():
    """测试：敏感数据脱敏功能"""
    from swu_checkin.get_info import mask_sensitive_data
    
    # 测试长字符串脱敏
    token = "abcdefghijklmnopqrstuvwxyz123456"
    masked = mask_sensitive_data(token, show_chars=4)
    assert masked.startswith("ab")
    assert masked.endswith("56")
    assert "*" in masked
    assert "cdefghijklmnopqrstuvwxyz1234" not in masked  # 中间部分被隐藏
    print(f"[PASS] 长字符串脱敏: {token} -> {masked}")
    
    # 测试短字符串脱敏
    short_token = "abc"
    masked_short = mask_sensitive_data(short_token, show_chars=4)
    assert masked_short == "****"
    print(f"[PASS] 短字符串脱敏: {short_token} -> {masked_short}")
    
    # 测试空字符串
    empty = ""
    masked_empty = mask_sensitive_data(empty)
    assert masked_empty == "****"
    print(f"[PASS] 空字符串脱敏: (空) -> {masked_empty}")
    
    # 测试实际 token 格式
    jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ"
    masked_jwt = mask_sensitive_data(jwt_token, show_chars=8)
    assert masked_jwt.startswith("eyJh")
    assert masked_jwt.endswith("IyfQ")  # 实际的最后4个字符
    assert "*" in masked_jwt
    # 确保敏感部分被隐藏
    assert "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4" not in masked_jwt
    print(f"[PASS] JWT token 脱敏: {jwt_token[:20]}... -> {masked_jwt[:20]}...")


def test_debug_mode_behavior():
    """测试：调试模式行为"""
    from swu_checkin.get_info import debug_print
    
    # 捕获标准输出
    captured_output = StringIO()
    sys.stdout = captured_output
    
    # 在非调试模式下，debug_print 不应输出
    debug_print("这是调试信息")
    
    sys.stdout = sys.__stdout__
    output = captured_output.getvalue()
    
    # 验证：非调试模式下不输出
    assert output == ""
    print("[PASS] 测试通过：非调试模式下 debug_print 不输出")


def test_debug_mode_enabled():
    """测试：启用调试模式后的行为"""
    # 临时启用调试模式
    os.environ['SWUDK_DEBUG_CREDENTIALS'] = '1'
    
    # 重新导入以应用新的环境变量
    import importlib
    import swu_checkin.get_info
    importlib.reload(swu_checkin.get_info)
    from swu_checkin.get_info import debug_print
    
    # 捕获标准输出
    captured_output = StringIO()
    sys.stdout = captured_output
    
    debug_print("调试信息：token=abc123")
    
    sys.stdout = sys.__stdout__
    output = captured_output.getvalue()
    
    # 验证：调试模式下应输出
    assert "[DEBUG]" in output
    assert "token=abc123" in output
    print("[PASS] 测试通过：调试模式下 debug_print 正常输出")
    
    # 清理：关闭调试模式
    os.environ.pop('SWUDK_DEBUG_CREDENTIALS', None)


def test_github_actions_safety():
    """测试：模拟 GitHub Actions 环境，确保不泄露敏感信息"""
    # 模拟 GitHub Actions 环境
    os.environ.pop('SWUDK_DEBUG_CREDENTIALS', None)
    
    from swu_checkin.get_info import safe_print, mask_sensitive_data
    
    # 捕获标准输出
    captured_output = StringIO()
    sys.stdout = captured_output
    
    # 模拟登录流程中的日志
    fake_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test"
    fake_username = "20211234567"
    
    safe_print(f"用户: {mask_sensitive_data(fake_username, 4)}", [])
    safe_print(f"获取 token: {fake_token}", ["token"])  # 应该被过滤
    safe_print("签到任务获取成功", [])
    
    sys.stdout = sys.__stdout__
    output = captured_output.getvalue()
    
    # 验证
    assert "20**567" in output or "****" in output  # 脱敏后的用户名
    assert fake_token not in output  # 完整 token 不应出现
    assert "签到任务获取成功" in output  # 普通日志正常
    
    print("[PASS] 测试通过：GitHub Actions 环境下不泄露敏感信息")


if __name__ == "__main__":
    print("=" * 60)
    print("开始安全性测试")
    print("=" * 60)
    print()
    
    test_mask_sensitive_data()
    print()
    
    test_no_token_in_normal_output()
    print()
    
    test_debug_mode_behavior()
    print()
    
    test_debug_mode_enabled()
    print()
    
    test_github_actions_safety()
    print()
    
    print("=" * 60)
    print("[SUCCESS] 所有安全性测试通过")
    print("=" * 60)
