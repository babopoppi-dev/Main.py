#!/usr/bin/python3
from __future__ import annotations

"""
Live smoke test for the ANDREA AI TEAM write gate (run after deploy, as andrea-ai-team):

  runuser -u andrea-ai-team -g andrea-ai-team-ipc -- /usr/bin/python3 -B /opt/andrea-ai-team/live_smoke_v3.py

Through the REAL gate and the REAL MCP Andrea it:
  1. opens a work_session + work_lock on a throw-away project;
  2. writes a tiny module and a passing unittest, runs the real tests (expects PASS);
  3. breaks the module, runs the tests again (expects FAIL);
  4. rolls back every operation with MCP native rollback (project must disappear);
  5. releases the lock and closes the session.
Prints one JSON report; exit code 0 only if every step behaved as expected.
"""

import json
import sys
import time
import uuid

from project_builder import parse_test_output
from write_gate import GateError, WriteGateClient

GOOD = "def add(a, b):\n    return a + b\n"
BAD = "def add(a, b):\n    return a - b\n"
TEST = (
    "import unittest\n\nfrom calc import add\n\n\n"
    "class T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n\n\n"
    "if __name__ == '__main__':\n    unittest.main()\n"
)


def main() -> int:
    gate = WriteGateClient()
    uid = uuid.uuid4().hex
    project = "zz_smoke_" + time.strftime("%H%M%S")
    report: dict = {"project": project, "steps": []}
    ops: list[str] = []
    ok = True

    def step(name: str, passed: bool, **info) -> None:
        nonlocal ok
        ok = ok and passed
        report["steps"].append({"step": name, "ok": passed, **info})

    try:
        step("gate_status", bool(gate.status().get("ok")))
        info = gate.begin(uid, project)
        step("begin", bool(info.get("work_session_id")), lock=bool(info.get("work_lock_id")))
        ops.append(gate.mkdir(uid, project, "")["operation_id"])
        ops.append(gate.write(uid, project, "calc.py", GOOD)["operation_id"])
        ops.append(gate.write(uid, project, "test_calc.py", TEST)["operation_id"])
        step("write", all(ops))
        step("read_back", gate.read(uid, project, "calc.py") == GOOD)
        r1 = parse_test_output(gate.run_tests(uid, project, "unittest", timeout=60))
        step("tests_pass", r1.passed and r1.ran == 1, ran=r1.ran, tail=r1.output_tail[-400:])
        ops.append(gate.write(uid, project, "calc.py", BAD)["operation_id"])
        r2 = parse_test_output(gate.run_tests(uid, project, "unittest", timeout=60))
        step("tests_fail_detected", (not r2.passed) and r2.failed == 1, failed=r2.failed)
        try:
            gate.write(uid, project, "../escape.py", "x")
            step("traversal_blocked", False)
        except GateError as exc:
            step("traversal_blocked", exc.code in {"PATH_OUTSIDE_PROJECT", "INVALID_PATH"}, code=exc.code)
    except GateError as exc:
        step("gate_error", False, code=exc.code, detail=exc.detail[:200])
        if exc.code in {"LOCK_REQUIRED", "MCP_DENIED"}:
            report["hint"] = ("Lo shell MCP richiede probabilmente un lock aggiuntivo: impostare "
                              "GATE_SHELL_LOCK_PATH nella unit del gate e ripetere lo smoke.")
    finally:
        rolled = 0
        for op in reversed([o for o in ops if o]):
            try:
                gate.rollback(uid, project, op)
                rolled += 1
            except GateError as exc:
                report.setdefault("rollback_errors", []).append(exc.code)
        try:
            gone = not gate.exists(uid, project, "").get("exists")
        except GateError:
            gone = False
        step("rollback", rolled == len([o for o in ops if o]) and gone, rolled=rolled)
        try:
            gate.end(uid, project)
            step("end", True)
        except GateError as exc:
            step("end", False, code=exc.code)
    report["result"] = "SMOKE_V3=OK" if ok else "SMOKE_V3=FAIL"
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
