# Pilot rewrite review 2

## Scope

- 30 rows / 90 assistant turns / 154 bubbles: `c01` 10 rows (41 turns, 72 bubbles), `c02` 10 rows (39 turns, 66 bubbles), `c05` 10 rows (10 turns, 16 bubbles).
- Every output bubble was compared against the original human + gpt turn in the chunk input and in `source/legacy_train.jsonl`. All 30 input rows are byte-identical to the legacy records, so the problems below are rewrite-side, not upstream truncation.
- Issue file: `pilot_review_2.jsonl` (52 lines).

## Counts

| chunk | rows | issues | blocker | major | minor |
|---|---:|---:|---:|---:|---:|
| c01 | 10 | 28 | 1 | 20 | 7 |
| c02 | 10 | 15 | 0 | 9 | 6 |
| c05 | 10 | 9 | 0 | 2 | 7 |
| total | 30 | 52 | 1 | 31 | 20 |

By category: `other` 32, `persona` 9, `human` 5, `fragment` 3, `added_fact` 2, `repetition` 1, `over_split` 0.

Rows with no issue: `cg_0222`, `cg_0192`, `cg_0046`.

Rows with only minor issues: `cg_2493`, `cg_0586`, `cg_0164`, `cg_0012`, `cg_0041`, `cg_0065`, `cg_0171`, `cg_0020`, `cg_0039`, `cg_0054`.

Rows with at least one major/blocker: `cg_0073`, `cg_0458`, `cg_0053`, `cg_0086`, `cg_0124`, `cg_0077`, `cg_0485`, `cg_0112`, `cg_0230`, `cg_1429`, `cg_1442`, `cg_0520`, `cg_0174`, `cg_0045`, `cg_0060`, `cg_0255`, `cg_0042`.

Severity used here: **blocker** = actionable user-facing content lost (medical instructions); **major** = the turn's core answer, cross-turn reference, or persona contract is broken; **minor** = a detail/texture loss where the turn still works.

## Top systematic problems

### 1. c01 is over-compressed into single bubbles

`c01` source gpt turns average 169.7 chars; output turns average 20.9 chars (12.3% of source length), and 17 of 41 turns are a single bubble. `c05` is at 17.8% of source length; `c02` at 33.8%.

The first things cut are consistently the ones that make the persona work:

- concrete care actions: breakfast, soup reheating schedule, medicine, honey water, umbrella;
- tsundere denials: `谁说我等你了`, `我才不陪你坐`, `谁要你煮面`;
- the emotional payload: `不想一个人待着`, `下午埋在被子里 想你了`.

Examples: `cg_0124` t2 195 chars -> an 11-char bubble; `cg_0230` t1 181 -> 10; `cg_0485` t2 174 -> 10; `cg_0077` t5 187 -> one 10-char bubble plus emoji. This is not just brevity: several turns stop answering the human at all.

### 2. Human compression is decoupled from what the assistant says

All 41 `c01` humans are compressed, and the compression often removes the exact premise the reply depends on:

- `cg_0073` t1: human keeps `扣五十` but drops `第二次`; assistant still says `一百块`.
- `cg_0458` t1: human drops `周六` / `连周末都这样`; assistant still says `周六下午三点`.
- `cg_0124` t5: human drops the milk-tea offer; assistant still says `别买奶茶`.
- `cg_0485` t1/t4: human drops `晚饭吃了没` and `我给你煮碗面`; assistant answers both anyway.
- `cg_1429` t2/t3: human drops `你要是不想回就不回` and `带上那条白裙子`; assistant replies `看我安排 你倒会推` and `那条裙子扣不上了`.
- `cg_0042` t1: human drops the actual symptom `晚上发现没下完`, leaving only `关机` and `中毒`.

Only 5 JSONL lines use the `human` category because most instances were filed under the assistant turn they break; the pattern affects at least 8 rows.

### 3. Direct questions are left unanswered

At least eight turns ignore what the human actually asked:

