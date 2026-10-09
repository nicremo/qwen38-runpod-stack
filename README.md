<div align="center">

# qwen38-runpod-stack

**One command spins up Qwen3.8-27B (abliterated, NVFP4) on a rented Blackwell GPU and wires it into your local coding agent.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Model: Apache 2.0](https://img.shields.io/badge/Model-Apache%202.0-blue.svg)](https://huggingface.co/Qwen/Qwen3.8-27B)
[![Shell](https://img.shields.io/badge/shell-bash-121011?logo=gnu-bash&logoColor=white)](bin/)
[![Python](https://img.shields.io/badge/python-3.8%2B-3776AB?logo=python&logoColor=white)](bin/qwen38-proxy)
[![Platform](https://img.shields.io/badge/platform-macOS-000000?logo=apple&logoColor=white)](#requirements)
[![Engine: SGLang](https://img.shields.io/badge/engine-SGLang-6f42c1)](https://github.com/sgl-project/sglang)
[![GPU: RTX PRO 6000](https://img.shields.io/badge/GPU-RTX%20PRO%206000-76b900?logo=nvidia&logoColor=white)](https://www.runpod.io/gpu-models/rtx-pro-6000)
[![~150 tok/s](https://img.shields.io/badge/measured-~150%20tok%2Fs-brightgreen)](docs/PERFORMANCE.md)

</div>

---

A rented Blackwell GPU is cheaper than a hosted uncensored API once you actually
use it, and it is roughly ten times faster than the same model on a laptop. This
repo makes that a single command: it starts the pod, serves the model over an
OpenAI-compatible API, and gives your coding agent a **fixed local URL** that
always points at whatever pod is currently running. Layered shutdown protection
reduces the risk of forgotten pods draining your balance, including a
server-side timer when the installed RunPod CLI supports it.

Measured on 2026-08-23: **~150 tok/s** on an RTX PRO 6000 with SGLang plus
DFlash2 speculative decoding, single stream, 262K context. See
[docs/PERFORMANCE.md](docs/PERFORMANCE.md).

## Table of contents

- [Why](#why)
- [How it fits together](#how-it-fits-together)
- [What's inside](#whats-inside)
- [Requirements](#requirements)
- [Install](#install)
- [Usage](#usage)
- [Cost control](#cost-control)
- [Security](#security)
- [The model](#the-model)
- [Troubleshooting](#troubleshooting)
- [License](#license)

## Why

Three separate worlds exist and nobody connects them: run an uncensored model
locally (slow), rent a GPU to host a model (no privacy story, fiddly), and plug a
local model into a coding agent (usually a censored model). This stack does all
three with an abliterated model, and it does the math on when renting beats a
hosted API.

| Where | Speed (Qwen3.8-27B, Q4/NVFP4) | Notes |
|---|---|---|
| MacBook Pro M2 Max 32GB | ~14 tok/s | free, private, but slow for an agent |
| 16GB gaming GPU | ~3 tok/s | technically runs, unusable for agents |
| **RunPod RTX PRO 6000 (this repo)** | **~150 tok/s** | SGLang + NVFP4 + DFlash2 |
| Hosted uncensored API | ~35 tok/s | convenient, more expensive at volume |

## How it fits together

```
  pi / any OpenAI-compatible agent
              │
              ▼
   http://127.0.0.1:8388/v1      ← fixed local address, never changes
              │
      qwen38-proxy  (LaunchAgent)
              │  reads ~/.runpod/current-pod, injects the API key
              ▼
   https://<pod-id>-8000.proxy.runpod.net/v1   ← changes on every launch
              │
        SGLang on a RunPod Blackwell GPU
```

`qwen38fast` / `qwen38pi` writes the running pod's id to `~/.runpod/current-pod`.
The proxy reads it, so your agent config points at `127.0.0.1:8388` once and
never has to change, even though the pod URL is different every time. No pod
running → the proxy returns a clean 503 telling you to start one.

## What's inside

| File | Purpose |
|---|---|
| `bin/qwen38fast` | Full stack: SGLang API **plus** OpenWebUI (port 8080). Starts and waits until usable |
| `bin/qwen38pi` | Lean: SGLang API only, for a coding agent. No OpenWebUI, ready sooner |
| `bin/qwen38bench` | Measures decode rate, TTFT and accepted-token length (discards a warmup run) |
| `bin/qwen38-proxy` | Local proxy on `127.0.0.1:8388` that always targets the running pod |
| `bin/rp` | `runpodctl` wrapper that adds a server timer when supported and preserves the local reaper fallback |
| `bin/runpod-reaper` | LaunchAgent backstop that kills forgotten pods after 1h |
| `scripts/bootstrap-sglang-openwebui.sh` | Runs inside the pod: downloads weights, starts SGLang (optionally OpenWebUI) |
| `launchagents/*.template` | macOS LaunchAgents for proxy and reaper; `__HOME__` is filled in at setup |
| `pi/models.runpod.json` | The provider block for `~/.pi/agent/models.json` |
| `create-templates.sh` | Creates the two RunPod templates and prints their ids |
| `setup.sh` | Installs everything for the current user |

## Requirements

- [`runpodctl`](https://github.com/runpod/runpodctl) installed and logged in
- A Hugging Face token in `~/.cache/huggingface/token` (the default model is not
  gated, but a token gives faster, rate-limit-free downloads)
- The RunPod SSH key in `~/.runpod/ssh/runpodctl-ssh-key` (only needed for the
  OpenWebUI restart in the full stack)
- Python 3, `base64`, `curl`
- For the agent path: [pi](https://pi.dev) (or any OpenAI-compatible agent)
- macOS for the LaunchAgents (the scripts themselves are portable)

## Install

```bash
git clone https://github.com/nicremo/qwen38-runpod-stack.git
cd qwen38-runpod-stack

./setup.sh                       # bin → ~/.local/bin, load LaunchAgents
./create-templates.sh            # create the RunPod templates, prints two ids
export QWEN38_TEMPLATE=<id>       # the full-stack id
export QWEN38_TEMPLATE_PI=<id>    # the pi id
# copy the block from pi/models.runpod.json into ~/.pi/agent/models.json
```

You can also hardcode the template ids in `bin/qwen38fast` instead of exporting
the env vars.

**Bootstrap changes:** `./setup.sh` copies this checkout's bootstrap to
`~/.local/share/qwen38-runpod-stack/`, which `qwen38fast` uses when creating
new pods. Set `QWEN38_BOOTSTRAP=/path/to/bootstrap-sglang-openwebui.sh` to test
an uninstalled working-tree version. For deployments launched from the RunPod
web UI, run `./create-templates.sh` again and use the newly printed template IDs:
existing RunPod templates retain their embedded bootstrap code.

**Dependency isolation:** On full-stack deployments, OpenWebUI is installed
into its own virtual environment (`/workspace/openwebui-venv`) using the `uv`
bundled in the SGLang image. It defaults to OpenWebUI `0.11.4`; set
`OPENWEBUI_VERSION` at pod creation to select a different version. SGLang's
Python/PyTorch/NCCL environment is not modified by the bootstrap. Installing
OpenWebUI into the serving environment while SGLang starts can replace NCCL
libraries and crash DeepEP's startup check.

## Usage

Lean path for a coding agent:

```bash
qwen38pi                                 # starts, ready as soon as the API answers
pi --model runpod/qwen38-uncensored      # work with it
qwen38pi stop                            # shut the pod down
```

With a web UI (OpenWebUI, opens in your browser):

```bash
qwen38fast                               # starts, opens OpenWebUI
qwen38fast status                        # what's running, what it costs
qwen38fast stop
```

### Debug SSH (off by default)

SSH is disabled by default, including in newly created templates. This keeps the
debugging service off unless it is explicitly required. To enable it for one new
pod, use:

```bash
QWEN38_ENABLE_SSH=1 qwen38fast
```

The launcher passes this through as `ENABLE_SSH=1`; the bootstrap then installs
and starts `sshd` before model downloads. Your RunPod account must have its SSH
key registered. Leave the variable unset for normal launches.

Measure the real decode rate:

```bash
qwen38bench                              # picks the running pod, 5 runs + warmup
```

## Cost control

Cost protection is layered:

1. **`rp` wrapper** — detects whether `runpodctl` supports
   `--terminate-after` and adds it when available.
2. **Server-side timer** — when supported, fires even with the Mac asleep.
3. **`runpod-reaper`** — remains enabled and, while the Mac is awake, kills any
   pod older than 1h that isn't named `keep-*`.

If the installed CLI has no server-side timer flag, `rp` warns and does not add
an unsupported option or exempt long-running pods from the reaper. Protection
is then local only and cannot fire while the Mac is asleep.

Full details in [docs/COST_CONTROL.md](docs/COST_CONTROL.md).

## Security

- **No keys, no tokens, no personal paths in this repo.** `qwen38fast` generates
  the API key locally and hands it to SGLang, so the publicly reachable pod port
  isn't open to the internet.
- `.gitignore` keeps keys, tokens and pod state out.
- The proxy binds to `127.0.0.1` only.

> The default model has its safety alignment removed. It is intended for
> research, red-teaming and your own responsible use. What you do with it is on you.

## The model

Default is `sakamakismile/Huihui-Qwen3.8-27B-abliterated-NVFP4`, a uniform
`nvfp4-pack-quantized` checkpoint. Point at another with `--model` or the
`QWEN38_MODEL` variable.

**Important:** not every NVFP4 checkpoint works with SGLang. A `mixed-precision`
compressed-tensors checkpoint loads **silently unquantized** in SGLang
([sgl-project/sglang#32736](https://github.com/sgl-project/sglang/issues/32736)),
which throws away the whole FP4 speedup without any error. Use a uniform
`nvfp4-pack-quantized` build. The reasoning behind every choice is in
[docs/PERFORMANCE.md](docs/PERFORMANCE.md).

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Pod URL returns 404 | port not exposed at creation | expose `8000`/`8080` when the pod is created, never edit a running pod |
| Model runs but is slow like BF16 | `mixed-precision` checkpoint in SGLang | use a `nvfp4-pack-quantized` build |
| Endless thinking, no answer | `reasoning_effort` defaults high | pass `enable_thinking: false` or a lower effort |
| HTTP 403 from the pod URL | RunPod proxy rejects the default urllib UA | send a browser User-Agent (the proxy already does) |
| Editing a running pod wiped the model | RunPod recreates the container | put models on the `/workspace` volume, or expose ports at creation |
| SGLang crashes in `deep_ep.check_nccl_so()` with `(deleted)` | concurrent pip install into SGLang Python environment | redeploy with isolated OpenWebUI environment; do not disable NCCL checks |

## License

MIT, see [LICENSE](LICENSE). The model itself is Apache 2.0.
