"""Original-source and host-action contracts for a finite graphical test.

The two real-browser scenarios execute separately in the native/transport
workflow. These tests run without graphical or network dependencies.
"""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3

from research_y import publication_identity as identity
from tools.gui_feasibility import run_materialisation_window as probe


def test_gui_window_132_original_sources_preserve_individual_citations(tmp_path):
    project, run = probe._fixture(tmp_path)
    original = probe._ledger(project)
    assert original['sources'] == 132
    assert original['memberships'] == 132
    assert original['provisional'] == original['links'] == 0
    assert original['identity_audits'] == 0
    assert original['original_source_sha256'] != original['original_membership_sha256']
    assert original['sqlite_integrity_check'] == 'ok'
    assert original['foreign_key_check'] is True
    assert original['linked_order_exact'] is True
    with closing(sqlite3.connect(project.database_path)) as db:
        rows = db.execute(
            "SELECT source_name,source_record_id,original_metadata_json "
            "FROM source_retrievals WHERE run_id=? ORDER BY retrieval_id LIMIT 2",
            (run,)).fetchall()
        assert [row[0] for row in rows] == ['pubmed','wos']
        assert 'Identical original abstract title' in rows[0][2]
        assert 'Identical original abstract title' in rows[1][2]
        assert rows[0][1] != rows[1][1]
        saved = db.execute(
            "SELECT exact_query FROM source_queries WHERE run_id=? "
            "ORDER BY exact_query", (run,)).fetchall()
        assert len(saved) == 2
        assert any('TS=(' in row[0] for row in saved)
        assert any('[All Fields]' in row[0] for row in saved)
    assert probe._ledger(project) == original


def test_window_driver_and_native_scenario_actions_are_fixed():
    root = Path(__file__).parents[1]
    app = (root / 'tools/gui_feasibility/real_project_app.py').read_text(
        encoding='utf-8')
    driver = (root / 'tools/gui_feasibility/run_real_project.py').read_text(
        encoding='utf-8')
    experiment = (root / 'tools/gui_feasibility/run_materialisation_window.py').read_text(
        encoding='utf-8')
    assert "WINDOW_SCENARIOS = ('publication_window', 'publication_window_lost_reply')" in app
    assert 'if args.scenario in WINDOW_SCENARIOS:' in app
    assert "if name == 'publication_window_confirm':" in app
    assert "flow.confirm_publication_window(value)" in app
    assert 'publication-window-recovery' in app
    assert 'publication-window-inspection' in app
    assert 'publication-window-actor' in app
    assert "if scenario in ('publication_window', 'publication_window_lost_reply'):" in driver
    # Fixed transport actions are still validated, now with test-owned expected
    # counts for both original 132-record and new 100k-record fixtures.
    assert 'return transport_window_steps(' in driver
    assert 'expected_pending=expected_pending' in driver
    assert 'expected_remaining=expected_remaining' in driver
    assert 'expected_provisional=expected_provisional' in driver
    assert 'window_lost_reply_not_refused' in driver
    # Verify the actual scenario is present without assuming Python quote style.
    assert "publication_window_lost_reply" in experiment
    assert "publication_window" in experiment
    assert "for scenario in" in experiment
    # This is a command-line-selected synthetic failure, NOT a browser route
    # accepting a client-selected fault, source ID, original path or query.
    assert "if name == 'publication_window_confirm':\n                    raise ProjectFlowError('worker_interrupted')" in app
    assert 'window-gui-evidence.json' in experiment
    assert 'full_AT_22_acceptance' in experiment
    assert 'no_network_provider_requests' in experiment
