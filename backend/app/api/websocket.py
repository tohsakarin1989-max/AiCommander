"""
WebSocket实时通信API
用于实时指挥大屏的数据推送和会议进度推送
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import List, Dict, Optional
import json
import asyncio
from datetime import datetime, timedelta
from app.utils.logger import logger
from app.database import SessionLocal
from app.models.case import Case
from sqlalchemy.orm import Session


router = APIRouter()


class ConnectionManager:
    """WebSocket连接管理器"""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """接受新的WebSocket连接"""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"新的WebSocket连接，当前连接数: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """断开WebSocket连接"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"WebSocket连接断开，当前连接数: {len(self.active_connections)}")

    async def broadcast(self, message: Dict):
        """向所有连接的客户端广播消息"""
        if not self.active_connections:
            return

        message_str = json.dumps(message, ensure_ascii=False, default=str)
        disconnected = []

        for connection in self.active_connections:
            try:
                await connection.send_text(message_str)
            except Exception as e:
                logger.error(f"发送WebSocket消息失败: {e}")
                disconnected.append(connection)

        # 清理断开的连接
        for conn in disconnected:
            self.disconnect(conn)

    async def send_personal_message(self, message: Dict, websocket: WebSocket):
        """向特定客户端发送消息"""
        try:
            message_str = json.dumps(message, ensure_ascii=False, default=str)
            await websocket.send_text(message_str)
        except Exception as e:
            logger.error(f"发送个人消息失败: {e}")


class MeetingConnectionManager:
    """会议WebSocket连接管理器 - 按会议ID分组管理连接"""

    def __init__(self):
        # {meeting_id: [WebSocket, ...]}
        self.meeting_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, meeting_id: str):
        """接受新的会议WebSocket连接"""
        await websocket.accept()
        if meeting_id not in self.meeting_connections:
            self.meeting_connections[meeting_id] = []
        self.meeting_connections[meeting_id].append(websocket)
        logger.info(f"会议 {meeting_id} 新连接，当前该会议连接数: {len(self.meeting_connections[meeting_id])}")

    def disconnect(self, websocket: WebSocket, meeting_id: str):
        """断开会议WebSocket连接"""
        if meeting_id in self.meeting_connections:
            if websocket in self.meeting_connections[meeting_id]:
                self.meeting_connections[meeting_id].remove(websocket)
            if not self.meeting_connections[meeting_id]:
                del self.meeting_connections[meeting_id]
        logger.info(f"会议 {meeting_id} 连接断开")

    async def broadcast_to_meeting(self, meeting_id: str, message: Dict):
        """向特定会议的所有连接广播消息"""
        if meeting_id not in self.meeting_connections:
            return

        message_str = json.dumps(message, ensure_ascii=False, default=str)
        disconnected = []

        for connection in self.meeting_connections[meeting_id]:
            try:
                await connection.send_text(message_str)
            except Exception as e:
                logger.error(f"发送会议消息失败: {e}")
                disconnected.append(connection)

        # 清理断开的连接
        for conn in disconnected:
            self.disconnect(conn, meeting_id)

    async def send_personal_message(self, message: Dict, websocket: WebSocket):
        """向特定客户端发送消息"""
        try:
            message_str = json.dumps(message, ensure_ascii=False, default=str)
            await websocket.send_text(message_str)
        except Exception as e:
            logger.error(f"发送个人消息失败: {e}")

    def get_connection_count(self, meeting_id: str) -> int:
        """获取会议连接数"""
        return len(self.meeting_connections.get(meeting_id, []))


manager = ConnectionManager()
meeting_manager = MeetingConnectionManager()


async def broadcast_meeting_progress(meeting_id: str, stage: int, stage_name: str,
                                     status: str, progress: int,
                                     details: Optional[Dict] = None):
    """广播会议进度更新"""
    message = {
        "type": "meeting_progress",
        "meeting_id": meeting_id,
        "timestamp": datetime.now().isoformat(),
        "data": {
            "stage": stage,
            "stage_name": stage_name,
            "status": status,  # 'started', 'running', 'completed', 'failed'
            "progress": progress,  # 0-100
            "details": details or {}
        }
    }
    await meeting_manager.broadcast_to_meeting(meeting_id, message)


@router.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket):
    """
    实时指挥大屏WebSocket端点
    推送案件、警力位置等实时数据
    """
    await manager.connect(websocket)
    
    try:
        # 发送初始数据
        await send_initial_data(websocket)
        
        # 保持连接并定期推送更新
        while True:
            # 等待客户端消息（心跳或请求）
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                # 处理客户端消息（如果需要）
                message = json.loads(data)
                if message.get("type") == "ping":
                    await manager.send_personal_message({"type": "pong"}, websocket)
            except asyncio.TimeoutError:
                # 超时，发送心跳
                await manager.send_personal_message({"type": "heartbeat"}, websocket)
            except WebSocketDisconnect:
                break
            
            # 定期推送数据更新（每5秒）
            await asyncio.sleep(5)
            await send_dashboard_update(websocket)
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket错误: {e}")
        manager.disconnect(websocket)


