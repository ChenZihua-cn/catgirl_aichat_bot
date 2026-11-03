#!/usr/bin/env python3
"""Compare base vs LoRA adapter on held-out prompts."""
from __future__ import annotations

import argparse
import json
import os

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def split_reasoning(text):
    if "</think>" in text:
        reasoning, visible = text.split("</think>", 1)
        return reasoning.replace("<think>", "").strip(), visible.strip()
    return "", text.strip()


def generate(model, tok, messages, max_new, do_sample, temperature, top_p):
    prompt = tok.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True)
    enc = tok(prompt, return_tensors="pt", add_special_tokens=False).to("cuda")
    kwargs = dict(
        max_new_tokens=max_new,
        repetition_penalty=1.05,
        eos_token_id=tok.eos_token_id,
        pad_token_id=tok.pad_token_id,
    )
    if do_sample:
        kwargs.update(do_sample=True, temperature=temperature, top_p=top_p)
    else:
        kwargs.update(do_sample=False)
    with torch.inference_mode():
        out = model.generate(**enc, **kwargs)
    new_ids = out[0][enc["input_ids"].shape[1]:]
    return split_reasoning(tok.decode(new_ids, skip_special_tokens=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="/home/labubu/30856/Model/DeepSeek-R1-Distill-Qwen-7B")
    ap.add_argument("--adapter", default="finetune/out/deepseek-r1-7b-cot-qlora")
    ap.add_argument("--prompts", default=None)
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--max-new", type=int, default=160)
    ap.add_argument("--out", default=None)
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--top-p", type=float, default=0.9)
    args = ap.parse_args()

    prompts_path = args.prompts or os.path.join(args.adapter, "eval_prompts.jsonl")
    rows = list(read_jsonl(prompts_path))[:args.limit]
    if not rows:
        raise SystemExit(f"no prompts in {prompts_path}")

    tok = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        quantization_config=bnb,
        device_map={"": 0},
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
        attn_implementation="sdpa",
    )
    model.eval()

    results = []
    for row in rows:
        base_reason, base_visible = generate(model, tok, row["messages"], args.max_new, args.sample, args.temperature, args.top_p)
        results.append({
            "id": row["id"],
            "scene": row["scene"],
            "last_human": row["last_human"],
            "reference": row["reference"],
            "base_reasoning": base_reason,
            "base_visible": base_visible,
        })
        print(f"[base] {row['id']} {row['scene']} | {base_visible}")

    print(f"[model] loading adapter {args.adapter}")
    model = PeftModel.from_pretrained(model, args.adapter)
    model.eval()
    for res, row in zip(results, rows):
        ft_reason, ft_visible = generate(model, tok, row["messages"], args.max_new, args.sample, args.temperature, args.top_p)
        res["ft_reasoning"] = ft_reason
        res["ft_visible"] = ft_visible
        print(f"[ft]   {row['id']} {row['scene']} | {ft_visible}")

    out_path = args.out or os.path.join(args.adapter, "eval_results.json")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"[save] {out_path}")


if __name__ == "__main__":
    main()
