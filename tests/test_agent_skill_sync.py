from scripts.sync_agent_skill import FILES, SOURCE, TARGET


def test_repository_skill_matches_export_source() -> None:
    for relative in FILES:
        assert (TARGET / relative).read_bytes() == (SOURCE / relative).read_bytes(), relative
