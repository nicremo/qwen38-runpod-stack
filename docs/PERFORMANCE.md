# Qwen3.8-27B abliterated on RunPod, tuned for maximum decode rate

As of 2026-08-22. Everything here is sourced, references sit next to every number.

## TL;DR

```bash
qwen38fast                 # RTX PRO 6000 Blackwell, NVFP4, DFlash2, 4h window
qwen38bench                # measures what actually comes out
qwen38fast stop
```

Stack: SGLang on `lmsysorg/sglang:dev-qwen38-27b-dflash2`, model
`sakamakismile/Huihui-Qwen3.8-27B-abliterated-NVFP4`, draft `incoai/Qwen3.8-27B-DFlash2`.

## The four decisions and why

### 1. GPU: RTX PRO 6000 Blackwell 96GB, 1.69 USD/h

| Card | VRAM | RunPod on-demand | good for NVFP4 |
|---|---|---|---|
| RTX 5090 | 32 GB | 0.69 USD/h | yes, but context capped |
| **RTX PRO 6000** | **96 GB** | **1.69 USD/h** | **yes, full 262K context** |
| H100 SXM | 80 GB | 2.69 USD/h | no, SM90 has no FP4 tensor cores |
| H200 SXM | 141 GB | 3.59 USD/h | no, same reason |
| B200 | 180 GB | 5.98 USD/h | yes, not in the cookbook matrix |
| B300 | 288 GB | 6.94 USD/h | yes, cookbook cell exists |

NVFP4 needs Blackwell. That rules out H100 and H200 for the fast path no matter
the price. The RTX PRO 6000 and RTX 5090 share the GB202 chip and about 1.79 TB/s
bandwidth, but the PRO 6000 has three times the VRAM, so the full context fits.
The SGLang cookbook validates this exact card end-to-end; the B200 isn't in the
matrix at all.

### 2. Checkpoint: uniform NVFP4, not mixed-precision

The most popular abliterated build, `orcarouter/Qwen3.8-27B-Uncensored-NVFP4`, is
**unusable with SGLang**: its `format` is `mixed-precision`, and SGLang loads such
compressed-tensors checkpoints **completely unquantized** without saying so
(sgl-project/sglang#32736, open). The whole FP4 advantage would be gone, silently.
It's also gated, and an unapproved HF token gets HTTP 403 on `config.json`.

So the choice is:

| Checkpoint | Format | Size | MTP head | gated |
|---|---|---|---|---|
| `sakamakismile/Huihui-Qwen3.8-27B-abliterated-NVFP4` | `nvfp4-pack-quantized` | 20.6 GB | yes, BF16 separate | no |
| `sakamakismile/Qwen3.8-27B-AEON-ULTIMATE-UNCENSORED-NVFP4` | `nvfp4-pack-quantized` | 20.6 GB | yes | no |
| `orcarouter/Qwen3.8-27B-Uncensored-NVFP4` | `mixed-precision` | 23.4 GB | yes | **yes, 403** |
| `orcarouter/Qwen3.8-27B-Uncensored-FP8` | block-FP8 | 28.5 GB | yes | yes, access ok |

The abliteration is by huihui-ai, `sakamakismile` only quantized. Uniform
pack-quantized sidesteps the SGLang bug.

If you insist on the orcarouter NVFP4: accept the model-page terms and use
**vLLM instead of SGLang**, where the mixed-precision path is documented:

```bash
--speculative-config '{"method":"mtp","num_speculative_tokens":2}'
# and do NOT set --quantization or --kv-cache-dtype, that's in config.json
```

### 3. Engine: SGLang, not vLLM

For the same checkpoint on the same card, SGLang with trained draft models beats
vLLM's MTP by a wide margin. Measured from the cookbook (RTX 5090, ISL 8192 /
OSL 1024, concurrency 1):

- DFlash2, bf16 state: **4.92 ms TPOT at accept length 4.29** (best result on the card)
- NVFP4 + EAGLE/MTP: 152.9 tok/s (fp32 state) / 144.5 (bf16)
- FP8 + EAGLE/MTP: 106.3 / 116.1 tok/s

