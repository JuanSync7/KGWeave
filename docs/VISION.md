# KGWeave Vision

## Mission in one line

**KGWeave is a completeness-audit tool for chip-design IP.** It answers
the question "have I covered everything?" — not "does what I have
work?". The latter is validation, and EDA tools already do it well.
KGWeave does the layer above: it audits whether every claim in the
spec, every constraint in IP-XACT, every line in the testplan, every
intent expressed in prose, has corresponding infrastructure
(assertion, coverpoint, test, constraint, register definition) further
down the stack — and surfaces the gaps.

## Completeness audit vs. validation

These are different jobs and KGWeave is firmly on one side of the line:

| Concern | Question asked | Tool that answers it |
|---|---|---|
| **Validation** | Does my implementation behave correctly? | EDA: simulators, formal tools, static timing, lint |
| **Completeness audit** | Do I have the right *infrastructure in place* to validate every spec claim? | **KGWeave** |

EDA tools assume the testbench, assertions, constraints, and coverage
plan already exist; their job is to run them and report pass/fail.
KGWeave's job is the prior question: *do those things even exist for
every spec claim, and are they linked back to the claims they
discharge?* Both jobs are necessary, and together they form the loop:

```
Spec claim ──[KGWeave audit]──→ "Yes, there is a testpoint+SVA for this"
                                   │
                                   ↓
                           [EDA validation]
                                   │
                                   ↓
                          pass / fail / coverage hit
```

KGWeave does not need to ingest coverage hit reports (URG/IMC) or
simulation logs. Those are the EDA validation truth. KGWeave's truth
is the *declarations* one level up: did the design team plan for
every spec claim to be checked? When EDA reports a green run on a
plan that's missing half the spec, EDA is right and the plan is
incomplete — only the audit catches that.

## The "go up a level" insight

Auditing completeness means moving above the RTL, into the sources
that *declare what should be true* about the design. RTL is the
implementation; it's the answer, not the question. To know whether
the answer is *complete*, the audit needs the questions, and the
questions live in upper layers:

| Layer | Declares | Format |
|---|---|---|
| Functional spec | What the IP is supposed to do (prose claims) | Markdown / PDF |
| IP-XACT | Canonical structure (ports, clocks, registers, bus interfaces) | XML |
| SDC | Timing intent (clocks, false paths, multicycles) | Tcl |
| CSR map | Software-visible register interface | HJSON / IP-XACT |
| DV testplan | Verification intent (testpoints, stages, coverage targets) | HJSON |
| Security countermeasure plan | Sec-cm scenarios and threat model | HJSON / markdown |
| Compliance checklists | Lifecycle gates (DV signoff, V1/V2/V3) | Markdown |
| Programmer's guide / SW spec | Software-side contract | Markdown |
| Power intent | Power domains, isolation, retention | UPF / CPF |
| Lint / CDC / coverage waivers | Declared exceptions ("intentionally not checked") | Tcl / regex files |
| RTL header & block comments | Design intent buried in code | SystemVerilog comments |

Together, these are the **intent layers**. Every one of them is a
declaration written before or alongside the RTL, and every one of
them claims something the RTL must implement (or the testplan must
verify, or the assertion must enforce). KGWeave ingests these,
canonicalises shared entities (a port named in IP-XACT is the same
node as the port in RTL), and exposes the cross-layer joins that
make the completeness audit askable.

## Sources KGWeave ingests (and which it deliberately does not)