async def send_initial_data(websocket: WebSocket):
    """发送初始数据"""
    db = SessionLocal()
    try:
        # 获取最近的案件
        recent_cases = db.query(Case).filter(
            Case.latitude.isnot(None),
            Case.longitude.isnot(None)
        ).order_by(Case.occurred_time.desc()).limit(50).all()
        
        cases_data = [
            {
                "id": c.id,
                "case_number": c.case_number,
                "occurred_time": c.occurred_time.isoformat() if c.occurred_time else None,
                "latitude": c.latitude,
                "longitude": c.longitude,
                "location": c.location,
                "case_type": c.case_type,
                "status": c.status
            }
            for c in recent_cases
        ]
        
        # 统计信息
        total_cases = db.query(Case).count()
        today_cases = db.query(Case).filter(
            Case.occurred_time >= datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        ).count()
        
        await manager.send_personal_message({
            "type": "initial_data",
            "timestamp": datetime.now().isoformat(),
            "data": {
                "cases": cases_data,
                "statistics": {
                    "total_cases": total_cases,
                    "today_cases": today_cases
                }
            }
        }, websocket)
    finally:
        db.close()


async def send_dashboard_update(websocket: WebSocket):
    """发送数据更新"""
    db = SessionLocal()
    try:
        # 获取最新案件（最近1小时）
        one_hour_ago = datetime.now() - timedelta(hours=1)
        new_cases = db.query(Case).filter(
            Case.latitude.isnot(None),
            Case.longitude.isnot(None),
            Case.occurred_time >= one_hour_ago
        ).order_by(Case.occurred_time.desc()).all()
        
        if new_cases:
            cases_data = [
                {
                    "id": c.id,
                    "case_number": c.case_number,
                    "occurred_time": c.occurred_time.isoformat() if c.occurred_time else None,
                    "latitude": c.latitude,
                    "longitude": c.longitude,
                    "location": c.location,
                    "case_type": c.case_type,
                    "status": c.status
                }
                for c in new_cases
            ]
            
            await manager.send_personal_message({
                "type": "update",
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "new_cases": cases_data
                }
            }, websocket)
    finally:
        db.close()


@router.websocket("/ws/meeting/{meeting_id}")
async def websocket_meeting(websocket: WebSocket, meeting_id: str):
    """
    会议进度WebSocket端点
    推送会议各阶段的进度信息
    """
    await meeting_manager.connect(websocket, meeting_id)

    try:
        # 发送连接确认
        await meeting_manager.send_personal_message({
            "type": "connected",
            "meeting_id": meeting_id,
            "timestamp": datetime.now().isoformat(),
            "message": f"已连接到会议 {meeting_id} 的进度通道"
        }, websocket)

        # 获取当前会议状态
        await send_meeting_status(websocket, meeting_id)

        # 保持连接
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=60.0)
                message = json.loads(data)
                if message.get("type") == "ping":
                    await meeting_manager.send_personal_message({"type": "pong"}, websocket)
                elif message.get("type") == "get_status":
                    await send_meeting_status(websocket, meeting_id)
            except asyncio.TimeoutError:
                # 发送心跳
                await meeting_manager.send_personal_message({"type": "heartbeat"}, websocket)
            except WebSocketDisconnect:
                break

    except WebSocketDisconnect:
        meeting_manager.disconnect(websocket, meeting_id)
    except Exception as e:
        logger.error(f"会议WebSocket错误: {e}")
        meeting_manager.disconnect(websocket, meeting_id)


async def send_meeting_status(websocket: WebSocket, meeting_id: str):
    """发送会议当前状态"""
    db = SessionLocal()
    try:
        from app.models.meeting import Meeting
        meeting = db.query(Meeting).filter(Meeting.meeting_id == meeting_id).first()
        if meeting:
            await meeting_manager.send_personal_message({
                "type": "meeting_status",
                "meeting_id": meeting_id,
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "status": meeting.status,
                    "created_at": meeting.created_at.isoformat() if meeting.created_at else None,
                    "completed_at": meeting.completed_at.isoformat() if meeting.completed_at else None,
                }
            }, websocket)
        else:
            await meeting_manager.send_personal_message({
                "type": "error",
                "message": f"会议 {meeting_id} 不存在"
            }, websocket)
    finally:
        db.close()


@router.post("/ws/broadcast")
async def broadcast_message(message: Dict):
    """
    广播消息到所有连接的客户端
    用于后端主动推送事件（如新案件、警力位置更新等）
    """
    await manager.broadcast(message)
    return {"status": "broadcasted", "connections": len(manager.active_connections)}


@router.post("/ws/meeting/{meeting_id}/broadcast")
async def broadcast_meeting_message(meeting_id: str, message: Dict):
    """
    广播消息到特定会议的所有连接客户端
    """
    await meeting_manager.broadcast_to_meeting(meeting_id, message)
    return {
        "status": "broadcasted",
        "meeting_id": meeting_id,
        "connections": meeting_manager.get_connection_count(meeting_id)
    }



