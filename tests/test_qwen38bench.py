#!/usr/bin/env python3
"""Regression tests for actual SGLang SSE token usage (no GPU or network)."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "qwen38bench"
loader = importlib.machinery.SourceFileLoader("qwen38bench_under_test", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
bench = importlib.util.module_from_spec(spec)
loader.exec_module(bench)


class FakeResponse:
    def __init__(self, lines=None, result=None):
        self.lines = [(s if isinstance(s, bytes) else s.encode("utf-8"))
                      for s in (lines or [])]
        self.result = result

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def __iter__(self):
        return iter(self.lines)

    def read(self, *_):
        return json.dumps(self.result).encode("utf-8")


def data(obj):
    return "data: " + json.dumps(obj) + "\r\n"


def streaming(*events):
    # urllib's HTTP response iterator yields ONE physical line at a time.
    lines = []
    for event in events:
        lines.extend([data(event), "\r\n"])
    lines.extend(["data: [DONE]\r\n", "\r\n"])
    return FakeResponse(lines)


class ActualTokenCountingTests(unittest.TestCase):
    def run_with(self, response, clocks, **kw):
        with mock.patch.object(bench, "post", return_value=response), \
             mock.patch.object(bench.time, "perf_counter",
                               side_effect=clocks):
            return bench.one_run("https://test.invalid/v1", "test-model", 0, 30,
                                 **kw)

    def test_three_sse_chunks_are_not_three_tokens(self):
        response = streaming(
            {"choices": [{"delta": {"role": "assistant"}}]},
            {"choices": [{"delta": {"content": "First"}}]},
            {"choices": [{"delta": {"content": " second third"}}]},
            {"choices": [{"delta": {"content": " fourth"}}]},
            {"choices": [], "usage": {"completion_tokens": 12,
                                     "prompt_tokens": 15}})
        r = self.run_with(response, [10.0, 11.0, 13.0])
        self.assertEqual(r["out_tokens"], 12)
        self.assertEqual(r["prompt_tokens"], 15)
        self.assertEqual(r["token_count_source"], "server_usage")
        self.assertEqual(r["ttft"], 1.0)
        self.assertEqual(r["tps"], 5.5)  # (12 - 1) / (13 - 11)

    def test_missing_usage_must_not_fall_back_to_event_count(self):
        response = streaming(
            {"choices": [{"delta": {"content": "a"}}]},
            {"choices": [{"delta": {"content": "b"}}]})
        r = self.run_with(response, [3.0, 4.0, 5.0])
        self.assertIsNone(r["out_tokens"])
        self.assertIsNone(r["tps"])
        self.assertEqual(r["token_count_source"], "unavailable")

    def test_zero_usage_must_not_fall_back(self):
        response = streaming(
            {"choices": [{"delta": {"content": "a"}}]},
            {"choices": [], "usage": {"completion_tokens": 0}})
        r = self.run_with(response, [3.0, 4.0, 5.0])
        self.assertEqual(r["out_tokens"], 0)
        self.assertIsNone(r["tps"])
        self.assertEqual(r["token_count_source"], "server_usage")

    def test_single_token_cannot_estimate_decode_rate(self):
        response = streaming(
            {"choices": [{"delta": {"content": "one"}}]},
            {"choices": [], "usage": {"completion_tokens": 1}})
        r = self.run_with(response, [3.0, 4.0, 5.0])
        self.assertEqual(r["out_tokens"], 1)
        self.assertIsNone(r["tps"])

    def test_invalid_usage_does_not_become_fake_speed(self):
        for invalid in ("12", -1, True, 12.5, None):
            with self.subTest(invalid=invalid):
                response = streaming(
                    {"choices": [{"delta": {"content": "foo"}}]},
                    {"choices": [], "usage": {"completion_tokens": invalid}})
                r = self.run_with(response, [1.0, 2.0, 4.0])
                self.assertIsNone(r["out_tokens"])
                self.assertIsNone(r["tps"])

    def test_sse_multiline_data_and_comments(self):
        response = FakeResponse([
            b": keep-alive\r\n", b"\r\n",
            b"data: {\"choices\":\r\n",
            b"data: [{\"delta\":{\"content\":\"foo\"}}]}\r\n",
            b"\r\n",
            b"data:[DONE]\r\n", b"\r\n",
        ])
        ev = list(bench.sse_events(response))
        self.assertEqual(len(ev), 2)
        self.assertEqual(json.loads(ev[0])["choices"][0]["delta"]["content"],
                         "foo")
        self.assertEqual(ev[1], "[DONE]")

    def test_reasoning_tokens_also_mark_ttft(self):
        response = streaming(
            {"choices": [{"delta": {"role": "assistant"}}]},
            {"choices": [{"delta": {"reasoning_content": "thinking"}}]},
            {"choices": [], "usage": {"completion_tokens": 4}})
        r = self.run_with(response, [2.0, 3.0, 4.0])
        self.assertEqual(r["ttft"], 1.0)
        self.assertEqual(r["tps"], 3.0)

    def test_missing_done_does_not_claim_complete_benchmark(self):
        response = FakeResponse([
            data({"choices": [{"delta": {"content": "x"}}]}), "\r\n"])
        with self.assertRaisesRegex(ValueError, "missing .DONE."):
            self.run_with(response, [1.0, 2.0])

    def test_nonstream_usage_is_counted_without_fake_decode_speed(self):
        response = FakeResponse(result={
            "usage": {"completion_tokens": 23, "prompt_tokens": 10},
            "choices": [{"message": {"content": "answer"}}]})
        r = self.run_with(response, [1.0, 5.0], stream=False)
        self.assertEqual(r["out_tokens"], 23)
        self.assertIsNone(r["ttft"])
        self.assertIsNone(r["tps"])

    def test_main_prints_na_instead_of_crashing_when_usage_missing(self):
        no_usage = {"ttft": 0.25, "total": 1.0, "out_tokens": None,
                    "prompt_tokens": None, "tps": None,
                    "token_count_source": "unavailable"}
        model_response = FakeResponse(
            result={"data": [{"id": "testing-model"}]})
        output = io.StringIO()
        with mock.patch.object(bench, "get", return_value=model_response), \
             mock.patch.object(bench, "one_run",
                               side_effect=[no_usage, no_usage, no_usage]), \
             mock.patch.object(bench, "server_info", return_value={}), \
             mock.patch.object(sys, "argv",
                               ["qwen38bench", "dummy-pod", "--runs", "2"]), \
             contextlib.redirect_stdout(output):
            rc = bench.main()
        self.assertEqual(rc, 0)
        self.assertIn("n/a (server usage unavailable)", output.getvalue())
        self.assertIn("SSE chunks are never counted", output.getvalue())

    def test_cli_rejects_zero_runs_before_network(self):
        with mock.patch.object(sys, "argv", ["qwen38bench", "--runs", "0"]), \
             contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as exit_context:
                bench.main()
        self.assertEqual(exit_context.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