| Source | What it asserts | Tool that owns it today | KGWeave ingests? |
|---|---|---|---|
| RTL (SystemVerilog) | Structure, dataflow, FSM, assertions, covergroups | Simulators, synthesis, lint | Yes |
| IP-XACT XML | Canonical port/clock/register specification | IP-XACT validators | Planned |
| SDC (Tcl) | Timing constraints | Static timing tools | Yes |
| HJSON CSR map | Software-visible register interface | Reggen / register tools | Yes |
| HJSON DV testplan | Verification intent and coverage targets | DV simulators (UVM) | Yes |
| HJSON sec-cm testplan | Security countermeasure scenarios | DV simulators | Yes |
| Markdown spec | Functional and behavioural prose claims | Humans | Yes (mentions + LLM-extracted SpecClaim nodes) |
| Freeform testplans (markdown / wiki / CSV) | Verification intent in non-canonical formats | Humans | Yes (LLM testplan normalizer → canonical TestplanExtractor) |
| Bind-attached SVA files (`dv/sva/*.sv`) | Higher-level FPV properties | Formal tools | Planned |
| Covergroup/coverpoint declarations (RTL + `dv/cov/*.sv`) | What is *planned to be measured* | Coverage merge tools | Planned |
| File-header & block comments | Design intent buried in code | Humans | Planned |
| Compliance checklists (`checklist.md`) | Lifecycle gates (V1/V2/V3) | Humans | Planned |
| Programmer's guide / SW spec | Software-side contract | Humans | Planned |
| Power intent (UPF / CPF) | Power domains, isolation, retention | Power-aware tools | Future |
| Lint / CDC / coverage *waivers* | Declared exceptions ("intentionally not checked") | Vendor reports | Future |
| **Coverage hit reports (URG/IMC)** | Runtime truth: did the regression hit each bin? | EDA simulators | **No — out of scope** |
| **Simulation logs / dump files** | What actually fired at runtime | EDA simulators | **No — out of scope** |
| **Synthesis netlists / timing reports** | Post-synth structural and timing results | EDA tools | **No — out of scope** |

The "out of scope" rows are deliberate. They are *validation truth* —
the artefacts EDA tools produce when they run. KGWeave does not
ingest them because the audit it provides asks a different question:
not "did the regression hit it?" but "is there *something* in the
plan that *should* hit it?" Once the audit is green, the EDA tools
are the authoritative source of pass/fail. KGWeave is the upstream
question; EDA is the downstream answer.

Each ingested source is parsed by a different tool today. Each tool
sees one slice of the IP and is silent about the others. **No tool
answers questions that span more than one slice**, because no tool
sees more than one slice. KGWeave's mission is to make the IP
*queryable as a single graph* across all slices so engineers and AI
agents can ask the cross-cutting completeness questions that today
require manually exporting from five tools and joining the results in
a spreadsheet.

## What KGWeave is not

KGWeave is not a replacement for any EDA tool. It does not:

- Run static timing analysis (PrimeTime / Tempus does this)
- Validate IP-XACT structurally (Cadence IP Studio / Synopsys CoreTools does this)
- Lint RTL for naming or CDC issues (Spyglass / AscentLint does this)
- Run formal verification or simulation (JasperGold, Questa, VCS do this)
- Compute coverage (the simulator does this)

Re-implementing any of those would be reinventing 20 years of vendor
investment, badly. The point of KGWeave is the *layer above* those tools —
the unified graph that holds their inputs, outputs, and the prose that
describes them, all linked.

## The killer audit query

Before the three query classes, the single defining query that
encapsulates KGWeave's value:

> **For every claim in the spec, is there at least one testpoint
> covering it, at least one assertion enforcing it, and at least one
> coverpoint measuring it — and does the test that exercises it
> actually exist as code?**

Re-stated as a graph traversal: for every claim node, do the
following edges exist somewhere in the join?

```
SpecClaim ──covered_by──→ Testpoint  (from testplan)
SpecClaim ──enforced_by──→ SVA       (from RTL or bind file)
SpecClaim ──measured_by──→ Coverpoint (from RTL or dv/cov)
Testpoint ──tests──→ DVTest ──realized_by──→ SV_File (the test exists)
```

Any missing arrow is a completeness gap. The audit report lists
every claim with at least one missing arrow. That is the deliverable.

EDA tools cannot produce this report because they do not ingest the
spec; they assume the testbench already exists and exercise it. The
question "does this testbench cover the spec" is upstream of every
EDA tool.

## Three query classes that EDA tools cannot serve

### 1. Cross-source joins

Engineers regularly need to ask questions like:

> "Which ports appear in RTL, are declared in IP-XACT, but have no SDC
> constraint **and** no spec section mentioning them **and** no SVA
> covering them?"

Today this requires extracting four lists from four tools and joining
them by hand. The data exists, but it does not live in one place. KGWeave
makes this a single graph traversal because every artifact (port, clock,
constraint, spec section, assertion) is a node in the same graph,
connected by typed edges.

A concrete join chain exists for every Port in the system:

```
Port (from RTL)
  ↑ specified_by ── IPXACT_Port (from IP-XACT)
  ↑ constrains_port ── IODelay (from SDC)
       └── relative_to_clock ── ClockDomain
  ↑ mentions ── Section (from markdown)
  ↑ references_signal ── SVA_Assertion (from RTL)
       └── covered_by ── Testpoint (from testplan)
              └── tests ── DVTest (from DV plan)
```

