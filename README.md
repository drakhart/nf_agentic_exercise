### Instructions

#### GitHub Copilot

I requested services for a GitHub Copilot subscription, so this exxercise uses it's SDK through a small CrewAI `BaseLLM` adapter. Sign in with the Copilot CLI before running the application:

```sh
copilot login
```

`COPILOT_MODEL` .env var can override the default model.

#### Stretch work

The default command putputs just the original report. Stretch options are opt-in, i.e.:

```sh
uv run main.py INC-2043 --impact --critic --tool-budget 12 --timeout 60
uv run main.py INC-2043 --critic --post-update
uv run main.py --all
```

The Impact Analyst runs concurrently with the log and change specialists, sees only the initial incident, and adds its output to open questions.

The critic checks that reported citations were actually returned by search results, then checks the claims against those results.

Update posting depends on the the critic if this is enabled: a rejected or failed review prevents the update from being posted.

"All" mode emits all reports and one action list ordered by urgency, then incident id.

The tool budget counts every tool execution in an incident, including an explicit post. Hitting the budget or timeout produces a partial report.

The timeout covers only the parallel specialist phase, not the later correlation and runbook stages.

#### Evals

Examples:

```sh
uv run evaluate.py --split training          # five attempts each: INC-2043 and INC-2051
uv run evaluate.py --split holdout           # five attempts: INC-2062, after tuning
uv run evaluate.py --golden                  # ten attempts: INC-2043
uv run evaluate.py --split training --faults # add branch error, timeout, missing changes, empty logs, total budget and per-specialist budgets
uv run evaluate.py --runs 1 --output out/smoke-evals.jsonl
```

Run without `--split` to evaluate all three baseline cases. Expectations in [the cases](../eval_cases.json) come from the checked-in source evidence, not from model-generated reports.

Keep the holdout out of prompt tuning.

The baseline grader checks cause concepts, onset, returned evidence, correlation, theory rejection and the runbook decision. Fault runs check the behaviour each injected failure is meant to exercise. These are lightweight text heuristics, not a model judge.

Each attempt is appended to `out/evals.jsonl`, including failures, property checks, elapsed time, tool executions and denials, and SDK usage events. The file is append-only, so choose a new `--output` path for a clean run.

`reported_cost` is the SDK's reported value, not an invoice. It is `null` when unavailable or incomplete.

The runner prints per-case pass counts to stderr and exits nonzero if any attempt fails. Evals make hosted model calls but never post updates.

### Debrief questions

#### Where did your orchestrator's logic want to become a model call, and did you let it?

At first I tried to make everything be LLM calls, just out of curiosity, and it was catastrophic: sequential calls made before the orchestrator model asked for logs or changes, hallucinated services (i.e. stock service), and many other issues.

Then I kept the orchestrator deterministic with Python code: it makes the specialist agent calls concurrently, correlates their findings and moves on.

This makes the system easier to maintain an more predicable. Sure, it loses some of the reasoning and freedom can bring to the table, but I believe that the goal of this exercise is to balance agentic reasoning and reprudeacibility, and I believe I achieved a good balance in the end.

#### What did the join actually cost? Was it prompt work, code, or both?

It required both.

On the prompt side I needed the specialists (Log Analyst and Change Historian) to have separated responsibilities, and to provide sufficient evidence.

On the code side, I needed to implement the concurrent execution, collect the results and provide the final reasoning.

#### Which failures were prompt problems and which were architecture problems?

At first I thought that was a massive prompt problem: I started using local Ollama with DeepSeek 4.1 Flash just to save tokens from my Copilot subscription. It kept outputing bad results, and I blamed that on the prompts. I became obsessed adding more and more instructions and safeguards into them, until I realised that the model was simply running out of context and hallucinating.I lost an incredible amout of time on this.

Then I moved to Copilot, and specifically Claude Sonnet 5.5, with a wrapper coded by itself because CrewAI doesn't support Copilot out of the box and I didn't know where to begin with that, and the prompt issues were mostly gone. Sure, I needed to specify a bit their instructions, but it was easy after that.

Then I had to make a lot of architecture changes. I spent most of the time adding defensive safeguards around timeouts, exceptions, invalid citations, missing evidence, and so on.

So all in all it was again a mix of both.

#### What did the evidence citation requirement cost you, and what did it buy you?

This was easily the most difficult piece besides the orchestrator itself, and it added a lof of complexity all aroun the project: the agents needed to return precise citations, the incident analyst needed to preserve those references, and the report builder needed to verify that the references actually existed in the search results.

It was a lot of work, but I think it's totally worth it: without proper evidence citation and validation, the output could contain a root cause or actions that aren't supported by evidence. By reqiring citations, the report becomes asier to verify.

#### If a fourth specialist arrived tomorrow, what would you have to change?

I tried this by adding the Impact Analyst, which is a third parallel specialist.

The orchestrator was relatively easy to extend because specialists are registered in a collection and executed concurrently. However I just added its output to the open questions to avoid mutating the expected output model. That would have required extra changes.

I think the current architecture supports adding more agents without major changes.

#### If you used a framework, what did it decide for you, and would you have decided the same? If

you did not, what did you spend time building that you would rather have had for free?

I used CrewAI, which is one of the tools shown in the learning video, although I'm not really proficient with Python.

It provided the basic scaffolding for defining agents, tasks, tools and execution. One big caveat is that it doesn't support GitHub Copilot out of the box, and I didn't have any idea of how to integrate it, so I admit I used AI to create a wrapper for it and pass the tools to it.

I kept the orchestration logic in pure Python because I wanted to have a fine control over the logic sequence, which I believe is the biggest take away from this exercice.

In retrospective, I probably would've chosen a different language even if it wasn't in the learning materials, being a Node developer myself. Having to code Python, which I'm not familiar with (besides the typical user scripts and some plugin here and there), slowed me down and was a major source of frustration, and I have to admit that many times I resorted to autocomplete or asking the AI for help, especially when writing the evals when I was really tired. I did my best, but of course you'll judge if that's enough.

### Other thoughts

#### Fixes needed in the exercise repository

- `search_logs` tool should search just the log message and not the whole line. This isn't mentioned as a requirement in the contract, but missing it produces this extra unwanted result on the "`search_logs("checkout deploy")` -> the deploy lines in `platform-events.log`" check:

```
{
  'file': 'checkout-service.log',
  'line': 3,
  'text': '2026-08-12T19:29:58Z  checkout-service  INFO   draining connections for shutdown reason=deploy version=4.11.3'
}
```
