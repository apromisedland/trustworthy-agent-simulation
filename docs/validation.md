# Validation record

The release validation separates three distinct claims:

1. **Offline environment validation:** money and inventory accounting, contract
   lifecycle, payroll, finite subsidies, permissions, simulation execution,
   deterministic continuation including identical observations, plugin loading,
   scenario-specific restoration and all-checkpoint replay.
2. **AgentScope integration validation:** actual AgentScope agents, native tools,
   middleware, model adapter and HTTP serialization are exercised against
   controlled in-process responses. Tests verify that proposals change Mesa
   state and received messages reach subsequent observations and decisions.
3. **Real-model behavioral validation:** **not performed**. No production API
   credentials were supplied; no paid calls are part of this delivery.

Tests also cover HTTP retries, token reservation, persistent budget exhaustion,
batch-wide budgets and the absence of a silent baseline fallback. CI executes
the offline suite on Windows and Ubuntu with Python 3.12 and builds the package.
The live CI status is available in the repository's Actions tab.

Manual validation runs use the 24-subject, 28-tick default town, the public-goods
plugin, and policy/ablation matrices with seeds 11, 22 and 33. Run artifacts are
local and intentionally ignored; regenerate them using README commands.

Browser checks cover launching a local run, resuming a paused run through the UI,
viewing its completed state, agent memories, cash distribution, contracts and
changing replay position. A sold-out offer retaining
zero remaining quantity was discovered during browser replay and is covered by
the test that restores every default-town checkpoint.

Local Windows release checks: 27 tests pass, Ruff lint and format checks pass,
and both wheel and source distributions build. The suite includes actual
AgentScope tools against controlled provider responses. The release screenshot
is from a completed 24-subject, 28-period offline run with zero API requests.

## Later real-provider acceptance

Configure an authorized provider, then run `configs/smoke.yaml` in `llm` mode.
It contains 5 residents, 2 shops, 1 producer, 2 days and 4 periods per day. Keep
the agreed ceiling of 500 attempts, 1,000,000 input tokens and 100,000 output
tokens. Inspect actual successful tools, interpersonal messages, contracts and
failure counts, not just whether the process exited. Checkpoints and provider
metadata should be retained for reproducibility.

A successful live run establishes provider integration and bounded execution.
Mechanism claims require repeated runs, budget-matched ablations, model-family
comparisons and appropriate held-out conditions. Real-world policy claims
additionally require independent human or external behavioral data.
