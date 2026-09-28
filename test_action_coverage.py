from isycode import action_coverage
from isycode.actions import ACTION_BY_ID


def test_owner_coverage_report_exposes_unowned_actions_and_effect_callsites():
    report = action_coverage.owner_coverage_report()

    assert report["secure_closed"] is False
    assert "mobile.host.start" in report["unowned_effectful_actions"]
    assert "credentials.add" in report["unowned_effectful_actions"]
    callsites = {item["callsite"]: item for item in report["callsites"]}
    assert callsites["MobileHost.start"]["status"] == "UNWIRED"
    assert callsites["TUIApp._save_provider_key"]["status"] == "BLOCKED_BY_DESIGN"


def test_owner_coverage_report_detects_unknown_owner_action(monkeypatch):
    monkeypatch.setattr(action_coverage, "OWNER_ACTIONS", {"test_owner": frozenset({"not.real"})})

    report = action_coverage.owner_coverage_report()

    assert report["owner_action_mismatches"] == ["test_owner:not.real"]
    assert {item["action"] for item in report["actions"]} == set(ACTION_BY_ID)


def test_owner_coverage_report_detects_ambiguous_conflicting_owner():
    report = action_coverage.owner_coverage_report()

    assert {item["action"] for item in report["ambiguous_actions"]} == {"broker.start"}


def test_declared_effect_callsites_reference_catalog_actions():
    assert {item[0] for item in action_coverage.KNOWN_EFFECT_CALLSITES} <= set(ACTION_BY_ID)
