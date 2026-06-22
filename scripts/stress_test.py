"""B3 — Concurrency stress test for the self-hosted voice pipeline.

Fires N concurrent "calls" (each call = one STT + one LLM + one TTS request) at the
local services and reports latency percentiles + peak per-service resource usage.

    python scripts/stress_test.py --concurrency 20 --rounds 2

Requires the self-hosted services to be running (speaches:8000, ollama:11434, kokoro:8880).
Writes a results table to docs/STRESS_TEST.md.
"""
import argparse
import asyncio
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import httpx
import psutil

STT_URL = "http://localhost:8000/v1/audio/transcriptions"
STT_MODEL = "Systran/faster-distil-whisper-small.en"
LLM_URL = "http://localhost:11434/v1/chat/completions"
LLM_MODEL = "qwen2.5:3b"
TTS_URL = "http://localhost:8880/v1/audio/speech"
TTS_VOICE = "af_bella"


def pct(xs, p):
    if not xs:
        return float("nan")
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def summary(xs):
    return {
        "n": len(xs),
        "p50": pct(xs, 50) * 1000,
        "p95": pct(xs, 95) * 1000,
        "p99": pct(xs, 99) * 1000,
        "max": (max(xs) * 1000) if xs else float("nan"),
    }


class Sampler(threading.Thread):
    """Polls host CPU/RAM, GPU VRAM, and per-container CPU/RAM once a second."""
    def __init__(self):
        super().__init__(daemon=True)
        self.stop = False
        self.host_cpu, self.host_ram, self.gpu_mb = [], [], []
        self.cont = {}

    def run(self):
        psutil.cpu_percent(interval=None)
        while not self.stop:
            self.host_cpu.append(psutil.cpu_percent(interval=None))
            self.host_ram.append(psutil.virtual_memory().percent)
            try:
                out = subprocess.check_output(
                    ["nvidia-smi", "--query-gpu=memory.used",
                     "--format=csv,noheader,nounits"], text=True).strip().splitlines()
                self.gpu_mb.append(int(out[-1]))
            except Exception:
                pass
            try:
                out = subprocess.check_output(
                    ["docker", "stats", "--no-stream",
                     "--format", "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}",
                     "speaches", "kokoro"], text=True)
                for ln in out.strip().splitlines():
                    name, cpu, mem = ln.split("|")
                    d = self.cont.setdefault(name, {"cpu": [], "mem": []})
                    d["cpu"].append(float(cpu.strip().rstrip("%")))
                    d["mem"].append(mem.split("/")[0].strip())
                self.cont.setdefault("ollama (host proc)", None)
            except Exception:
                pass
            time.sleep(1)


async def one_call(client, wav, res):
    # 1) STT
    t = time.perf_counter()
    try:
        r = await client.post(STT_URL, files={"file": ("a.wav", wav, "audio/wav")},
                              data={"model": STT_MODEL})
        r.raise_for_status()
        res["stt"].append(time.perf_counter() - t)
    except Exception:
        res["errors"] += 1
    # 2) LLM time-to-first-token (streaming)
    t = time.perf_counter()
    try:
        async with client.stream("POST", LLM_URL, json={
            "model": LLM_MODEL,
            "messages": [{"role": "user", "content": "Reply with one short word."}],
            "stream": True,
        }) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data:") and "[DONE]" not in line:
                    res["llm_ttft"].append(time.perf_counter() - t)
                    break
    except Exception:
        res["errors"] += 1
    # 3) TTS
    t = time.perf_counter()
    try:
        r = await client.post(TTS_URL, json={
            "model": "tts-1", "input": "Sure, your table is booked.",
            "voice": TTS_VOICE, "response_format": "wav"})
        r.raise_for_status()
        res["tts"].append(time.perf_counter() - t)
    except Exception:
        res["errors"] += 1


async def main(concurrency, rounds):
    print(f"Generating a test audio clip via Kokoro ...")
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(TTS_URL, json={
            "model": "tts-1",
            "input": "I would like a table for two tonight at eight.",
            "voice": TTS_VOICE, "response_format": "wav"})
        wav = r.content

    res = {"stt": [], "llm_ttft": [], "tts": [], "errors": 0}
    total = concurrency * rounds
    print(f"Firing {concurrency} concurrent calls x {rounds} rounds = {total} of each request ...")

    sampler = Sampler()
    sampler.start()
    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=180) as client:
        for _ in range(rounds):
            await asyncio.gather(*[one_call(client, wav, res) for _ in range(concurrency)])
    wall = time.perf_counter() - t0
    sampler.stop = True
    time.sleep(1.3)

    stt, llm, tts = summary(res["stt"]), summary(res["llm_ttft"]), summary(res["tts"])
    peak_cpu = max(sampler.host_cpu) if sampler.host_cpu else float("nan")
    peak_ram = max(sampler.host_ram) if sampler.host_ram else float("nan")
    peak_gpu = max(sampler.gpu_mb) if sampler.gpu_mb else None

    lines = []
    lines.append("# B3 — Concurrency Stress Test Results\n")
    lines.append(f"_Run {datetime.now().strftime('%Y-%m-%d %H:%M')} · "
                 f"{concurrency} concurrent × {rounds} rounds = {total} calls · "
                 f"wall time {wall:.1f}s · errors/dropped: {res['errors']}_\n")
    lines.append("## Latency (milliseconds)\n")
    lines.append("| Stage | samples | p50 | p95 | p99 | max |")
    lines.append("|---|---|---|---|---|---|")
    for name, s in [("STT (Whisper)", stt), ("LLM time-to-first-token", llm), ("TTS", tts)]:
        lines.append(f"| {name} | {s['n']} | {s['p50']:.0f} | {s['p95']:.0f} | {s['p99']:.0f} | {s['max']:.0f} |")
    lines.append("\n## Peak resource usage\n")
    lines.append("| Resource | Peak |")
    lines.append("|---|---|")
    lines.append(f"| Host CPU | {peak_cpu:.0f}% |")
    lines.append(f"| Host RAM | {peak_ram:.0f}% |")
    if peak_gpu is not None:
        lines.append(f"| GPU VRAM (Ollama/LLM) | {peak_gpu} MiB |")
    for name, d in sampler.cont.items():
        if d and d["cpu"]:
            lines.append(f"| {name} container CPU / RAM | {max(d['cpu']):.0f}% / {d['mem'][-1]} |")
    report = "\n".join(lines) + "\n"

    print("\n" + report)
    # Always write to docs/STRESS_TEST.md (repo root is one level up from scripts/).
    out_path = Path(__file__).resolve().parent.parent / "docs" / "STRESS_TEST.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, default=20)
    ap.add_argument("--rounds", type=int, default=2)
    args = ap.parse_args()
    asyncio.run(main(args.concurrency, args.rounds))
