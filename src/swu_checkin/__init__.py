"""SWU 查寝打卡模块"""

from .check_in import check_in
from .models import CheckinResult
from .service import run_checkin, run_probe

__version__ = "1.1.1"
__all__ = ["CheckinResult", "check_in", "run_checkin", "run_probe"]