No EDA tool produces this chain because no EDA tool ingests all seven
sources. KGWeave does, by design.

### 2. Natural-language ↔ structure linkage

EDA tools touch zero prose. They are blind to the markdown spec, blind to
file-header comments, blind to DV plan descriptions, blind to security
notes in checklists. Yet most of an IP's *intent* lives in those prose
sources, not in code.

KGWeave closes the gap by extracting structural claims from prose using
LLM-assisted entity and relation extraction, then linking those claims
back to the RTL/SDC/IP-XACT entities they describe. Examples:

- A spec sentence "the cipher must complete in 14 cycles" becomes a
  `BehavioralClaim(latency=14)` node, linked to the relevant FSM, with a
  pending `covered_by` edge to whichever SVA enforces that latency
  (or surfaced as an *unverified claim* if no such SVA exists).
- A DV-plan testpoint description in HJSON becomes a `Testpoint` node
  linked via `covers` to the SVA assertions and via `tests` to the UVM
  test classes that realise it.
- A file-header comment block becomes intent metadata on the module it
  precedes, queryable as part of the module's facts.

This is the "fill the gap left by EDA" mission.

### 3. Blast-radius and what-if analysis

EDA tools tell you **whether** something broke (lint error, timing
violation, simulation mismatch). They do not tell you **what a change
touched** if nothing breaks. Silent change is the worst class of bug:
refactor a parameter's bit-width, no error fires, three downstream
consumers now silently truncate, ships to silicon.

KGWeave answers "if I change X, what is affected?" by graph traversal
across typed edges before EDA is run:

```
target = Parameter "KeyWidth"
↓ reverse-traverse: binds_parameter, instance_of, drives, reads,
                    references_signal, constrains_port, mentions,
                    covers, tests
↓ depth-N reachable set
→ "73 entities affected: 12 signals (4 with non-trivial bit-slices),
   4 instances, 3 SDC constraints, 2 spec sections, 5 SVAs,
   8 testplan entries, 1 IP-XACT register field"
```

This is impact analysis at the *intent* layer, not the netlist layer.
EDA can do limited netlist-level impact analysis after-the-fact;
KGWeave does it at the source level, before anything runs.

## Why one graph (not separate graphs per source)

The metal-stack analogy: a chip has many metal layers, but they share a
single substrate of vias and contacts. KGWeave's substrate is the set of
**canonical entities** (Port, Signal, ClockDomain, RTL_Module,
CSR_Register, Parameter) that every source layer ultimately points down
to. Layer-specific entities (ClockConstraint from SDC, Section from
markdown, Testpoint from DV plan, IPXACT_Port from IP-XACT) wrap and
annotate the canonical entities rather than duplicating them.

If we put each source in its own graph:

- **Fusion is broken.** `clk_main` becomes seven independent nodes
  instead of one, and the cross-source joins above become manual joins.
- **The answer to "what do we know about X" requires querying seven
  graphs and merging.** That merge is exactly the problem we are trying
  to solve, pushed back onto the user.
- **Layer drift becomes invisible.** When SDC says one thing about a
  clock and IP-XACT says another, separate graphs hide the
  disagreement. A unified graph with `extractor_source` tagging on every
  edge makes the disagreement queryable as a single set-difference.

The unified-graph-with-layer-tags model is the right shape. Each edge
already carries its layer of origin (`extractor_source` field). The next
foundational step is promoting that field to a first-class `layer`
concept with `subgraph_by_layer()` and `diff_layers()` APIs, so a user
can both see the unified view *and* drill into a single layer or diff
two layers — without ever splitting the underlying graph.

## What "match the spec" actually means

A unified graph plus prose extraction enables matching the spec to the
implementation, but the match strength varies by claim type. KGWeave is
explicit about this:

| Spec claim type | Match strength | Mechanism |
|---|---|---|
| Structural (ports, clocks, registers, bus interfaces) | Equivalence | IP-XACT diff against RTL — exact match expected |
| Behavioural (FSM transitions, latency, throughput) | Coverage | Spec claim → SVA assertion or DV testpoint that enforces it |
| Functional (correctness of an algorithm) | Coverage | Spec claim → suite of DV tests + assertions |
| Intent (security, low-power, constant-time) | Decomposition | Spec claim refines into a checklist of structural and behavioural sub-claims, each then matchable |

