"""Local pipeline regression, NOT a model-quality benchmark. No paid calls."""
import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def main():
    cases = json.loads(Path(__file__).with_name("cases.json").read_text())
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(app_mode="demo", database_url=f"sqlite:///{tmp}/app.db", checkpoint_url=f"{tmp}/cp.db", console_token="", _env_file=None)
        with TestClient(create_app(settings)) as client:
            for case in cases:
                payload = {"title": f"Regression {case['id']}", "description": case.get("description", "请根据所提供的日志与代码差异排查故障。"), "fixture_id": case.get("fixture")}
                created = client.post("/api/runs", json=payload)
                run_id = created.json()["id"]
                row = client.get(f"/api/runs/{run_id}").json()
                checks = {"awaits_approval": row["status"] == "awaiting_approval", "no_unapproved_write": row["ticket"] is None, "expected_abstention": bool(row["report"]["findings"]) == case["expect_finding"], "zero_model_calls": row["metrics"]["model_calls"] == 0}
                if case.get("expected_term"):
                    checks["expected_fixture_term"] = case["expected_term"] in row["report"]["summary"]
                results.append({"case": case["id"], "passed": all(checks.values()), "checks": checks})
    output = {"evaluation_type": "deterministic_pipeline_regression", "is_model_accuracy": False, "cases": len(results), "passed": sum(r["passed"] for r in results), "results": results}
    print(json.dumps(output, indent=2, ensure_ascii=False))
    if not all(r["passed"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
