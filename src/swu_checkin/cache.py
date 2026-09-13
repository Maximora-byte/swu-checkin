"""会话上下文 - 在一次 action 中复用 token、学号、宿舍信息等"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class CheckinContext:
    """签到会话上下文，存储一次 action 中需要复用的数据"""
    
    # 认证信息
    token: Optional[str] = None
    
    # 学生信息
    student_id: Optional[str] = None
    
    # 宿舍信息
    dormitory_data: Optional[dict] = None
    building: Optional[str] = None
    room: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    
    # 签到任务信息
    transition: Optional[dict] = None
    
    def is_authenticated(self) -> bool:
        """是否已认证"""
        return self.token is not None
    
    def has_dormitory_info(self) -> bool:
        """是否已获取宿舍信息"""
        return all([
            self.building is not None,
            self.room is not None,
            self.latitude is not None,
            self.longitude is not None
        ])
    
    def has_student_id(self) -> bool:
        """是否已获取学号"""
        return self.student_id is not None
    
    def has_transition(self) -> bool:
        """是否已获取签到任务"""
        return self.transition is not None
