"""Reproduce OpenZeppelin Relayer issue #843: a nonce-too-high jam whose drift region is fully
occupied by Sent records, which disarms the 1.7.0 recovery paths.

Stack: anvil (auto-mining every 2 s) behind proxy843.py, which (a) rejects any raw transaction
whose nonce is above the sender's pending nonce with "nonce too high" (strict-nonce rollup
behaviour) and (b) returns HTTP 503 to eth_sendRawTransaction during a controlled outage window.
Relayer v1.8.0 talks only to the proxy, single provider.

Sequence: steady producer (one transfer every PERIOD s) for the whole run; after WARMUP s open an
OUTAGE s window of 503s so some submit jobs exhaust their retries without ever broadcasting;
keep producing; sample on-chain nonce vs the relayer's highest allocated nonce every 30 s.
Verdict REPRODUCED if, for the last OBSERVE s, drift (counter - on_chain) never shrinks and the
relayer log never contains "rewound nonce counter". Logs to logs/run.log.
"""
import json, time, subprocess
import httpx

RELAYER = "http://127.0.0.1:18781"; KEY = "repro843-api-key-0123456789abcdef"
ANVIL = "http://127.0.0.1:18745"; PROXY = "http://127.0.0.1:18746"
RID = "anvil-strict"; TO = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
SENDER = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
import os
PERIOD = float(os.environ.get("PERIOD", "5")); WARMUP = 40; OUTAGE = int(os.environ.get("OUTAGE", "90")); TOTAL = int(os.environ.get("TOTAL", "900")); OBSERVE = 5 * 60
LOG = open(__file__.rsplit("/", 1)[0] + "/logs/run.log", "a")

def log(m):
    line = f"{time.strftime('%H:%M:%S')} {m}"; print(line, flush=True); LOG.write(line + "\n"); LOG.flush()

def rpc(method, params=None):
    j = httpx.post(ANVIL, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []}, timeout=20).json()
    if "error" in j: raise RuntimeError(f"{method}: {j['error']}")
    return j["result"]

def api(method, path, body=None):
    r = httpx.request(method, RELAYER + path, headers={"Authorization": f"Bearer {KEY}"}, json=body, timeout=30)
    try: return r.status_code, r.json()
    except Exception: return r.status_code, {"raw": r.text[:200]}

def on_chain_nonce():
    return int(rpc("eth_getTransactionCount", [SENDER, "latest"]), 16)

def relayer_view():
    """Highest nonce the relayer has allocated, and a status histogram, from its transaction list."""
    items = []; page = 1
    while True:
        code, j = api("GET", f"/api/v1/relayers/{RID}/transactions?page={page}&per_page=100")
        data = j.get("data") or []
        items += data
        if len(data) < 100 or page > 20: break
        page += 1
    hist = {}; top = -1; sent_null = 0; reasons = {}
    for t in items:
        s = t.get("status"); hist[s] = hist.get(s, 0) + 1
        n = t.get("nonce")
        if isinstance(n, int): top = max(top, n)
        if s == "sent":
            r = (t.get("status_reason") or "")[:24]; reasons[r] = reasons.get(r, 0) + 1
            if t.get("sent_at") in (None, ""): sent_null += 1
    return top, hist, sent_null, reasons, len(items)

def relayer_log_has(pattern):
    out = subprocess.run(["docker", "logs", "repro843-relayer"], capture_output=True, text=True).stdout + subprocess.run(["docker", "logs", "repro843-relayer"], capture_output=True, text=True).stderr
    return pattern in out, out.count(pattern)

def stats():
    try: return httpx.get(PROXY + "/stats", timeout=5).json()
    except Exception as e: return {"err": str(e)}

def main():
    log("=== repro #843 start; relayer v1.8.0 behind strict-nonce proxy, single provider")
    t0 = time.time(); submitted = 0; outage_opened = False; samples = []
    next_submit = t0; next_sample = t0 + 30
    while time.time() - t0 < TOTAL:
        now = time.time()
        if not outage_opened and now - t0 >= WARMUP:
            httpx.post(PROXY + "/control", json={"fail_send_for": OUTAGE}, timeout=5); outage_opened = True
            log(f"--- outage window opened for {OUTAGE} s (eth_sendRawTransaction -> HTTP 503)")
        if now >= next_submit:
            code, j = api("POST", f"/api/v1/relayers/{RID}/transactions", {"to": TO, "value": 1, "data": "0x", "speed": "fast", "gas_limit": 21000})
            submitted += 1
            if code != 200 and code != 201: log(f"submit {submitted} -> {code} {json.dumps(j)[:160]}")
            next_submit += PERIOD
        if now >= next_sample:
            oc = on_chain_nonce(); top, hist, sent_null, reasons, n = relayer_view()
            drift = (top + 1) - oc if top >= 0 else 0
            samples.append((int(now - t0), oc, top + 1, drift))
            rew, _ = relayer_log_has("rewound nonce counter")
            log(f"t+{int(now-t0)} s: submitted {submitted}, on-chain nonce {oc}, relayer next nonce {top+1}, drift {drift}, statuses {json.dumps(hist)}, sent with null sent_at {sent_null}, sent reasons {json.dumps(reasons)}, rewind logged {rew}, proxy {json.dumps({k: v for k, v in stats().items() if k != 'rejected_nonces'})}")
            next_sample += 30
        time.sleep(0.5)
    oc = on_chain_nonce(); top, hist, sent_null, reasons, n = relayer_view()
    tail = [s for s in samples if s[0] >= TOTAL - OBSERVE]
    drifts = [s[3] for s in tail]
    rewound, rew_n = relayer_log_has("rewound nonce counter")
    gaps_logged, _ = relayer_log_has("nonce gaps confirmed below tx")
    never_shrinks = all(b >= a for a, b in zip(drifts, drifts[1:])) and (drifts[-1] if drifts else 0) > 0
    if never_shrinks and not rewound:
        verdict = f"REPRODUCED: drift {drifts[0]} -> {drifts[-1]} over the last {OBSERVE} s without shrinking; 'rewound nonce counter' never logged; {hist.get('sent',0)} records sent ({sent_null} with null sent_at), on-chain nonce {oc}, relayer next nonce {top+1}"
    elif rewound:
        verdict = f"NOT REPRODUCED: relayer logged 'rewound nonce counter' {rew_n} time(s); final drift {drifts[-1] if drifts else '?'}"
    else:
        verdict = f"INCONCLUSIVE: drift samples {drifts}; rewind logged {rewound}; gaps logged {gaps_logged}"
    log(f"final statuses {json.dumps(hist)}; sent reasons {json.dumps(reasons)}; proxy {json.dumps(stats())[:600]}")
    log(f"=== VERDICT: {verdict}")

if __name__ == "__main__":
    main()