Every claim node in KGWeave carries a `verification_strength` attribute
naming which mechanism applies. The killer query then becomes:

> "What spec claims have no SVA backing, no DV test backing, and no
> decomposition into matchable sub-claims?"

That is the spec-completeness audit no EDA tool produces, because EDA
tools don't ingest the spec.

## How KGWeave fits next to EDA, not against it

KGWeave is best understood as the **fabric** that ties EDA outputs and
spec inputs together:

```
                 ┌──────────────────────────────────────┐
                 │        KGWeave Unified Graph         │
                 │  (canonical entities + layer tags)   │
                 └──────────────────────────────────────┘
                    ▲     ▲     ▲     ▲     ▲     ▲
                    │     │     │     │     │     │
   ┌───────────┐    │     │     │     │     │     │  ┌────────────┐
   │ RTL slang │────┘     │     │     │     │     └──│ Spec MD    │
   └───────────┘          │     │     │     │        └────────────┘
   ┌───────────┐          │     │     │     │        ┌────────────┐
   │ IP-XACT   │──────────┘     │     │     └────────│ DV plan    │
   └───────────┘                │     │              │ (testplan) │
   ┌───────────┐                │     │              └────────────┘
   │ SDC       │────────────────┘     │              ┌────────────┐
   └───────────┘                      │              │ SV comments│
                                      │              └────────────┘
                                      │
                          (lint / CDC / coverage *waiver*
                           files — declared exceptions only,
                           never coverage hit reports)
```

Pure structural validation (IP-XACT vs RTL ports, SDC syntactic check,
register-map consistency) can be done *either* by EDA *or* by KGWeave's
own diff over the unified graph. The *differentiating* work is the
completeness audit — everything an EDA tool cannot do because it does
not ingest the spec or the cross-layer relationships:

- Linking prose claims to RTL entities, assertions, and testpoints
- Auditing whether every spec claim has at least one testpoint, one
  assertion, and one coverpoint
- Tracing intent through file-header comments and DV-plan descriptions
- Cross-layer joins and blast-radius queries
- Spec-completeness reports

KGWeave deliberately does **not** ingest coverage hit reports
(URG/IMC), simulation logs, synthesis netlists, or post-route timing
reports. Those are validation truth and EDA tools already produce
them on a stable schedule. The audit job — *do these things even
exist for every spec claim?* — is upstream of EDA and is the gap
KGWeave fills.

## Why this matters now

Two pressures make this the right time:

**1. AI-native engineering interfaces.** RAG systems and agents need a
queryable graph of the design, not a directory of vendor-specific
formats. KGWeave is the substrate an LLM agent can reason over without
touching flexlm or a 50 GB EDA install.

**2. Spec-implementation drift is a real and expensive bug class.** The
prose spec, the IP-XACT, the SDC, the testplan, and the RTL are written
and maintained by different people on different schedules. They drift
silently. The cost of catching drift after tape-out is enormous; the
cost of catching it in CI on every commit is small — *if* the unified
graph and cross-layer queries exist. KGWeave is that infrastructure.

## Operating principles

- **One graph, many lenses.** Layer tags filter the view, never split
  the data.
- **Canonical entities are the spine.** Layer-specific nodes anchor to
  them; never duplicate canonicals.
- **Every edge carries provenance.** `extractor_source`, `evidence_span`,
  and `source` are non-negotiable so claims are auditable and
  conflicts are diagnosable.
- **Match strength is first-class.** A claim's verification mechanism
  (equivalence vs coverage vs decomposition) is a graph attribute, not
  a convention.
- **Don't reinvent EDA.** Ingest its declarative inputs and waiver
  files where useful; differentiate on the prose, completeness audit,
  and cross-layer work it cannot do. Never ingest coverage hit
  reports or simulation logs — those are EDA's domain and ingesting
  them blurs the audit/validation line.
- **Audit, don't validate.** KGWeave reports gaps in the *infrastructure
  of validation* (missing testpoints, missing assertions, missing
  coverpoints, claims with no enforcement). It does not report
  whether the validation passed. EDA is the authority for the latter.
- **Reproducible and repo-local.** Runs on a checkout in CI, no
  licences, no servers.
