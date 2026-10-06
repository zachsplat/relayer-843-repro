"""Strict-nonce proxy with a controllable transport-error window, for the #843 reproduction.

Forwards JSON-RPC to anvil. Two behaviours on top:
1. Strict nonce (emulates a no-mempool rollup such as Arbitrum): an eth_sendRawTransaction whose
   nonce is above anvil's pending nonce for the sender is rejected with a JSON-RPC error
   "nonce too high" instead of being queued.
2. Transport-error window: while `fail_send_until` (epoch seconds, set through POST /control)
   is in the future, every eth_sendRawTransaction gets HTTP 503, so the relayer's submit jobs
   retry and eventually give up, exactly as a flaky provider would cause.
GET /stats returns counters. Needs the `rlp` package (pip install rlp) to decode the nonce.
"""
import json, os, time, threading, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import rlp

UPSTREAM = os.environ.get("UPSTREAM", "http://anvil:8545")
LOG = os.environ.get("PROXY_LOG", "/logs/proxy.log")
lock = threading.Lock()
state = {"fail_send_until": 0.0}
stats = {"send_raw": 0, "send_ok": 0, "send_503": 0, "send_nonce_too_high": 0, "send_other_error": 0, "max_nonce_seen": -1, "rejected_nonces": []}

def log(m):
    line = f"{time.strftime('%H:%M:%S')} {m}"; print(line, flush=True)
    with open(LOG, "a") as f: f.write(line + "\n")

def forward(body: bytes) -> bytes:
    req = urllib.request.Request(UPSTREAM, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r: return r.read()

def rpc(method, params):
    return json.loads(forward(json.dumps({"jsonrpc": "2.0", "id": 99, "method": method, "params": params}).encode()))["result"]

def decode_nonce_and_sender_nonce(raw_hex: str):
    raw = bytes.fromhex(raw_hex[2:] if raw_hex.startswith("0x") else raw_hex)
    if raw[0] in (0x01, 0x02, 0x03, 0x04):      # typed tx: type byte then rlp list; nonce is field 1
        fields = rlp.decode(raw[1:])
        nonce = int.from_bytes(fields[1], "big") if fields[1] else 0
    else:                                        # legacy: nonce is field 0
        fields = rlp.decode(raw)
        nonce = int.from_bytes(fields[0], "big") if fields[0] else 0
    return nonce

SENDER = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"   # anvil account 0, the relayer's signer

def handle_one(obj):
    method = obj.get("method")
    if method == "eth_sendRawTransaction":
        with lock:
            stats["send_raw"] += 1
            failing = time.time() < state["fail_send_until"]
        if failing:
            with lock: stats["send_503"] += 1
            raise TransportError()
        try:
            nonce = decode_nonce_and_sender_nonce(obj["params"][0])
        except Exception as e:
            log(f"nonce decode failed: {e!r}"); nonce = None
        if nonce is not None:
            pending = int(rpc("eth_getTransactionCount", [SENDER, "pending"]), 16)
            with lock: stats["max_nonce_seen"] = max(stats["max_nonce_seen"], nonce)
            if nonce > pending:
                with lock:
                    stats["send_nonce_too_high"] += 1
                    if len(stats["rejected_nonces"]) < 400: stats["rejected_nonces"].append(nonce)
                if stats["send_nonce_too_high"] in (1, 2, 5, 10, 25, 50, 100, 200, 400):
                    log(f"strict nonce: rejected nonce {nonce} (pending {pending}); rejections so far {stats['send_nonce_too_high']}")
                return {"jsonrpc": "2.0", "id": obj.get("id"), "error": {"code": -32000, "message": "nonce too high"}}
        resp = json.loads(forward(json.dumps(obj).encode()))
        with lock:
            if "error" in resp: stats["send_other_error"] += 1; log(f"anvil send error: {resp['error'].get('message')}")
            else: stats["send_ok"] += 1
        return resp
    return json.loads(forward(json.dumps(obj).encode()))

class TransportError(Exception): pass

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        with lock: body = json.dumps({**stats, "failing_now": time.time() < state["fail_send_until"]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); body = self.rfile.read(n)
        if self.path.startswith("/control"):
            c = json.loads(body); secs = float(c.get("fail_send_for", 0))
            with lock: state["fail_send_until"] = time.time() + secs
            log(f"control: eth_sendRawTransaction will get HTTP 503 for the next {secs} s")
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok"); return
        try:
            obj = json.loads(body)
            out = [handle_one(o) for o in obj] if isinstance(obj, list) else handle_one(obj)
            data = json.dumps(out).encode(); code = 200
        except TransportError:
            data = b"proxy: simulated upstream outage"; code = 503
        except Exception as e:
            log(f"proxy error: {e!r}"); data = json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": f"proxy: {e}"}}).encode(); code = 200
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def log_message(self, *a): pass

if __name__ == "__main__":
    log(f"proxy843 up: upstream {UPSTREAM}, strict nonce on, no outage scheduled")
    ThreadingHTTPServer(("0.0.0.0", 8546), H).serve_forever()
