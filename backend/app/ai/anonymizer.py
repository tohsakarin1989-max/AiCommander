import random
import copy

class Anonymizer:
    """匿名化处理模块 - 确保LLM在评价时无法识别其他模型身份"""
    
    @staticmethod
    def anonymize(analysis: dict, index: int) -> dict:
        """
        匿名化分析结果
        移除所有可能暴露模型身份的信息，并打乱顺序
        """
        # 深拷贝避免修改原始数据
        anonymized = copy.deepcopy(analysis)
        
        # 移除可能暴露模型身份的字段
        anonymized.pop("model_id", None)
        anonymized.pop("model_name", None)
        anonymized.pop("analyst_name", None)
        anonymized.pop("specialty", None)
        
        # 如果结果中有任何可能暴露身份的文本，进行清理
        if "raw_content" in anonymized:
            # 移除可能包含模型名称的内容
            content = anonymized.get("raw_content", "")
            if isinstance(content, str):
                # 移除常见的模型标识词
                for marker in ["GPT", "Claude", "Gemini", "Grok", "模型", "Model"]:
                    content = content.replace(marker, "[模型]")
                anonymized["raw_content"] = content
        
        # 添加匿名标识（仅用于追踪，不暴露真实身份）
        anonymized["_anonymous_id"] = f"Response_{index + 1}"
        
        return anonymized
    
    @staticmethod
    def distribute_for_review(
        analyses: list,
        evaluator_index: int
    ) -> list:
        """
        为评价者分发匿名分析结果（排除自己的）
        打乱顺序，确保无法通过位置推断身份
        """
        # 获取其他分析员的结果并匿名化
        other_analyses = [
            Anonymizer.anonymize(analyses[i], i)
            for i in range(len(analyses))
            if i != evaluator_index
        ]
        
        # 打乱顺序，确保无法通过位置推断
        shuffled = copy.deepcopy(other_analyses)
        random.shuffle(shuffled)
        
        return shuffled
    
    @staticmethod
    def create_anonymous_batch(analyses: list) -> list:
        """
        创建完全匿名的批次（用于排名阶段）
        所有分析结果都被匿名化并打乱顺序
        """
        anonymized = [
            Anonymizer.anonymize(analysis, i)
            for i, analysis in enumerate(analyses)
        ]
        shuffled = copy.deepcopy(anonymized)
        random.shuffle(shuffled)
        return shuffled

