# Reproduction of OpenZeppelin Relayer issue #843 on v1.8.0

A `nonce too high` jam whose drift region is fully occupied by `Sent` records, so the 1.7.0 recovery paths never fire and the drift only grows: https://github.com/OpenZeppelin/openzeppelin-relayer/issues/843

This runs the unmodified `openzeppelin/openzeppelin-relayer:v1.8.0` image against anvil through `proxy843.py`, which does two things a strict-nonce rollup and a flaky provider would do: it rejects any raw transaction whose nonce is above the sender's pending nonce with a JSON-RPC error `nonce too high`, and it returns HTTP 503 to `eth_sendRawTransaction` during a window the driver opens through `POST /control`. One provider, no failover. The driver submits transfers at a fixed rate throughout and samples the drift (relayer's next nonce minus on-chain nonce) every 30 s.

## What it shows (2026-10-06)

Run 1, 12 transactions a minute, 90 s outage (`logs/run1-12tx-per-min.log`): the 18 transactions prepared during the window had their submit jobs abandoned on the first transport error (`max attempts reached, failing job job_type=Transaction Submission ... max_attempts=0`), leaving `sent` records with `sent_at: null`. Every later transaction was rejected `nonce too high` and parked in `sent` with reason `Nonce too high (attempt N)`. The health job logged `no nonce gaps detected` and `gaps_filled=0` on every run; `rewound nonce counter` never appeared. Drift held at 18 for fifteen minutes: at this rate the blind resubmits landed slots as fast as the producer added them. The backlog cleared within two minutes of the producer stopping.

Run 2, 30 transactions a minute, 60 s outage (`logs/run2-30tx-per-min.log`): same mechanism with intake above the resubmit-governed drain. Drift 0, 10, 25, 33 during and just after the window, flat for three minutes, then 39, 40, 45, 45, 45, 46, 51, 51, 57, 58, 58, 60 over six minutes, never decreasing. 69 `sent` records with null `sent_at` at the end; 1,807 `nonce too high` rejections at the proxy; 1,797 resubmit jobs queued; 215 `no nonce gaps detected`; 0 rewinds (`logs/relayer-run2-counts.txt`).

## Why, as far as I can tell from the 1.8.0 source

- `src/constants/worker.rs`: `WORKER_TRANSACTION_SUBMIT_RETRIES = 0`. A submit job that hits a transport error is abandoned; the record it was broadcasting stays `Sent` with no `sent_at`, and its nonce slot stays occupied by a payload the chain never saw.
- `src/domain/transaction/evm/evm_transaction.rs`: `NonceTooHigh` on submission or resubmission tracks the attempt and leaves the record in `Sent`.
- `src/domain/relayer/evm/nonce.rs`, `try_rewind_counter`: the rewind is bounded by the highest occupied slot of any status and returns silently when the target equals the observed counter, which is always the case once the region is full.
- `src/domain/transaction/common.rs`, `is_active_nonce_status`: `Sent` is active, so `detect_nonce_gaps` and `detect_nonce_gap_ahead` report no gaps.

I did not instrument those functions; the evidence is the absence of the rewind and gap-fill lines across 27 minutes of jammed state while the health job ran continuously.

Differences from the original report: anvil with 2 s blocks and a proxy emulating strict nonces, instead of Arbitrum Sepolia; a clean 60 or 90 s outage window rather than a continuously flaky provider; minutes rather than days; drift in the tens rather than hundreds. Same state, same log signature, same absence of recovery.

## Run it

Requirements: Docker with Compose, Python 3.10+, `pip install httpx eth-account`. The proxy container installs `rlp` at start to decode the nonce from the raw transaction.

```bash
python3 generate_keystore.py          # keystore for anvil's public dev account #0
touch logs/receiver.log               # bind-mounted into the receiver; must exist as a file
docker compose -p repro843 up -d      # anvil (2 s blocks), redis, receiver, proxy, relayer 1.8.0
# wait ~45 s for "all health checks passed" in: docker logs repro843-relayer
PERIOD=2 OUTAGE=60 TOTAL=720 python3 run_repro.py     # run 2; PERIOD=5 OUTAGE=90 TOTAL=900 is run 1
docker compose -p repro843 down -v
```

Ports on localhost: 18745 (anvil, direct), 18746 (proxy; `GET /` shows the counters, `POST /control {"fail_send_for": 60}` opens an outage), 18781 (relayer API). The API key and webhook signing key are throwaway values for this test.

## Files

- `docker-compose.yml`: anvil 1.8.1 (`--block-time 2`), Redis, the receiver, `proxy843.py`, `openzeppelin/openzeppelin-relayer:v1.8.0`.
- `proxy843.py`: strict-nonce rejection plus the controllable outage window.
- `config/config.json`: one EVM relayer with `eip1559_pricing`, local keystore signer, inline network pointing at the proxy.
- `run_repro.py`: the producer, the outage trigger, the drift sampler, and the verdict.
- `logs/`: both runs' driver output, the relayer's decisive lines, and the log-line counts.

MIT. Not affiliated with OpenZeppelin.
