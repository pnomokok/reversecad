"""Candidate approaches (prompt styles) and stopping the search early."""
import threading
import time

import candidates
from candidates import STYLES, build_prompt, iter_candidates, style_for
from e2e_pipeline import search_settled

VIEW = {"outline": {"length_mm": 80, "width_mm": 40, "vertex_count": 4,
                    "polygon_mm": [[-40, -20], [40, -20], [40, 20], [-40, 20]], "arcs": []},
        "hole_count": 0, "holes": []}


def test_candidates_take_the_approaches_in_turn():
    assert [style_for(i) for i in range(1, 7)] == list(STYLES) * 2
    prompts = {style: build_prompt(VIEW, 3.0, style) for style in STYLES}
    assert len(set(prompts.values())) == len(STYLES)
    for style, prompt in prompts.items():
        assert f"- Approach for this program: {STYLES[style]}" in prompt
        assert prompt.rstrip().endswith("nothing else.")  # the answer format stays last
    assert "Approach for this program" not in build_prompt(VIEW, 3.0)


def row(corners=4, length=80.0, passed=True):
    return {"iou": 0.98, "deviation_ok": passed, "topology_ok": None, "corners": corners,
            "hole_layout": [[32, 12, 6]], "outline_mm": [length, 40.0]}


def test_search_settles_when_three_passing_candidates_agree():
    assert not search_settled([row(), row(), row(passed=False)])
    assert not search_settled([row(), row(), row(corners=5)])  # a different shape does not count
    assert search_settled([row(), row(corners=5), row(length=80.3), row()])  # 80.3 rounds to the same 80 mm


def test_closing_the_search_cancels_requests_not_yet_started(monkeypatch):
    calls, lock = [], threading.Lock()

    def slow_request(client, prompt, image_url, effort):
        with lock:
            calls.append(prompt)
        time.sleep(0.2)
        return {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]}

    monkeypatch.setattr(candidates, "make_client", lambda: None)
    monkeypatch.setattr(candidates, "image_data_url", lambda path: "data:")
    monkeypatch.setattr(candidates, "_request_one", slow_request)
    requests = iter_candidates(VIEW, "mask.png", 10)
    received = [next(requests) for _ in range(2)]
    requests.close()
    time.sleep(0.5)  # requests already running may finish; the queued ones must not start
    assert {r[2]["style"] for r in received} <= set(STYLES)
    assert len(calls) <= candidates.MAX_PARALLEL_REQUESTS + len(received) < 10  # a freed worker may start one more
