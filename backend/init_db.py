"""
数据库初始化脚本
运行此脚本创建数据库表
"""
from app.database import engine, Base
from app.models import AIModel, Case, Meeting, MeetingConversation, AnalysisResult, Evaluation, Report

def init_db():
    """初始化数据库表"""
    print("创建数据库表...")
    Base.metadata.create_all(bind=engine)
    print("数据库表创建完成！")

if __name__ == "__main__":
    init_db()

