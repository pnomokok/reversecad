"""Candidate approaches (prompt styles) and stopping the search early."""
import threading
from concurrent.futures import ThreadPoolExecutor

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
    # Only two requests may ever finish, so exactly two workers are freed and each starts one queued
    # request: seven have started, five are still running. Nothing depends on how long a thread takes.
    finished = 2
    workers = candidates.MAX_PARALLEL_REQUESTS
    started = threading.Condition()
    calls = []
    may_finish = threading.Semaphore(finished)
    pools = []

    class WatchedPool(ThreadPoolExecutor):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            pools.append(self)

    def held_request(client, prompt, image_url, effort):
        with started:
            calls.append(prompt)
            started.notify_all()
        assert may_finish.acquire(timeout=30)
        return {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]}

    monkeypatch.setattr(candidates, "make_client", lambda: None)
    monkeypatch.setattr(candidates, "image_data_url", lambda path: "data:")
    monkeypatch.setattr(candidates, "_request_one", held_request)
    monkeypatch.setattr(candidates, "ThreadPoolExecutor", WatchedPool)
    requests = iter_candidates(VIEW, "mask.png", 10)
    received = [next(requests) for _ in range(finished)]
    with started:
        assert started.wait_for(lambda: len(calls) == workers + finished, timeout=30)
    requests.close()
    may_finish.release(10)  # the running requests finish; a queued one would start now if it was not cancelled
    pools[0].shutdown(wait=True)
    assert {r[2]["style"] for r in received} <= set(STYLES)
    assert len(calls) == workers + finished < 10
