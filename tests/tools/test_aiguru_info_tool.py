"""Tests for the aiguru_info built-in tool (local product knowledge).

The tool exists so the chat agent answers "what can AI Guru do / how does X
work here" questions from the bundled guide instead of web_searching for the
product name or hallucinating capabilities.
"""

from __future__ import annotations

import pytest

from deeptutor.tools.builtin import (
    BUILTIN_TOOL_NAMES,
    CONFIGURABLE_BUILTIN_TOOL_NAMES,
    AIGuruInfoTool,
)
from deeptutor.tools.product_info_data import (
    PRODUCT_NAME,
    PRODUCT_OVERVIEW,
    search_product_info,
)


def test_tool_is_registered_and_auto_mounted():
    assert "aiguru_info" in BUILTIN_TOOL_NAMES
    # Membership in CONFIGURABLE_* is what auto-mounts it in product chat
    # and lets partners gate it (AUTO_MOUNTED_TOOLS derives from this).
    assert "aiguru_info" in CONFIGURABLE_BUILTIN_TOOL_NAMES


def test_description_steers_away_from_web_search():
    definition = AIGuruInfoTool().get_definition()
    lowered = definition.description.lower()
    assert "web_search" in lowered  # explicit 'never web_search' steering
    assert "ai guru" in lowered


@pytest.mark.asyncio
async def test_execute_topic_vault_returns_vault_section():
    result = await AIGuruInfoTool().execute(topic="how does the video vault work")
    assert result.success is not False
    assert "GURUVAULT02" in result.content or "AES-256-GCM" in result.content
    assert any(s.get("type") == "product_guide" for s in result.sources)


@pytest.mark.asyncio
async def test_execute_matches_monitoring_and_telegram():
    monitor = await AIGuruInfoTool().execute(topic="distraction warnings cooldown")
    assert "warning" in monitor.content.lower()

    telegram = await AIGuruInfoTool().execute(topic="telegram alerts outbox")
    assert "outbox" in telegram.content.lower() or "Telegram" in telegram.content


@pytest.mark.asyncio
async def test_execute_empty_topic_returns_overview_with_index():
    result = await AIGuruInfoTool().execute()
    assert PRODUCT_NAME in result.content
    assert PRODUCT_OVERVIEW.strip()[:40] in result.content
    assert "Detail sections" in result.content


@pytest.mark.asyncio
async def test_unknown_topic_falls_back_to_overview_not_error():
    result = await AIGuruInfoTool().execute(topic="quantum chromodynamics homework")
    assert PRODUCT_NAME in result.content
    assert "no dedicated section matched" in result.content


class TestSearchRanking:
    def test_direct_key_beats_alias_noise(self):
        vault = search_product_info("vault")
        assert "GURUVAULT02" in vault or "AES-256-GCM" in vault

    def test_multi_word_query_picks_best_section(self):
        tunnel = search_product_info("parent remote access tunnel cloudflare")
        assert "cloudflare" in tunnel.lower()

    def test_troubleshoot_hits_quota_guidance(self):
        out = search_product_info("429 quota exceeded error")
        assert "quota" in out.lower()


def test_all_sections_have_alias_coverage():
    """Every section must be reachable by at least its own key."""
    from deeptutor.tools.product_info_data import _TOPIC_SECTIONS

    for key in _TOPIC_SECTIONS:
        assert key in search_product_info(key).lower() or _TOPIC_SECTIONS[key].split()[
            0
        ] in search_product_info(key)
