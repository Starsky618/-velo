"""
v5 task-1.B.1：app/agent/segment_writer.py 单元测试。

mock OpenAI client 调用（不连真 DeepSeek API），覆盖 4 条路径：
1. 无 API key → 返空字符串
2. API 调用抛异常（5xx / 网络）→ 返空字符串
3. 正常成功路径 → 返 strip 后内容
4. 嵌套字段缺失（choices / message / content）→ 返空字符串
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import importlib

from app.agent import segment_writer


def _segment_props_sample() -> dict:
    """6 字段齐全的标准 segment_props，给所有测试用。"""
    return {
        "name": "测试坡",
        "city": "beijing",
        "distance_km": 5.2,
        "elevation_gain_m": 180,
        "max_gradient_pct": 8.5,
        "difficulty": "hard",
    }


def test_no_api_key_returns_empty():
    """未配 DEEPSEEK_API_KEY → _client = None → generate 直接返空字符串 + warn。"""
    # 直接把 segment_writer._client 置 None 模拟 import 时无 key 状态
    with patch.object(segment_writer, "_client", None):
        result = segment_writer.generate_segment_draft(_segment_props_sample())
    assert result == ""


def test_api_call_failure_returns_empty():
    """OpenAI SDK 抛异常（5xx / 限流 / 网络超时）→ catch 后返空字符串 + error log。"""
    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = RuntimeError("simulated 5xx")
    with patch.object(segment_writer, "_client", fake_client):
        result = segment_writer.generate_segment_draft(_segment_props_sample())
    assert result == ""


def test_normal_success_path_returns_stripped_content():
    """OpenAI 正常返回 → 取 choices[0].message.content + strip 首尾空白返。"""
    fake_message = SimpleNamespace(content="  这是一段活人感介绍 50-100 字  \n")
    fake_choice = SimpleNamespace(message=fake_message)
    fake_response = SimpleNamespace(choices=[fake_choice])

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_response

    with patch.object(segment_writer, "_client", fake_client):
        result = segment_writer.generate_segment_draft(_segment_props_sample())

    assert result == "这是一段活人感介绍 50-100 字"


def test_malformed_response_no_choices_returns_empty():
    """OpenAI 返回缺 choices 字段 → 安全访问兜底返空。"""
    fake_response = SimpleNamespace()  # 无 choices 属性

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_response

    with patch.object(segment_writer, "_client", fake_client):
        result = segment_writer.generate_segment_draft(_segment_props_sample())

    assert result == ""


def test_malformed_response_empty_choices_returns_empty():
    """choices=[] 空列表 → 空数组也算无内容 → 返空。"""
    fake_response = SimpleNamespace(choices=[])

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_response

    with patch.object(segment_writer, "_client", fake_client):
        result = segment_writer.generate_segment_draft(_segment_props_sample())

    assert result == ""


def test_malformed_response_no_content_returns_empty():
    """choices[0].message.content = None → 兜底返空，不 strip 空类型炸。"""
    fake_message = SimpleNamespace(content=None)
    fake_choice = SimpleNamespace(message=fake_message)
    fake_response = SimpleNamespace(choices=[fake_choice])

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_response

    with patch.object(segment_writer, "_client", fake_client):
        result = segment_writer.generate_segment_draft(_segment_props_sample())

    assert result == ""
