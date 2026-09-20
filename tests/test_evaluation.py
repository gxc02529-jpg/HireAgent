from hire_agent.evaluation import evaluate_cases


def test_evaluation_reports_step_and_end_to_end_outcomes():
    report = evaluate_cases()

    assert report["evaluation_scope"] == "synthetic_regression_fixtures"
    assert report["step_level"] == {
        "tools_started": 5,
        "tools_completed": 5,
        "tool_call_success_rate": 1.0,
    }
    assert report["end_to_end"] == {
        "tasks_total": 3,
        "tasks_successful": 3,
        "task_success_rate": 1.0,
    }
    assert all(not case["unexpected_changed_fields"] for case in report["cases"])
    assert all(not case["missing_changed_fields"] for case in report["cases"])
