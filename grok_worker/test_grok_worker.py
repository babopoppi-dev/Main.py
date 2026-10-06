"""Test del grok_worker con un finto server xAI locale (nessuna chiamata reale)."""
import http.server
import json
import os
import tempfile
import threading
import unittest

_srv_state = {"last": None, "status": 200}


class FakeXAI(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(200, {"data": [{"id": "grok-4"}, {"id": "grok-4-fast"}]})

    def do_POST(self):
        n = int(self.headers["Content-Length"])
        req = json.loads(self.rfile.read(n))
        _srv_state["last"] = {"auth": self.headers["Authorization"], "body": req}
        if _srv_state["status"] != 200:
            self._send(_srv_state["status"], {"error": "boom"})
            return
        self._send(200, {
            "model": req["model"],
            "choices": [{"message": {"role": "assistant", "content": "Nessun problema trovato."}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4},
        })


srv = http.server.HTTPServer(("127.0.0.1", 0), FakeXAI)
threading.Thread(target=srv.serve_forever, daemon=True).start()
TMP = tempfile.mkdtemp()
os.environ["XAI_BASE_URL"] = f"http://127.0.0.1:{srv.server_port}/v1"
os.environ["GROK_OUT_DIR"] = os.path.join(TMP, "out")
os.environ["XAI_API_KEY"] = "test-key"

import grok_worker as gw  # noqa: E402


class GrokWorkerTest(unittest.TestCase):
    def setUp(self):
        _srv_state.update(last=None, status=200)
        os.environ["XAI_API_KEY"] = "test-key"
        self.src = os.path.join(TMP, "codice.py")
        with open(self.src, "w") as f:
            f.write("print('ciao')\n")

    def test_job_writes_unique_result(self):
        self.assertEqual(gw.main(["lavoro", "--tipo", "revisione", "--file", self.src, "Controlla"]), 0)
        self.assertEqual(gw.main(["lavoro", "--tipo", "revisione", "--file", self.src, "Controlla"]), 0)
        outs = sorted(os.listdir(os.environ["GROK_OUT_DIR"]))
        self.assertGreaterEqual(len(outs), 2)
        with open(os.path.join(os.environ["GROK_OUT_DIR"], outs[-1])) as f:
            text = f.read()
        self.assertIn("Nessun problema trovato.", text)
        self.assertIn("10 in / 4 out", text)
        sent = _srv_state["last"]
        self.assertEqual(sent["auth"], "Bearer test-key")
        self.assertIn("print('ciao')", sent["body"]["messages"][1]["content"])
        self.assertIn("revisore", sent["body"]["messages"][0]["content"])

    def test_dry_run_sends_nothing(self):
        self.assertEqual(gw.main(["lavoro", "--prova", "--file", self.src, "x"]), 0)
        self.assertIsNone(_srv_state["last"])

    def test_sensitive_files_blocked(self):
        for name in [".env", "server.key", "pec_inbox.txt", "api_token.json", "GoogleService-Info.plist"]:
            p = os.path.join(TMP, name)
            with open(p, "w") as f:
                f.write("x")
            self.assertEqual(gw.main(["lavoro", "--file", p, "x"]), 2, name)
        self.assertIsNone(_srv_state["last"])

    def test_ordinary_names_allowed(self):
        for name in ["spec.md", "inspector.py", "expected.txt"]:
            self.assertFalse(gw.is_blocked(name), name)

    def test_missing_key(self):
        del os.environ["XAI_API_KEY"]
        self.assertEqual(gw.main(["lavoro", "x"]), 2)

    def test_http_error(self):
        _srv_state["status"] = 429
        self.assertEqual(gw.main(["lavoro", "x"]), 2)

    def test_empty_task(self):
        self.assertEqual(gw.main(["lavoro"]), 2)

    def test_models(self):
        self.assertEqual(gw.main(["modelli"]), 0)


if __name__ == "__main__":
    unittest.main()
