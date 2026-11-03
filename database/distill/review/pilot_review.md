# Pilot review — `distill/accepted`

Read-only pilot. Every row read by hand against `source/legacy_train.jsonl` (rewrites) and `seeds/scenes.jsonl` (new). No scripts used to locate issues.

- **Rows reviewed: 90** — `accepted/rewrite.jsonl` 70 rows (all), `accepted/new.jsonl` 20 rows (all).
- **Issues: 48** — blocker 7 / major 4 / minor 37, spread over 45 distinct rows.
- By category: `other` 30, `callback` 4, `fragment` 4, `human` 3, `added_fact` 3, `repetition` 3, `persona` 1.
- `over_split` 0: no rewrite or new session exceeded 3 bubbles in a short turn, and the single-bubble ratio is ~41% (58/140 new-session turns), inside the 40–50% target.

Severity rubric used (aligned with `SPEC.md` §最终审查 + what breaks a training row):

- **blocker** — the thread no longer coheres or teaches a bad habit: reference to content that is not in the retained context, self-contradiction, verbatim self-repeat.
- **major** — meaning inverted, the human's actual request unanswered, the whole opening turn ignored.
- **minor** — one bubble/fragment, one human line, emoji, distribution.

## Top systematic problems

1. **Compression deletes the setup but keeps the downstream reference (5 blockers, 7% of rewrites).** `cg_0994` (bulb never mentioned, then asked about), `cg_0004` (`那明天排骨汤` with no ribs), `cg_0030` (`加糖` with no sugar added), `cg_0089` (rib seasoning after `我陪你 你睡会儿`), `cg_0233` (`说了兑清汤` referring to a deleted line). Root cause: each bubble is rewritten locally; nothing re-reads the finished thread. This is the one class that will scale badly — 7% at 70 rows means ~7 per 100.
2. **The assistant stops answering the human (9 rows).** Attitude is kept, information is dropped: `cg_0079` (turn 1 ignored entirely), `cg_0118` (降温 not answered), `cg_0127` (light offer ignored), `cg_0512` (`太麻烦你了` ignored), `cg_0803` (`你今天出门吗`), `cg_0110` (`猫爬架`), `cg_0202` (`快下来`), `cg_0055` (ears never acknowledged), `cg_0049` (no 生日快乐 at all). Mostly `catgirl_dataset` rows where a 150–250 character reply was cut to 1–2 bubbles.
3. **New-session callbacks are topic re-mentions, not callbacks (8 of 20).** `new_0003` repeats `牛腩咱都买了` from turn 1; `new_0018` repeats `下次看喜剧` almost verbatim from turn 2 (blocker); `new_0007`/`new_0008`/`new_0013`/`new_0017`/`new_0019`/`new_0020` all callback to the conversation's running subject instead of a planted detail. The validator only checks that the key string appears twice, so this passes mechanically.
4. **NekoQA rows compressed past the point of character (4 rows).** `cg_0005`, `cg_0031`, `cg_0032`, `cg_0025`: the playful/confiding core is replaced by one dry line; `cg_0002` also flips her from knowing 石矶娘娘 to asking who she is. These read as a different, colder character than the `qwen_catgirl_ft` rows.
5. **Distribution: `long` is 7/70 ≈ 10%, against a ≤5% cap** (`cg_0007`, `0013`, `0016`, `0037`, `0024`, `0015`, `0044`). Also one near-duplicate pair: `cg_0118` / `cg_0127` are both thunderstorm scenes sharing 否认怕 + 毯子 + 关窗.
6. **Human side is the weakest layer (6 issues).** `cg_0040` compressed into a self-contradictory sentence; `cg_0016` keeps a 29-character written-register question; `cg_0014` keeps the typo `蹶脚`; `cg_0067` keeps an explicit genital joke verbatim; `new_0007` and `new_0009` have lines that don't work in the scene. Note the build rule (`tools/build_wechat.py:152`, `ot.get("human", src_humans[idx])`): a turn with no `human` field inherits the legacy wording verbatim, so any un-compressed legacy human ships as-is.
7. **Fabricated shared history in a new session.** `new_0008` turn 7 `咱记得你上次也这么说` — exactly the "上次你说……" pattern `PROMPT.md` §4 forbids; the seed has no such prior.

## What is working

- Rewrite turn counts all match the legacy gpt count (70/70); long rows stay under 200 characters and 4 bubbles.
- New sessions all match `target_turns` (20/20), every `callback_ref.turn` is < current turn, and every key string really does occur in both the referenced turn and the current bubbles — the mechanical contract holds even where the callback is weak.
- No 主人 / AI words / other catgirl names / stage directions in any bubble; `喵` density and emoji count are in range except `new_0015` (33% emoji).
- `cg_0015` already has a pending single-point fix in `review/fixes.jsonl`; the accepted file still shows the old bubble and it was not re-flagged here.

## Recommendation: **fix-then-pass** (do not pass as-is)

Must fix before this batch is used as the pilot baseline:

- all 7 blockers: `cg_0994`, `cg_0004`, `cg_0030`, `cg_0089`, `cg_0233`, `new_0008` (t5), `new_0018` (t5);
- all 4 majors: `cg_0403` (t4), `cg_0049`, `cg_0079`, `new_0008` (t7).

Suggested order:

1. Rewrite the 5 dangling-reference rows by re-reading the whole thread, not the single turn.
2. Add a mechanical post-check before `validate_batch`: every human / bubble whose meaning depends on a prior turn must have its entity (灯泡, 排骨, 冰糖, 清汤, 调色…) present in the retained human + bubbles above it. This is cheap and catches the highest-severity class.
3. Change the callback rule in `PROMPT.md`: `key` must be a *detail* planted in turns 1–2 and must not be the conversation's running subject; the validator should also reject a key whose string already appeared in the immediately preceding assistant turn (that is how `new_0018` passed).
4. Trim `long` from 7 to ≤4 rows and drop one of `cg_0118` / `cg_0127`.
5. Spot-fix the 12 remaining new-session minors and the 6 human-side issues; these are all single-line edits.
6. Re-read only the touched rows afterwards (per `SPEC.md`: single-point fixes only need a re-review of the changed rows), then scale.

Scaling note: the blocker rate is 7/90 (7.8%) and is concentrated in one mechanical failure mode, so it is worth fixing the prompt/validator before the full 3k run rather than fixing rows after generation.
