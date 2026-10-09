# Cost control on RunPod

On 2026-08-15 two forgotten pods ran for 24 hours doing nothing. Everything here
exists because of that.

## The rule

**Always create pods through `rp`, including quick tests.** It adds a
server-side shutdown timer when the installed `runpodctl` supports one and
keeps the local reaper fallback active on versions that do not:

```bash
rp pod create ...                          # 1h local-reaper limit
RUNPOD_MAX_AGE_HOURS=6 rp pod create ...   # requests a 6h window
rp 6h pod create ...                       # same, shorter
```

`rp` lives in `~/.local/bin/rp` and passes everything through to `runpodctl`
unchanged. On `pod create`, it first inspects the command's help output. If
`--terminate-after` is available and no timer was supplied, it adds one. If the
flag is unavailable, it emits a warning and lets the local reaper enforce its
one-hour limit while the Mac is running.

You can check whether the installed CLI exposes a server-side timer:

```bash
runpodctl pod create --help | grep -- --terminate-after
```

## The three layers

| Layer | What | Fires when |
|---|---|---|
| 1. `rp` wrapper | detects and sets a supported timer flag | every `rp pod create` |
| 2. `--terminate-after` | server-side at RunPod | when the installed CLI supports it, even with the Mac asleep |
| 3. `runpod-reaper` | LaunchAgent, every 10 min, kills anything over 1h | while the Mac is running, including pods from the web console |

The server-side timer is the only layer that works without a running Mac, but
not every `runpodctl` release exposes it. It also can't be verified through
`pod get`, which returns no `terminateAfter`. That's why the reaper stays active
instead of trusting the timer. When the flag is unavailable, protection is
local only and cannot fire while the Mac is asleep or offline.

For windows longer than one hour, `rp` adds a `keep-` name prefix only when a
server-side timer is present. If the CLI has no timer support, the requested
longer window cannot be safely guaranteed, so the reaper continues to enforce
one hour. Manually naming a pod `keep-*` bypasses that protection and should be
reserved for actively monitored runs.

Check the reaper by hand:

```bash
RUNPOD_REAPER_DRY_RUN=1 runpod-reaper && cat ~/.runpod/reaper.log
```

The reaper only writes to the log on errors or kills. A quiet log means all is
well, not that it isn't running. Whether it runs shows in
`launchctl list | grep runpod`.

## What RunPod can't do

**There is no global auto-terminate setting.** An idle timeout exists only for
serverless endpoints, not for pods. Some CLI releases expose
`--terminate-after`; others do not. `runpodctl user` is read-only. The only
account-wide cap is the spend limit, but that only bites once the month is
already burned.

## Prices, as of 2026-08-22

From the account's GraphQL API, field `lowestPrice.uninterruptablePrice`. That's
the **cheapest** on-demand price for the card, i.e. the Community Cloud price
where Community is available. Secure is higher: the RTX PRO 6000 ran on
2026-08-22 in Secure for 2.09 USD/h against 1.69 in the table below, about a 24%
markup.

| GPU | VRAM | USD/h | good for NVFP4 |
|---|---|---|---|
| RTX 3090 | 24 GB | 0.22 | no |
| RTX 4090 | 24 GB | 0.34 | no |
| RTX 5090 | 32 GB | 0.69 | yes |
| RTX PRO 6000 | 96 GB | 1.69 | yes |
| H100 PCIe | 80 GB | 1.99 | no, SM90 |
| H100 SXM | 80 GB | 2.69 | no, SM90 |
| H200 SXM | 141 GB | 3.59 | no, SM90 |
| B200 | 180 GB | 5.98 | yes |
| B300 | 288 GB | 6.94 | yes |

Community isn't always available. `qwen38fast` tries Community first and falls
back to Secure automatically, at which point the higher price applies.

Query prices yourself:

```bash
KEY=$(python3 -c "import re;print(re.search(r\"apikey = '([^']+)'\",open('$HOME/.runpod/config.toml').read()).group(1))")
curl -s -X POST "https://api.runpod.io/graphql?api_key=$KEY" -H 'Content-Type: application/json' \
  -d '{"query":"query { gpuTypes { displayName memoryInGb lowestPrice(input:{gpuCount:1}) { uninterruptablePrice } } }"}'
```

`runpodctl gpu list` shows availability and stock status but **no prices**.

## Check running costs

```bash
qwen38fast status                  # pods plus balance plus current rate
runpodctl pod list -a              # including exited pods
runpodctl network-volume list      # volumes cost even without a running pod
```

Exited pods (`desiredStatus: EXITED`) cost nothing as long as no volume is
attached. Network volumes cost continuously, independent of any pod.