vLLM with MTP@3 goes from 72.0 to 117.3 tok/s on a 5090 per a community
measurement. For the RTX PRO 6000, daily.dev cites 150 to 220 tok/s with SGLang
plus speculation at full 262K context.

### 4. Speculation: DFlash2 as the default

Three options, all Apache 2.0:

| Method | Draft | Flags |
|---|---|---|
| MTP | in the checkpoint | `--speculative-algorithm EAGLE --speculative-num-steps 3 --speculative-eagle-topk 1 --speculative-num-draft-tokens 4` |
| DFlash2 | `incoai/Qwen3.8-27B-DFlash2` | `--speculative-algorithm DFLASH --speculative-num-draft-tokens 8` |
| DSpark | `RadixArk/Qwen3.8-27B-DSpark` | `--speculative-algorithm DSPARK`, window comes from the draft (gamma 7) |

Both draft checkpoints are trained on the **base** model; the target is
abliterated. Vocabulary and architecture are identical, so it runs, but the
accept length may be below the cookbook value. That's exactly why `qwen38bench`
measures the real accept length.

## Measured on 2026-08-23

RTX PRO 6000 Blackwell 96GB, SGLang `dev-qwen38-27b-dflash2`, checkpoint
`sakamakismile/Huihui-Qwen3.8-27B-abliterated-NVFP4` (uniform NVFP4), DFlash2
speculation, 262,144 context, `--mamba-ssm-dtype float32`, measured over the
RunPod proxy, ISL 8192 / OSL 1024, concurrency 1.

First series, right after start:

| Run | Decode | TTFT |
|---|---|---|
| 1 | 142.2 tok/s | 1412 ms |
| 2 | 143.3 tok/s | 1207 ms |
| 3 | 167.8 tok/s | 923 ms |

Median 143.3 tok/s, TPOT 6.98 ms.

Second series, about 20 minutes later on the same pod, five runs:

| Run | Decode | TTFT |
|---|---|---|
| 1 | 122.4 tok/s | 855 ms |
| 2 | 148.1 tok/s | 1168 ms |
| 3 | 152.3 tok/s | 1340 ms |
| 4 | 155.6 tok/s | 1086 ms |
| 5 | 150.7 tok/s | 1378 ms |

Median **150.7 tok/s**, TPOT 6.63 ms, `max_running_requests` 48. **This is the
headline number.**

Lesson: three runs aren't enough. The first run of each series dips even though
`qwen38bench` already discards a warmup, and the numbers keep climbing over the
first few minutes. To publish a number, run five and let the pod warm for a couple
of minutes first.

Context: the cookbook cites 4.92 ms TPOT for the 5090 with NVFP4 plus DFlash2, so
about 203 tok/s. We land below that, for two plausible reasons not yet measured
apart:

1. **The draft doesn't match exactly.** `incoai/Qwen3.8-27B-DFlash2` is trained on
   the base model, the target is abliterated. The accept length is likely below
   the cookbook's 4.29. Measuring it fails because the Prometheus endpoint stays
   empty without `--enable-metrics`, and the SGLang image ships no sshd.
2. **`--mamba-ssm-dtype`.** For DFlash2 on the 5090 the cookbook says `bfloat16`
   is faster. We run `float32`.

Open comparisons for a future run: `--spec mtp` vs `dflash2`, and `bfloat16` vs
`float32` for the state. Both need a server restart, i.e. a new pod.

## Traps that are waiting here specifically

| Trap | Symptom | Countermeasure |
|---|---|---|
| mixed-precision in SGLang | model runs but is slow, no error | only use `nvfp4-pack-quantized` |
| `reasoning_effort` default | model thinks forever, no answer | `enable_thinking: false` or lower effort per request |
| `--mamba-full-memory-ratio` default 0.9 | concurrency silently capped | 4.59 for the standard config |
| wrong tool parser | tool calls come as raw text | `qwen3_coder`, not `hermes` |
| MTP on FlashInfer | arity error in the prefill plan | `--attention-backend triton` as a fallback |
| H100 booked for NVFP4 | FP4 falls back to the slow Marlin path | book Blackwell or use an FP8 checkpoint |
| cold start measured | number 2 to 10x too low | `qwen38bench` discards the first run itself |
| Python urllib against the proxy | HTTP 403 from the RunPod proxy | send a browser User-Agent, `curl` is unaffected |
| SSH into the pod with the default configuration | connection refused | SSH is intentionally off by default; launch with `QWEN38_ENABLE_SSH=1 qwen38fast` when debugging is needed |

