"""Tests for project settings resolution and how they reach an add.

`projects.settings` is a JSONB blob, so nothing at the database level says what
belongs in it. These tests are that schema: they pin the defaults, the
section-wise merge that stops one settings page clobbering another's section,
and the actor rule that decides which set of custom instructions an add gets.

The actor rule is the one worth guarding hardest. Instructions that silently
never apply look exactly like instructions that do not work, and the difference
is only visible by reading what the SDK does with `prompt`.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def ps():
    import project_settings

    return project_settings


class TestResolve:
    def test_empty_settings_resolve_to_defaults(self, ps):
        resolved = ps.resolve({})
        assert resolved["extraction"]["infer"] is True
        assert resolved["retention"]["default_expiration_days"] is None
        assert resolved["categories"]["auto_classify"] is True

    def test_none_resolves_to_defaults(self, ps):
        assert ps.resolve(None) == ps.resolve({})

    def test_stored_values_win_over_defaults(self, ps):
        resolved = ps.resolve({"extraction": {"infer": False}})
        assert resolved["extraction"]["infer"] is False

    def test_absent_keys_still_get_their_default(self, ps):
        """A project created before a setting existed must behave like a new one."""
        resolved = ps.resolve({"extraction": {"infer": False}})
        assert resolved["extraction"]["multilingual"] is False
        assert "user_instructions" in resolved["extraction"]

    def test_unknown_keys_are_not_surfaced(self, ps):
        resolved = ps.resolve({"extraction": {"nonsense": 1}})
        assert "nonsense" not in resolved["extraction"]

    def test_a_non_dict_section_falls_back_to_defaults(self, ps):
        """Hand-edited JSON is a real source of this; it must not crash a read."""
        assert ps.resolve({"extraction": "oops"})["extraction"]["infer"] is True


class TestMerge:
    def test_updating_one_section_leaves_the_others_alone(self, ps):
        """Four settings pages each own a section; a shallow merge would lose one."""
        existing = {"extraction": {"infer": False}, "retention": {"decay_enabled": True}}
        merged = ps.merge(existing, {"extraction": {"multilingual": True}})
        assert merged["retention"]["decay_enabled"] is True
        assert merged["extraction"]["infer"] is False
        assert merged["extraction"]["multilingual"] is True

    def test_unknown_keys_are_dropped_on_write(self, ps):
        merged = ps.merge({}, {"extraction": {"user_instructions": "x", "bogus": 1}})
        assert merged["extraction"] == {"user_instructions": "x"}

    def test_unknown_sections_are_dropped(self, ps):
        assert ps.merge({}, {"billing": {"plan": "pro"}}) == {}

    def test_a_non_dict_section_is_ignored_rather_than_stored(self, ps):
        assert ps.merge({}, {"extraction": "oops"}) == {}

    def test_merge_does_not_mutate_the_input(self, ps):
        existing = {"extraction": {"infer": False}}
        ps.merge(existing, {"extraction": {"infer": True}})
        assert existing["extraction"]["infer"] is False


class TestExtractionPrompt:
    """Which instructions an add gets, by which ids it carries."""

    SETTINGS = {"extraction": {"user_instructions": "USER SET", "agent_instructions": "AGENT SET"}}

    def test_user_only_add_gets_the_user_set(self, ps):
        assert ps.extraction_prompt(self.SETTINGS, has_user=True, has_agent=False) == "USER SET"

    def test_agent_only_add_gets_the_agent_set(self, ps):
        assert ps.extraction_prompt(self.SETTINGS, has_user=False, has_agent=True) == "AGENT SET"

    def test_an_add_with_both_ids_gets_both_sets(self, ps):
        """Dropping either half would silently ignore configuration someone wrote."""
        prompt = ps.extraction_prompt(self.SETTINGS, has_user=True, has_agent=True)
        assert "USER SET" in prompt and "AGENT SET" in prompt

    def test_a_run_only_add_falls_back_to_the_user_set(self, ps):
        assert ps.extraction_prompt(self.SETTINGS, has_user=False, has_agent=False) == "USER SET"

    def test_no_instructions_returns_none_not_empty_string(self, ps):
        """The SDK resolves `prompt or custom_instructions`; "" would blank the default."""
        assert ps.extraction_prompt({}, has_user=True, has_agent=False) is None
        assert ps.extraction_prompt({"extraction": {"user_instructions": "   "}}, has_user=True, has_agent=False) is None

    def test_multilingual_appends_a_language_instruction(self, ps):
        prompt = ps.extraction_prompt(
            {"extraction": {"user_instructions": "keep facts", "multilingual": True}},
            has_user=True,
            has_agent=False,
        )
        assert "keep facts" in prompt
        assert "language" in prompt.lower()

    def test_multilingual_alone_still_produces_a_prompt(self, ps):
        prompt = ps.extraction_prompt(
            {"extraction": {"multilingual": True}}, has_user=True, has_agent=False
        )
        assert prompt is not None and "translate" in prompt.lower()

    def test_an_empty_agent_set_does_not_leave_a_blank_prompt(self, ps):
        settings = {"extraction": {"user_instructions": "USER SET", "agent_instructions": ""}}
        assert ps.extraction_prompt(settings, has_user=False, has_agent=True) is None
