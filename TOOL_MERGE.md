# TOOL_MERGE.md — citizen server: 8 tools → 6

Interview task (14/11/2026): use the MCP metrics to check efficiency, then reduce the citizen
server's tools by merging 1–2, measured before/after. The officer server is unchanged (6 tools).

## The 8 tools today

| tool | kind | input | est. tokens |
|---|---|---|---|
| get_scheme_info | read | none | 119 |
| check_eligibility | read | date_of_birth, applicant_mobile? | 263 |
| get_my_application | read | none | 131 |
| save_application_details | write (draft) | 12 optional fields | 715 |
| get_document_upload_link | link | applicant_mobile? | 334 |
| get_number_verification_link | link | none | 308 |
| submit_application | **write, declaration** | confirm_declaration, applicant_mobile? | 363 |
| withdraw_application | **destructive** | application_no, confirm | 173 |

Real footprint (calibration, `python -m evals calibrate`): **4,785 tokens** for the citizen
server, against an estimate of 3,979. The gap (~100 tokens per tool) is the client's own
wrapping of each tool, so every tool removed also saves that overhead.

## Rules for a merge

Only read-only or link-generating tools with a similar purpose. `submit_application`,
`withdraw_application` and `save_application_details` stay separate (declaration,
destructive action, writes). At most one new parameter per merge. Short, unambiguous
descriptions for a small model. Every portal rule and every result stays identical: the
merged tool calls the same code and returns the same fields as the tool it replaces.

## Merge A: `get_scheme_info` + `check_eligibility` → `check_scheme_and_eligibility`

Both are read-only and both answer "can she get this pension?". Today the assistant often
calls `get_scheme_info` then `check_eligibility` one or two messages later.

```
check_scheme_and_eligibility(date_of_birth: str | None = None, applicant_mobile: str | None = None)
```
- no `date_of_birth` → exactly today's `get_scheme_info` result (amount, documents, window, …)
- with `date_of_birth` → exactly today's `check_eligibility` result (age, window, existing
  application, next_step)
- new parameter: none; `date_of_birth` becomes optional (the one change of shape).
  `applicant_mobile` is unchanged and only used with a date of birth.

Description (draft): "The Old Age Pension's facts and an eligibility check. Without
date_of_birth: the amount, who qualifies, documents needed, decision time, and whether
applications are open; call this first when someone asks about the scheme. With
date_of_birth (the applicant's, DD/MM/YYYY, day first, e.g. 10/04/1957): checks age 60+, the
window, and whether this number already has an active application; call before collecting
details. <applicant_mobile doc>"

## Merge B: `get_document_upload_link` + `get_number_verification_link` → `get_link`

Both only issue a portal link the person opens themselves, and both are polled the same way
("when they reply, call again and check"). Different purposes, same shape.

```
get_link(purpose: "age_proof" | "verify_number", applicant_mobile: str | None = None)
```
- `purpose="age_proof"` → exactly today's `get_document_upload_link` result (upload_url,
  document_attached, …); `applicant_mobile` as today
- `purpose="verify_number"` → exactly today's `get_number_verification_link` result
  (verify_url, verified_numbers); `applicant_mobile` is not used
- new parameter: `purpose` (required enum, two values)

Description (draft): "A link the person opens on their phone. purpose="age_proof": upload the
applicant's age proof (…); call again after they reply and check document_attached.
purpose="verify_number": verify another mobile number by OTP on the page, only to file for
someone on a different number; call again after they reply and check verified_numbers.
<document and OTP rules, unchanged>"

## Not merged, and why

- `get_my_application` + anything: it is the status read and the one "status check"
  completion; merging it into the scheme tool would mix the person's data with public facts.
- `save_application_details`, `submit_application`, `withdraw_application`: writes; the
  declaration and the destructive withdraw must stay explicit.

## Expected saving

| | est. tokens before | est. after | real (incl. ~100/tool wrapping) |
|---|---|---|---|
| Merge A | 382 | ~300 | ~−180 |
| Merge B | 642 | ~420 | ~−320 |
| **citizen footprint** | 3,979 | ~3,500 | **~−500 of 4,785 (≈10%)** |

The footprint is re-read on every API call, about 11 per conversation, so the expected
saving is ~5–6k client tokens per conversation (≈5% of ~110k). Fewer calls per
application are possible but not expected: these merges do not remove a step, they only make
the tool list smaller. The risk is a small model choosing the wrong `purpose`, or skipping
the eligibility check because the scheme tool now "looks done"; the after-round checks both.

## What changes in the code

`app/mcp_server/citizen.py` (two tools replace four; instructions and next_step texts),
`app/mcp_server/fmt.py` (one next_step), `app/mcp_metrics_calc.py` (poll tools),
`app/scripts/check_*.py`, `evals/client.py` (expected tool list), persona checks that name
tools (p04, p10), `evals/tests`. Services, portal rules and the officer server: untouched.

## Result (14/11/2026): built, measured, **not deployed**

Same settings both rounds: local stack reset, the 12 citizen personas once plus P01 ×3,
client `claude-haiku-5-5`, Haiku simulator. Invalid runs (the simulated person broke their
card) are not counted.

| | before (8 tools) | after (6 tools) |
|---|---|---|
| conversations passed (valid) | 12/14 | 12/12 |
| tool calls per completed apply (median / mean) | 8 / 7.5 | 8 / 8.0 |
| wasted calls | 0 | 1 |
| client tokens per conversation | 126,645 | 134,731 |
| **client tokens per completed apply** | **137,082** | **146,426 (+6.8%)** |
| client tokens per assistant step | 10,368 | 10,707 |
| client API steps per conversation | 12.2 | 12.6 |
| citizen footprint, real (calibration) | 4,787 | 4,593 (−194, −4%) |

The deploy rule (pass rate not lower **and** tokens per completed apply not higher) fails on
tokens, so the merge stays on branch `tool-merge` and production keeps 8 citizen tools.

What the transcripts show:
- **No purpose confusion.** Every `get_link` call used the right purpose; `check_scheme_and_eligibility`
  was called without a date first and with one next, exactly mirroring the old
  `get_scheme_info` → `check_eligibility` pair. Calls per apply did not change.
- **The token rise is mostly conversation length.** P04 ran 9 person messages against 7,
  P15 7 against 5, P01-0077 10 calls against 7–8; each extra message re-reads ~10k tokens.
- **One behaviour change worth a second look.** In P03 (under 60) and P07 (already
  applied) the assistant called `save_application_details` in the same step as the
  eligibility check, before seeing that the person could not apply. Harmless (a draft,
  nothing filed), but new: before the merge it did not happen.

## What we learned

1. **Measure footprint, don't estimate it.** chars/3.5 under-counts the client's real cost by
   17–28%; the calibration turn is the number to use.
2. **The saving was smaller than planned (−194, not −500)** because the merged `get_link`
   kept every tuned safety sentence from both old descriptions (document rule, OTP rule,
   re-check rule). Those sentences came from earlier eval findings; shortening them would
   have been a behaviour change, not a merge.
3. **A 2% per-step saving is below the noise of 15 runs.** Conversation length varies by
   ±2 messages between runs and each message costs ~10k tokens, so a footprint change this
   small needs many more runs (or a fixed-script replay) to show up in tokens per apply.
4. **Fewer tools did not mean fewer calls.** The merges removed tool definitions, not
   steps; the call sequence was the same. A real saving would come from removing a step
   (for example, eligibility facts returned with the scheme facts so one call does both).
