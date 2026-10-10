# PR #844 against this reproduction (2026-10-07 and 2026-10-08)

[OpenZeppelin Relayer PR #844](https://github.com/OpenZeppelin/openzeppelin-relayer/pull/844) ("fix(evm): rewind nonce counter past slots rejected and never broadcast") at `fa2495c`, built as is on its pinned 1.91.1 toolchain, run twice against the run-2 setup of this repository with the published config (no network tags), and stock `openzeppelin/openzeppelin-relayer:v1.8.0` as a control on the same setup. The branch's base differs from v1.8.0 only in the Stellar status polling, so the EVM path matches 1.8.0.

Driver: `PERIOD=2 OUTAGE=60 TOTAL=720 python3 run_repro.py`. For PR run 2 and the control, four minutes of sampling followed with no new transactions (`*-post.log`).

| | v1.8.0 | PR #844 run 1 | PR #844 run 2 |
|---|---|---|---|
| Drift over the last 300 s of intake | 40 to 47 | 51 to 54 | 63 to 88 |
| Rewinds during intake | 0 | 0 (223 `cannot rewind`) | 0 (239 `cannot rewind`) |
| After intake stopped | all 360 confirmed by t+128 s, 0 failed | not observed | rewind 34 s after the producer stopped: 78 transactions set to `failed`, 282 confirmed, no failed webhook |

While transfers kept arriving, the rewind was attempted on every health run and blocked by the newest slot each time (`cannot rewind ... blocking_nonce=Some(observed - 1)`): the transaction created last has not yet collected `MAX_NONCE_TOO_HIGH_RETRIES` rejections when the health check looks at it. Once intake stopped, the rewind reclaimed the whole region to `failed` through `partial_update`, without a notification.

Files: `pr844-r1-*`, `pr844-r2-*` and `v180-ctl-*`: driver log, post-run samples where taken, proxy log, counts of key log lines and webhook statuses, relayer log excerpt.
