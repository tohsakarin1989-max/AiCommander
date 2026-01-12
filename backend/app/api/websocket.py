"""
WebSocket实时通信API
用于实时指挥大屏的数据推送
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import List, Dict
import json
import asyncio
from datetime import datetime
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


manager = ConnectionManager()


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


@router.post("/ws/broadcast")
async def broadcast_message(message: Dict):
    """
    广播消息到所有连接的客户端
    用于后端主动推送事件（如新案件、警力位置更新等）
    """
    await manager.broadcast(message)
    return {"status": "broadcasted", "connections": len(manager.active_connections)}



