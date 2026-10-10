# PR #862 against this reproduction (2026-10-10)

[OpenZeppelin Relayer PR #862](https://github.com/OpenZeppelin/openzeppelin-relayer/pull/862) ("fix(evm): Chain Arbitrum delivery to drain nonce-too-high jams") at `bcb5129`, run twice against the run-2 setup of this repository, with stock `openzeppelin/openzeppelin-relayer:v1.8.0` as a control. All three runs use the same config with the anvil network tagged `rollup`, `arbitrum-based` and `no-mempool` ([config-tagged.json](config-tagged.json)), because the branch's changes apply only to networks tagged `arbitrum-based`.

Build: the branch's own `Dockerfile.production` under BuildKit with two lines changed ([Dockerfile-build.diff](Dockerfile-build.diff)): `openssl-3.6-dev` instead of `openssl-dev` (without it the binary links libssl.so.4, which the image does not ship; see [#919](https://github.com/OpenZeppelin/openzeppelin-relayer/pull/919)) and `pnpm@10` (main already pins it). The branch reports `service_version=1.7.0` because it predates the version bump; its `src/` otherwise matches v1.8.0 plus the PR's seven commits.

Driver: `PERIOD=2 OUTAGE=60 TOTAL=720 python3 run_repro.py` (30 transfers a minute for 12 minutes, a 60 s window of HTTP 503 on `eth_sendRawTransaction` from t+40 s), then four minutes of sampling with no new transactions (`*-post.log`).

| | v1.8.0 | PR #862 run 1 | PR #862 run 2 |
|---|---|---|---|
| Drift samples, every 30 s | 0, 10, 25, then 33 until intake stopped | 0, 10, 25, then 0 from t+120 s | the same as run 1 |
| `sent` records with `sent_at: null` when intake stopped | 32 | 0 | 0 |
| Final, of 360 | 360 confirmed, 0 failed | 360 confirmed, 0 failed | 360 confirmed, 0 failed |
| End of intake to an empty queue | 61 to 92 s | under 30 s | under 30 s |
| Submit jobs failed on the first error in the 503 window | 30 | 30 | 30 |
| `transaction stuck in Sent, queuing resubmit job with repricing` | 1,360 | 4 | 4 |
| `drain chain advanced: enqueueing submit for next nonce` | n/a | 36 | 35 |
| `stuck Sent tx is queued behind the chain head on Arbitrum; skipping resubmit` | n/a | 38 | 37 |
| Lines containing `nonce too high` | 2,600 | 67 | 56 |

The driver's own verdict line reads INCONCLUSIVE for the two PR runs: its check looks for a drift that is above zero and never shrinks, and the drift there was 0.

In each PR run, two submit jobs failed just after the window with `transaction already imported` (anvil's answer to a duplicate), because the chain link had already sent their transactions; those transactions confirmed.

Differences from Arbitrum: the proxy rejects a gapped nonce at once instead of holding it for about a second, there is no sequencer feed, the chain is anvil with 2 s blocks, and nothing restarts during the window.

Files per run (`v180tag`, `pr862-r1`, `pr862-r2`): `-run.log` (driver), `-post.log` (after intake), `-proxy.log`, `-counts.txt` (key log lines and webhook statuses), `-relayer-excerpt.log`.
