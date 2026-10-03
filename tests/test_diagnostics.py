from buzz.diagnostics import build_diagnostic_report


def test_diagnostic_report_surfaces_snapshot_gates_and_questions():
    task = {"task_id": "task-1", "project_id": "osana"}
    handoff = {
        "next_actions": ["Review readiness"],
        "context_pack": {
            "documents": {
                "snapshot": '{"mode":"snapshot","provisional":true,"state":{"lifecycle":"pilot","maturity":"in_construction","live_state_available":false},"approval_gates":[{"id":"pilot","status":"pending_evidence","description":"collect evidence"}],"open_questions":["What is live?"]}'
            }
        },
    }

    report = build_diagnostic_report(task, handoff)

    assert report["readiness"]["maturity"] == "in_construction"
    assert report["gaps"] == [{
        "id": "pilot",
        "status": "pending_evidence",
        "description": "collect evidence",
        "evidence_required": True,
    }]
    assert report["open_questions"] == ["What is live?"]
    assert report["external_effects"] is False
