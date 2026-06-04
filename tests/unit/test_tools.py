"""Unit tests for agent tools — pure functions with no external dependencies."""
from unittest.mock import patch


def test_get_current_month_format():
    from agent.tools.agent_tools import get_current_month

    result = get_current_month.invoke({})
    assert len(result) == 7, f"Expected 'YYYY-MM', got '{result}'"
    year, month = result.split("-")
    assert year.isdigit() and len(year) == 4
    assert month.isdigit() and 1 <= int(month) <= 12


def test_get_weather_contains_city():
    from agent.tools.agent_tools import get_weather

    result = get_weather.invoke({"city": "深圳"})
    assert isinstance(result, str)
    assert "深圳" in result


def test_get_weather_contains_city_name_for_any_city():
    from agent.tools.agent_tools import get_weather

    for city in ["北京", "上海", "广州"]:
        result = get_weather.invoke({"city": city})
        assert city in result


def test_get_user_location_valid_city():
    from agent.tools.agent_tools import get_user_location

    valid = {"深圳", "合肥", "杭州"}
    result = get_user_location.invoke({})
    assert result in valid, f"Unexpected city: {result}"


def test_fetch_external_data_unknown_user_returns_empty():
    from agent.tools.agent_tools import fetch_external_data

    with patch("agent.tools.agent_tools.generate_external_data"):
        result = fetch_external_data.invoke({"user_id": "nonexistent_999", "month": "2099-01"})
    assert result == ""


def test_fill_context_for_report_returns_string():
    from agent.tools.agent_tools import fill_context_for_report

    result = fill_context_for_report.invoke({})
    assert isinstance(result, str)
    assert len(result) > 0
