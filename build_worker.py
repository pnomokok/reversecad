"""Long-running build process for the web app: imports CadQuery once, then builds jobs from stdin.

Starting a new process per slider move spent about 5.5 s of 8.7 s just importing CadQuery.
Each job is one JSON line {"code": path, "output": path, "overrides": {...}}; the program runs
in a fresh namespace and the part is exported (STL/STEP by extension). The reply is one JSON
line {"ok": true} or {"ok": false, "error": "..."}. Programs are checked (check_code) by the
caller before they get here; webapp/builder.py restarts this process if a job hangs or it dies.
"""
import contextlib
import json
import sys
import traceback


def build(job):
    import cadquery as cq

    from candidates import FUNCTION_NAME

    with open(job["code"], encoding="utf-8") as file:
        code = file.read()
    namespace = {"__name__": "candidate"}
    exec(compile(code, job["code"], "exec"), namespace)
    result = namespace[FUNCTION_NAME](**job.get("overrides", {}))
    if not isinstance(result, cq.Workplane):
        result = cq.Workplane("XY").add(result)
    cq.exporters.export(result, job["output"])


def main():
    import cadquery  # noqa: F401  (load once, up front)

    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        try:
            with contextlib.redirect_stdout(sys.stderr):  # stdout carries only the replies
                build(json.loads(line))
            reply = {"ok": True}
        except Exception:
            reply = {"ok": False, "error": traceback.format_exc().strip().splitlines()[-1]}
        print(json.dumps(reply), flush=True)


if __name__ == "__main__":
    main()
