# PR #862 against this reproduction, on v1.9.0 (2026-10-25)

[OpenZeppelin Relayer PR #862](https://github.com/OpenZeppelin/openzeppelin-relayer/pull/862) at `bcb5129`, rebased locally onto the v1.9.0 tag (`306f07e`), run twice against the run-2 setup of this repository, with stock `openzeppelin/openzeppelin-relayer:v1.9.0` (sha256:3ceb3986c636...) run twice as the control. Runs were interleaved (v1.9.0, branch, v1.9.0, branch). All four use the same config as the 2026-10-10 runs in [../pr862](../pr862), with the anvil network tagged `rollup`, `arbitrum-based` and `no-mempool` ([config-tagged.json](config-tagged.json)).

Driver: `PERIOD=2 OUTAGE=60 TOTAL=720 python3 run_repro.py` (30 transfers a minute for 12 minutes, a 60 s window of HTTP 503 on `eth_sendRawTransaction` from t+40 s, nonce-too-high gating in the proxy, one provider, speed `fast`), then four minutes of sampling with no new transactions (`*-post.log`).

| | v1.9.0 run 1 | v1.9.0 run 2 | #862 on v1.9.0 run 1 | #862 on v1.9.0 run 2 |
|---|---|---|---|---|
| Drift samples, every 30 s | 0, 10, 25, 33 until t+360 s, then rising to 59 | 0, 10, 25, 33 until t+270 s, then rising to 64 (63 when intake stopped) | 0, 10, 25, then 0 from t+120 s (one sample of 1 at t+480 s) | 0, 10, 25, then 0 from t+120 s |
| Drift over the last 300 s of intake | 38 to 59 | 51 to 64 | 0 to 1 | 0 |
| `sent` records with `sent_at: null` when intake stopped | 59 | 62 | 0 | 0 |
| Final, of 360 | 360 confirmed, 0 failed | 360 confirmed, 0 failed | 360 confirmed, 0 failed | 360 confirmed, 0 failed |
| End of intake to an empty queue | 155 to 186 s | 156 to 187 s | under 30 s | under 30 s |
| `transaction stuck in Sent, queuing resubmit job with repricing` | 2,186 | 2,405 | 4 | 5 |
| `drain chain advanced: enqueueing submit for next nonce` | n/a | n/a | 33 | 34 |
| `stuck Sent tx is queued behind the chain head on Arbitrum; skipping resubmit` | n/a | n/a | 37 | 36 |
| `transaction already imported` | 0 | 0 | 2 | 4 |
| Occurrences of `nonce too high` | 4,252 | 4,690 | 39 | 42 |

On v1.9.0, between t+360 s and t+690 s the chain head advanced about 13 nonces per 30 s against 15 new transfers per 30 s (147 to 286 and 134 to 282), so the drift kept growing instead of holding at 33 as it did on v1.8.0.

The driver's start line reads "relayer v1.8.0"; that is a fixed string in run_repro.py. The relayer version is the service_version=1.9.0 line at the top of each run's relayer excerpt.

The driver's verdict line reads INCONCLUSIVE for all four runs: its check looks for a drift that is above zero and never shrinks over the last 300 s; on v1.9.0 the drift grew with one or two small dips, and on the branch it was 0.

Rebase: the seven commits apply onto `306f07e` with one conflict, in the first commit (`415d340`), in `src/domain/transaction/evm/evm_transaction.rs`. #847 (configurable status-check delay) changed the same `constants` import list, the test imports and three submit tests, where it added a `get_by_name` expectation and the PR had switched to `default_mock_network()`; both were kept ([rebase-range-diff.txt](rebase-range-diff.txt)). No conflict in the logic itself. The PR's `tokio` `test-util` dev-dependency is already on v1.9.0, so that hunk drops out. Two test helpers the PR adds build `EvmNetworkConfig` without the `status_check` field that #847 added, so the tests do not compile until `status_check: None` is added ([test-fixup.diff](test-fixup.diff)); with that, the 234 tests under `domain::transaction::evm` pass. The image used for the runs was built before that test-only change.

Build: v1.9.0's own `Dockerfile.production` under BuildKit with only the target cache id changed ([Dockerfile-build.diff](Dockerfile-build.diff)); the openssl and pnpm changes needed on 2026-10-10 are already in v1.9.0. The image reports `service_version=1.9.0`, links `libssl.so.4` and `libcrypto.so.4` from the image, and confirmed one transfer in a start check.

Differences from Arbitrum: the proxy rejects a gapped nonce at once instead of holding it for about a second, there is no sequencer feed, the chain is anvil with 2 s blocks, and nothing restarts during the window.

Files per run (`v190-r1`, `v190-r2`, `pr862v190-r1`, `pr862v190-r2`): `-run.log` (driver), `-post.log` (after intake), `-proxy.log`, `-counts.txt` (key log lines and webhook statuses), `-relayer-excerpt.log` (the first 25 lines of each key message).
