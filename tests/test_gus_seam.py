"""GUS SEAM (MK6, GK6-01): the roster never grants, and its evidence chain cannot be edited."""
import json
import os
from pathlib import Path

import pytest

from isycode import gus_seam

# The roster is L0: its ids, expected verdicts and platforms go through this pin.
# Changing a case, adding one or relaxing a verdict means updating the pin on
# purpose, in a reviewed change, after running the roster by hand.
PINNED_ROSTER = "e1cb998c3b3a08168e4e3451c1e5ecc76320a5eb003ea7723f1eac416322d60c"


@pytest.fixture(scope="module")
def report():
    # The roster drives the real owners once; every check below reads that run.
    return gus_seam.run()


def test_the_roster_is_pinned():
    assert gus_seam.roster_digest() == PINNED_ROSTER, (
        "the SEAM roster changed: run it, review the verdicts, then update PINNED_ROSTER")


def test_the_roster_has_sixteen_unique_cases_in_a_stable_order():
    ids = [case.id for case in gus_seam.CASES]
    assert len(ids) == 16
    assert len(set(ids)) == 16
    assert ids == sorted(ids)


def test_no_case_grants_or_errors_and_every_verdict_matches_the_roster(report):
    broken = [result for result in report.results
              if result.verdict in {gus_seam.GRANT, gus_seam.ERROR}]
    assert not broken, [f"{result.case_id}: {result.detail}" for result in broken]
    assert report.failures() == []


def test_the_chain_links_every_case_to_the_one_before_it(report):
    previous = gus_seam.roster_digest()
    for result in report.results:
        assert result.previous == previous
        assert result.digest == gus_seam.case_digest(
            previous, result.case_id, result.verdict, result.detail)
        previous = result.digest
    assert report.chain == previous


def test_the_json_report_repeats_the_roster_and_the_chain(report):
    data = json.loads(gus_seam.report_json(report))
    assert data["roster"] == gus_seam.roster_digest()
    assert data["chain"] == report.chain
    assert [case["verdict"] for case in data["cases"]] == [
        result.verdict for result in report.results]
    assert [case["id"] for case in data["cases"]] == [
        result.case_id for result in report.results]


def test_a_host_without_a_command_sandbox_declares_the_gap(tmp_path, monkeypatch):
    """macOS is POSIX and has no command sandbox: a gap the roster expects.

    The case used to crash on it, which the audit reads as ERROR — a bug in the
    audit, not a statement about the host. The probe runs with the case's own
    bwrap visible, so only what the host truly lacks can answer "no".
    """
    monkeypatch.setattr(gus_seam, "sandbox_executable", lambda: None)
    report = gus_seam.run(tmp_path)
    result = next(item for item in report.results if item.case_id == "seam-02-command-l0")
    assert (result.verdict, result.expected) == (gus_seam.SKIP, gus_seam.SKIP)
    assert report.failures() == []
    assert all(item.verdict != gus_seam.ERROR for item in report.results)
    declared = next(case.platforms for case in gus_seam.CASES if case.id == "seam-02-command-l0")
    if os.name in declared:
        # It was the probe that stopped the case, not the platform list.
        assert result.detail.startswith("NOT_DEMONSTRATED:")


def test_a_temp_folder_reached_through_a_link_still_holds_the_roster_state(tmp_path, monkeypatch):
    """The host's own temp layout cannot decide whether the roster can run.

    macOS names its temp folder through the /var link, and private state
    refuses a path with a linked ancestor: handed over by that name, every case
    would crash for a reason that is not a verdict.
    """
    import shutil
    import tempfile

    from isycode.platform_storage import storage

    real = tmp_path / "temp-real"
    real.mkdir()
    link = tmp_path / "temp-link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"this host cannot create a folder link: {exc}")
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(link))
    given = Path(tempfile.mkdtemp(prefix="gus-seam-given-"))
    base = gus_seam._temporary_base()
    try:
        assert given.is_relative_to(link)
        # The refusal is the fact; the noun for "link" belongs to the platform —
        # POSIX says links, Windows says a reparse point.
        with pytest.raises(ValueError, match="private state cannot traverse"):
            storage.ensure_directory(given / "workspace-authority")
        assert base.is_relative_to(real)
        storage.ensure_directory(base / "workspace-authority")
    finally:
        shutil.rmtree(given, ignore_errors=True)
        shutil.rmtree(base, ignore_errors=True)