## What's wrong when you read it elsewhere

The widely cited **346 / 378 tok/s** from the LMSYS day-0 blog belong to
**Qwen3.8-2.4T-A95B** on **TP8 B300**, i.e. the large MoE across eight cards. They
have nothing to do with the 27B on a single GPU.

## Sources

- SGLang Cookbook Qwen3.8-27B: https://docs.sglang.io/cookbook/autoregressive/Qwen/Qwen3.8-27B
- LMSYS day-0 (the 2.4T model): https://www.lmsys.org/blog/2026-08-12-qwen3-8-day0-support
- SGLang mixed-precision bug: https://github.com/sgl-project/sglang/issues/32736
- vLLM recipes Qwen3.8-27B: https://recipes.vllm.ai/Qwen/Qwen3.8-27B
- orcarouter model card: https://huggingface.co/orcarouter/Qwen3.8-27B-Uncensored-NVFP4

## Fixed local URL: pod changes without touching config

The pod URL changes on every launch. To keep agent configs stable, a local proxy
with a fixed address sits in front:

```
pi / OpenCode / whatever
        |
        v
http://127.0.0.1:8388/v1        <- this line never changes
        |
   qwen38-proxy (LaunchAgent com.qwen38.proxy)
        |  reads ~/.runpod/current-pod, injects the API key
        v
https://<pod>-8000.proxy.runpod.net/v1
```

Parts:

| File | Purpose |
|---|---|
| `~/.local/bin/qwen38-proxy` | the proxy, port 8388, streams SSE through unchanged |
| `~/Library/LaunchAgents/com.qwen38.proxy.plist` | keeps it alive, even after reboot |
| `~/.runpod/current-pod` | current pod id, written by `qwen38fast`, cleared by `stop` |
| `~/.runpod/qwen38.key` | API key, generated once and reused |
| `~/.pi/agent/models.json` | provider `runpod`, model `runpod/qwen38-uncensored` |

No pod running → the proxy answers 503 with a hint to start `qwen38fast`, so the
agent shows a readable message instead of connection refused.

Three details that otherwise cost time:

- **`read1()` instead of `read()`** in the proxy. With `read()` Python waits for a
  full block and token streaming arrives in clumps. Verified: 198 chunks evenly
  over 6.12 s.
- **Browser User-Agent required.** The RunPod proxy answers Python urllib with 403.
- **`thinkingFormat: "qwen-chat-template"`** in the pi model definition. Only then
  does the thinking toggle land where SGLang reads it
  (`chat_template_kwargs.enable_thinking`).

The pod is reachable from the whole internet without `--api-key` once someone
knows the pod id. That's why `qwen38fast` generates a key on the first run and
hands it to SGLang and OpenWebUI.

## Which abliterated build is strongest

As of 2026-08-22, by published numbers:

| Build | Residual refusals | Quality loss | NVFP4 | Speed |
|---|---|---|---|---|
| `huihui-ai` (via sakamakismile NVFP4) | 1.5% | KLD 0.0078, first 15 layers untouched | yes | full 143 tok/s |
| `OBLITERATUS` (Pliny) V2 | 2 of 842, ~0.24% | ship score 92.1 | **no**, BF16 and GGUF only | BF16, ~a third |
| `orcarouter` | 0 to 6% | ±1.3 points | yes, but `mixed-precision` | unusable in SGLang |

The pick is huihui: harder than orcarouter, cleaner than anything else with
NVFP4. OBLITERATUS is more uncompromising but costs the FP4 path and thus two
thirds of the speed.
