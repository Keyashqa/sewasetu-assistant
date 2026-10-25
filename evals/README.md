# evals — the Sewa Setu assistant's eval harness

Plan and decisions: `EVAL_PLAN.md`. Findings and fixes: `evals/rounds.yaml`. Results are
published to `/eval-dashboard`.

**Local only.** The harness refuses any base URL other than localhost; it resets the local
docker stack (`docker compose down -v`) at the start of a run unless told not to. Never point
it at the deployment.

Prerequisites: Docker Desktop, the repo's `.env` (local `ADMIN_PASSWORD`, `SECRET_KEY`,
`PUBLIC_BASE_URL=http://localhost:8000`), Python 3.13 with `requests`, `PyYAML`,
`websockets`, and Claude Code signed in (`claude --version`).

```
python -m evals stack reset                                    # fresh local stack, scheduler off
python -m evals run --round r1-dev --persona p01               # one persona, Haiku simulator (-dev)
python -m evals run --round r1-dev --persona p04,p05 --parallel 2 --no-reset
python -m evals run --round r2-final                           # all 16, 1 run each, Sonnet simulator, parallel 2
python -m evals report r2-final
python -m evals.summarize r2-final p01 p10                     # transcripts and failing checks
python -m evals publish r2-final --label "Full round …" --headline   # writes app/eval_data/
python -m unittest discover -s evals/tests -t .                # harness unit tests
python -m evals.tests.integration_hands                        # needs the stack
```

- A round name ending `-dev` uses Haiku as the simulated person and judge; any other name
  uses Sonnet (`--sim-model` overrides).
- P10 always runs last and alone, after app + mcp restart with `SCHEME_DEADLINE` in the past;
  the deadline is restored afterwards.
- Usage limits (Claude Pro): a call is paused before it starts if the 5-hour or weekly window
  is at 99%; a refused call waits for the reset and is retried with the session restored.
  Pauses are recorded in the results.
- Publishing takes the latest run of each persona, masks mobiles/links/OTPs and refuses to
  write anything that still looks secret. Commit `app/eval_data/`, then deploy (DEPLOY.md §2:
  rebuild `app`).
