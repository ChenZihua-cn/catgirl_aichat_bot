#!/usr/bin/env python3
"""QLoRA SFT for the text-only catgirl corpus.

Default target is DeepSeek-R1-Distill-Qwen-7B. The script builds the raw
DeepSeek chat sequence itself instead of using apply_chat_template(), because
that template strips everything before </think> from assistant content.

Only assistant spans (including <think>...</think> and the EOS token) are
supervised. A small eval split is held out and written to <out>/eval_prompts.jsonl.
"""
from __future__ import annotations

import argparse
import json
import os
import random

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import torch
from datasets import Dataset
from peft import LoraConfig, PeftModel, get_peft_model
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    Trainer,
    TrainingArguments,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATA = os.path.join(ROOT, "database", "train.jsonl")
DEFAULT_MODEL = "/home/labubu/30856/Model/DeepSeek-R1-Distill-Qwen-7B"
DEFAULT_OUT = os.path.join(ROOT, "finetune", "out", "deepseek-r1-7b-cot-qlora")

USER = "<｜User｜>"
ASSISTANT = "<｜Assistant｜>"
EOS = "<｜end▁of▁sentence｜>"


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def assistant_text(row, include_cot):
    visible = row["conversations"][-1]["value"]
    cot = (row.get("cot") or "").strip()
    if include_cot and cot:
        return f"<think>\n{cot}\n</think>\n\n{visible}"
    return visible


def encode_example(row, tokenizer, bos, include_cot, max_len):
    conv = row["conversations"]
    system = conv[0]["value"]
    ids = tokenizer(bos, add_special_tokens=False).input_ids
    labels = [-100] * len(ids)

    ids += tokenizer(system, add_special_tokens=False).input_ids
    labels += [-100] * (len(ids) - len(labels))

    for i in range(1, len(conv), 2):
        human = conv[i]["value"]
        prefix = USER + human
        pids = tokenizer(prefix, add_special_tokens=False).input_ids
        ids += pids
        labels += [-100] * len(pids)

        aids = tokenizer(ASSISTANT, add_special_tokens=False).input_ids
        ids += aids
        labels += [-100] * len(aids)

        if i == len(conv) - 2:
            content = assistant_text(row, include_cot)
        else:
            content = conv[i + 1]["value"]
        cids = tokenizer(content, add_special_tokens=False).input_ids
        ids += cids
        labels += cids

        eids = tokenizer(EOS, add_special_tokens=False).input_ids
        ids += eids
        labels += eids

    if len(ids) > max_len:
        return None
    return {"id": row["id"], "scene": row["scene"], "input_ids": ids,
            "labels": labels, "length": len(ids)}


def prompt_row(row):
    conv = row["conversations"]
    return {
        "id": row["id"],
        "scene": row["scene"],
        "messages": [{"role": "system", "content": conv[0]["value"]}]
        + [{"role": "user" if m["from"] == "human" else "assistant",
            "content": m["value"]} for m in conv[1:-1]],
        "last_human": conv[-2]["value"],
        "reference": conv[-1]["value"],
    }