- `cg_0053` t1: `要不要浇水` -> no `先别浇水`;
- `cg_0230` t4: `配点咸菜` -> only the sofa;
- `cg_0045` t4: `玩到几点` -> only `赢一局为止`;
- `cg_0255` t1/t2: no agreement to go, no answer to `你咋这么熟`;
- `cg_1442` t3: `你陪我坐会儿` -> only the ear-touch reward;
- `cg_0520` t3: `你怎么连这个都想到啦` -> only `带块生姜`;
- `cg_0060` t2: spicy hotpot lunch -> only `别喝奶茶`.

### 4. Cross-turn setup/callback is broken

The rewrite optimizes each turn in isolation:

- `cg_0485`: t1 drops `梅干`, t2 human still references it; t4 drops the umbrella line, t5 human acknowledges it and assistant repeats it.
- `cg_0174`: t3 drops `热过第二次`, t4 human asks `你热了两次？`.
- `cg_1429`: t1 drops `晒被子`, t4 says `下午埋在被子里`; t3 drops the white dress, assistant talks about the dress.
- `cg_0073`: t2 drops the packed buns, t3 reintroduces them.
- `cg_0255`: t1 drops the trip research, t2 human asks `你咋这么熟`.

### 5. Persona flattening

Nine `persona` issues. The usual shape is: the source has a refusal/denial followed by a reluctant concession, and the rewrite keeps only one half.

- `cg_0485` t4: keeps the concession, drops `谁要你煮面`;
- `cg_1429` t4: keeps the confession, drops `就一分钟` / `别取笑我`;
- `cg_0045` t3 and `cg_0255` t4: ignore the human's teasing and only give the next instruction;
- `cg_0012`: turns playful `一起玩` into `你一天到晚瞎想`;
- `cg_0020`: only `你疯了吧`, losing the `会着凉 / 披件衣服` worry.

### 6. c05 is the safest chunk, with one real knowledge problem

`c05` single-turn Q&A mostly preserves the answer. The exception is `cg_0042`: the compressed human removes `没下载完`, and the reply `电脑又不是猫 不会中毒` is a false generalization (the source only joked `不会得病`). `cg_0020` is a special case: the source's voyeuristic `躲泡泡里偷看` idea was correctly removed; do not restore it, only restore the caretaking worry.

## Per-chunk verdict

### c01: re-rewrite required (all 10 rows)

The strategy of compressing 140–200 char turns into one short bubble does not preserve the source. Every row has at least one major/blocker. `cg_0230` t1 is the highest priority: the user is sick and the rewrite deletes the medicine names, warm-water instruction, dosage, and hospital threshold.

### c02: targeted fixes, then pass

Facts are mostly accurate; the losses are emotional/structural. Fix the six major rows: `cg_1442` (sit-with-me), `cg_0520` (why-she-knows), `cg_0174` (reheat reference), `cg_0045` (tease + play-until-when), `cg_0060` (spicy lunch + porridge setup), `cg_0255` (trip agreement + two teasing replies). `cg_0222` passes as-is; the other three need minor polish.

### c05: fix cg_0042, then pass

Fix the `cg_0042` human compression and the `不会中毒` claim. The other rows are minor texture losses; `cg_0192` and `cg_0046` pass as-is.

## Recommendation

**Do not pass the 30-row pilot as-is. Fix before accept.**

- c01: full re-rewrite of the 10 rows, with a 2–3 bubble budget per turn and a retention checklist: (a) the direct answer to the human's question, (b) one concrete care action, (c) one denial/soft beat if the source has one, (d) every detail the next human/assistant turn references.
- c02: targeted second pass on the six major rows; keep the rest.
- c05: one targeted fix (`cg_0042`), minor polish elsewhere.
- Add automated guards: for every compressed human, check that entities/actions in the assistant reply appear in the human or an earlier turn; for every assistant turn, check the human's question type is answered; flag any source gpt >=120 chars rewritten to a single bubble under 20 chars for manual review; run a cross-turn n-gram check for setup/callback.
- Do not respond by splitting more: `over_split` is 0. The failure mode is selecting too few beats, not too many bubbles.
