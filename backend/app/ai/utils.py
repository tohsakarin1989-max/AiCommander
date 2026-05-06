"""AI 模块通用工具函数"""
import json
from typing import Any, Dict, Optional, Tuple


def parse_llm_json_response(
    content: str,
    default_value: Optional[Dict] = None
) -> Tuple[Dict, Optional[str]]:
    """
    解析 LLM 返回的 JSON 内容

    支持处理 ```json``` 代码块包裹的 JSON

    Args:
        content: LLM 返回的原始内容
        default_value: 解析失败时返回的默认值

    Returns:
        (解析结果, 错误信息)
        如果解析成功，错误信息为 None
    """
    if default_value is None:
        default_value = {}

    try:
        # 提取 JSON 内容
        json_str = extract_json_from_response(content)
        return json.loads(json_str), None
    except Exception as e:
        return default_value.copy(), str(e)


def extract_json_from_response(content: str) -> str:
    """
    从 LLM 响应中提取 JSON 字符串

    Args:
        content: LLM 返回的原始内容

    Returns:
        提取后的 JSON 字符串
    """
    if "```json" in content:
        return content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        return content.split("```")[1].split("```")[0].strip()
    return content.strip()