class PadCollator:
    def __init__(self, pad_id):
        self.pad_id = pad_id

    def __call__(self, features):
        width = max(len(f["input_ids"]) for f in features)
        input_ids, labels, masks = [], [], []
        for f in features:
            n = len(f["input_ids"])
            input_ids.append(f["input_ids"] + [self.pad_id] * (width - n))
            labels.append(f["labels"] + [-100] * (width - n))
            masks.append([1] * n + [0] * (width - n))
        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "attention_mask": torch.tensor(masks, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--max-len", type=int, default=896)
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--batch-size", type=int, default=1)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--lora-alpha", type=int, default=32)
    ap.add_argument("--lora-dropout", type=float, default=0.05)
    ap.add_argument("--eval-size", type=int, default=40)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-steps", type=int, default=-1)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-cot", action="store_true")
    ap.add_argument("--resume-adapter", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    print(f"[env] cuda={torch.cuda.is_available()} "
          f"free_vram={torch.cuda.mem_get_info()[0]/1e9:.2f}GB "
          f"total_vram={torch.cuda.get_device_properties(0).total_memory/1e9:.2f}GB")

    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    bos = tokenizer.bos_token
    print(f"[tok] bos={bos!r} eos={tokenizer.eos_token!r} pad={tokenizer.pad_token!r}")

    rows = list(read_jsonl(args.data))
    random.Random(args.seed).shuffle(rows)
    eval_rows = rows[:args.eval_size] if args.eval_size else []
    train_rows = rows[args.eval_size:] if args.eval_size else rows
    if args.limit:
        train_rows = train_rows[:args.limit]
    print(f"[data] train={len(train_rows)} eval={len(eval_rows)} cot={not args.no_cot}")

    skip = 0
    train = []
    for row in train_rows:
        ex = encode_example(row, tokenizer, bos, not args.no_cot, args.max_len)
        if ex is None:
            skip += 1
        else:
            train.append(ex)
    print(f"[data] encoded={len(train)} skipped_too_long={skip}")
    if not train:
        raise SystemExit("no training rows fit max_len")
    lens = sorted(e["length"] for e in train)
    print(f"[data] len min/avg/max={lens[0]}/{sum(lens)/len(lens):.0f}/{lens[-1]}")

    os.makedirs(args.out, exist_ok=True)
    if eval_rows:
        with open(os.path.join(args.out, "eval_prompts.jsonl"), "w",
                  encoding="utf-8", newline="\n") as f:
            for row in eval_rows:
                f.write(json.dumps(prompt_row(row), ensure_ascii=False) + "\n")

    if args.dry_run:
        ex = train[0]
        print("[dry-run] first ids:", ex["input_ids"][:40])
        print("[dry-run] first labels:", ex["labels"][:40])
        print("[dry-run] decoded tail:",
              tokenizer.decode(ex["input_ids"][-80:], skip_special_tokens=False))
        return

    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    print("[model] loading 4-bit ...")
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        quantization_config=bnb,
        device_map={"": 0},
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
        attn_implementation="sdpa",
    )
    # PEFT's prepare_model_for_kbit_training casts embedding/lm_head to fp32,
    # which needs ~2GB extra and OOMs on an 8GB card. Freeze instead, and only
    # cast the tiny RMSNorm modules to fp32 for stability.
    model.gradient_checkpointing_enable(
        gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    for _, param in model.named_parameters():
        param.requires_grad = False
    for name, module in model.named_modules():
        if name.endswith(("input_layernorm", "post_attention_layernorm")):
            module.to(torch.float32)
    model.config.use_cache = False
    torch.cuda.empty_cache()

    lora = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )
    if args.resume_adapter:
        print(f"[model] resuming adapter {args.resume_adapter}")
        model = PeftModel.from_pretrained(model, args.resume_adapter, is_trainable=True)
    else:
        model = get_peft_model(model, lora)
    model.print_trainable_parameters()
    print(f"[mem] after load allocated={torch.cuda.memory_allocated()/1e9:.2f}GB "
          f"reserved={torch.cuda.memory_reserved()/1e9:.2f}GB")

    dataset = Dataset.from_list(train)
    collator = PadCollator(tokenizer.pad_token_id)
    targs = TrainingArguments(
        output_dir=args.out,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        lr_scheduler_type="cosine",
        warmup_steps=10,
        logging_steps=5,
        save_strategy="steps",
        save_steps=50,
        save_total_limit=1,
        save_only_model=True,
        bf16=True,
        optim="paged_adamw_8bit",
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        report_to=[],
        remove_unused_columns=False,
        dataloader_num_workers=0,
        max_grad_norm=0.3,
        seed=args.seed,
    )
    trainer = Trainer(model=model, args=targs, train_dataset=dataset,
                      data_collator=collator)
    print("[train] start")
    trainer.train()
    print(f"[mem] peak allocated={torch.cuda.max_memory_allocated()/1e9:.2f}GB")
    model.save_pretrained(args.out)
    tokenizer.save_pretrained(args.out)
    print(f"[save] adapter -> {args.out}")


if __name__ == "__main__":
    main()
