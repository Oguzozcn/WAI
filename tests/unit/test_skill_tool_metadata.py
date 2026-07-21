"""Regression test for a real, previously-silent bug: the installed
google-adk SkillToolset only exposes a skill's function tools to the model
once that skill's SKILL.md frontmatter lists them under
`metadata.adk_additional_tools`. Without it, chat-driven tool calls fail
(or the model just improvises instead of calling the tool) for every skill,
not just a newly added one — discovered while building Documentation Master
(July 2026). `_write_skill_file` must always re-derive this metadata from
SKILL_TOOL_GROUPS so a persona edit through the Agent Console can never
silently drop it again.
"""

from src.api.routes.dev_console import SKILL_TOOL_GROUPS, _write_skill_file


def test_write_skill_file_embeds_adk_additional_tools_for_tool_bearing_skill(monkeypatch, tmp_path):
    monkeypatch.setattr("src.api.routes.dev_console.SKILLS_DIR", tmp_path)
    (tmp_path / "knowledge-coach").mkdir()

    _write_skill_file("knowledge-coach", "knowledge-coach", "A tutor.", "Body text.")

    content = (tmp_path / "knowledge-coach" / "SKILL.md").read_text()
    assert "metadata:" in content
    assert "adk_additional_tools:" in content
    for tool_name in SKILL_TOOL_GROUPS["knowledge-coach"]:
        assert f"- {tool_name}" in content


def test_write_skill_file_omits_metadata_for_toolless_skill(monkeypatch, tmp_path):
    monkeypatch.setattr("src.api.routes.dev_console.SKILLS_DIR", tmp_path)
    (tmp_path / "kb-validator").mkdir()
    assert SKILL_TOOL_GROUPS["kb-validator"] == []

    _write_skill_file("kb-validator", "kb-validator", "An auditor.", "Body text.")

    content = (tmp_path / "kb-validator" / "SKILL.md").read_text()
    assert "metadata:" not in content


def test_write_skill_file_metadata_survives_repeated_persona_edits(monkeypatch, tmp_path):
    """The exact failure mode this guards against: editing a persona through
    the Agent Console must not be able to drop the tool-visibility metadata,
    since a developer only ever supplies name/description/instruction."""
    monkeypatch.setattr("src.api.routes.dev_console.SKILLS_DIR", tmp_path)
    (tmp_path / "curriculum-builder").mkdir()

    _write_skill_file("curriculum-builder", "curriculum-builder", "v1", "Body v1.")
    _write_skill_file("curriculum-builder", "curriculum-builder", "v2 description", "Body v2.")

    content = (tmp_path / "curriculum-builder" / "SKILL.md").read_text()
    assert "v2 description" in content
    assert "Body v2." in content
    for tool_name in SKILL_TOOL_GROUPS["curriculum-builder"]:
        assert f"- {tool_name}" in content


def test_real_skill_files_all_declare_correct_adk_additional_tools():
    """The six on-disk .agents/skills/*/SKILL.md files themselves (not a
    temp copy) must already carry the fix, since a fresh app boot reads them
    as-is before any Agent Console edit ever happens."""
    from src.agents.agent import _load_skills

    skills_by_name = {s.name: s for s in _load_skills()}
    for skill_id, tool_names in SKILL_TOOL_GROUPS.items():
        skill = skills_by_name.get(skill_id)
        assert skill is not None, f"skill '{skill_id}' failed to load"
        declared = skill.frontmatter.metadata.get("adk_additional_tools") or []
        assert set(declared) == set(tool_names), (
            f"'{skill_id}' declares {declared}, expected {tool_names}"
        )
