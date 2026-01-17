"""
圆桌会议管理器测试
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.orm import Session

from app.ai.meeting_manager import MeetingManager
from app.ai.anonymizer import Anonymizer


class TestAnonymizer:
    """匿名化处理器测试"""

    def test_create_anonymous_batch_removes_identity(self):
        """匿名化应移除身份信息"""
        analyses = [
            {"model_id": 1, "model_name": "GPT-4", "content": "分析结果1"},
            {"model_id": 2, "model_name": "Claude", "content": "分析结果2"},
        ]

        anonymizer = Anonymizer()
        batch = anonymizer.create_anonymous_batch(analyses)

        for item in batch:
            assert "model_id" not in item or item.get("model_id") is None
            assert "model_name" not in item or item.get("model_name") is None

    def test_create_anonymous_batch_assigns_ids(self):
        """匿名化应分配匿名 ID"""
        analyses = [{"content": "分析1"}, {"content": "分析2"}]

        anonymizer = Anonymizer()
        batch = anonymizer.create_anonymous_batch(analyses)

        ids = [item.get("_anonymous_id") for item in batch]
        assert len(set(ids)) == len(ids)  # ID 应唯一


class TestMeetingManager:
    """会议管理器测试"""

    def test_init(self):
        """初始化测试"""
        db = MagicMock(spec=Session)
        manager = MeetingManager(db)

        assert manager.db == db
        assert manager.meeting_id is None
        assert manager.moderator is None
        assert manager.analysts == []

    @pytest.mark.asyncio
    async def test_stage_1_parallel_execution(self):
        """第一阶段应并行执行所有分析员"""
        db = MagicMock(spec=Session)
        manager = MeetingManager(db)

        # 模拟分析员
        mock_analysts = []
        for i in range(3):
            analyst = MagicMock()
            analyst.analyze_cases = AsyncMock(return_value={"analyst": i, "result": f"分析{i}"})
            mock_analysts.append(analyst)

        manager.analysts = mock_analysts

        results = await manager.conduct_stage_1_first_opinions("案件信息")

        # 验证所有分析员都被调用
        assert len(results) == 3
        for analyst in mock_analysts:
            analyst.analyze_cases.assert_called_once_with("案件信息")

    @pytest.mark.asyncio
    async def test_stage_2_parallel_execution(self):
        """第二阶段应并行执行所有排名任务"""
        db = MagicMock(spec=Session)
        manager = MeetingManager(db)

        # 模拟分析员
        mock_analysts = []
        for i in range(3):
            analyst = MagicMock()
            analyst.rank_analyses = AsyncMock(
                return_value={"rankings": [{"anonymous_id": f"R{j}", "score": 8} for j in range(2)]}
            )
            mock_analysts.append(analyst)

        manager.analysts = mock_analysts

        # 准备分析结果
        analyses = [
            {"_anonymous_id": f"Response_{i+1}", "content": f"分析{i}"}
            for i in range(3)
        ]

        results = await manager.conduct_stage_2_review_and_rank(analyses)

        # 验证所有分析员都执行了排名
        assert len(results) == 3
        for analyst in mock_analysts:
            analyst.rank_analyses.assert_called_once()

    def test_aggregate_rankings_empty(self):
        """空排名列表应返回空聚合结果"""
        db = MagicMock(spec=Session)
        manager = MeetingManager(db)

        result = manager._aggregate_rankings([], [])
        assert result["rankings"] == {}

    def test_aggregate_rankings_calculates_average(self):
        """排名聚合应计算平均分"""
        db = MagicMock(spec=Session)
        manager = MeetingManager(db)

        original_analyses = [
            {"_anonymous_id": "Response_1"},
            {"_anonymous_id": "Response_2"},
        ]

        rankings = [
            {
                "rankings": [
                    {"anonymous_id": "Response_1", "score": 8, "rank": 1},
                    {"anonymous_id": "Response_2", "score": 6, "rank": 2},
                ]
            },
            {
                "rankings": [
                    {"anonymous_id": "Response_1", "score": 9, "rank": 1},
                    {"anonymous_id": "Response_2", "score": 7, "rank": 2},
                ]
            },
        ]

        result = manager._aggregate_rankings(rankings, original_analyses)

        # Response_1 平均分应为 (8+9)/2 = 8.5
        assert result["rankings"][0]["average_score"] == 8.5
        # Response_2 平均分应为 (6+7)/2 = 6.5
        assert result["rankings"][1]["average_score"] == 6.5

    def test_aggregate_rankings_handles_missing_votes(self):
        """聚合应处理缺失的评价"""
        db = MagicMock(spec=Session)
        manager = MeetingManager(db)

        original_analyses = [
            {"_anonymous_id": "Response_1"},
            {"_anonymous_id": "Response_2"},
        ]

        # 只有一个评价者对 Response_2 评分
        rankings = [
            {"rankings": [{"anonymous_id": "Response_1", "score": 8, "rank": 1}]},
            {
                "rankings": [
                    {"anonymous_id": "Response_1", "score": 9, "rank": 1},
                    {"anonymous_id": "Response_2", "score": 7, "rank": 2},
                ]
            },
        ]

        result = manager._aggregate_rankings(rankings, original_analyses)

        # Response_1 被评 2 次
        assert result["rankings"][0]["vote_count"] == 2
        # Response_2 只被评 1 次
        assert result["rankings"][1]["vote_count"] == 1
