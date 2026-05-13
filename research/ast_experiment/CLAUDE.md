# Rule-writing conventions for the pyslang AST experiment

These conventions are specific to **this research directory** (`research/ast_experiment/`) — they capture lessons learned during the S14–S33 rule wave and exist so future agents adding new S-rules don't relearn them by breaking things.

Read this file before writing any new rule in `src/semantic/rules/`.

---

## 1. Dispatch on `.kind`, never on `_cls(node)`, for kinds that share a syntax class

pyslang's parser reuses one Python class for several `SyntaxKind` enum values to save memory. If you key your top-level dispatch on the class name, you silently mis-classify all but the first variant.

**Known shared classes — discriminate via `.kind`:**

| Python class | SyntaxKind values it carries |
|---|---|
| `ProceduralAssignStatementSyntax` | `ProceduralAssignStatement`, `ProceduralForceStatement` |
| `ProceduralDeassignStatementSyntax` | `ProceduralDeassignStatement`, `ProceduralReleaseStatement` |
| `EventTriggerStatementSyntax` | `BlockingEventTriggerStatement`, `NonblockingEventTriggerStatement` |
| `ImmediateAssertionStatementSyntax` | `ImmediateAssertStatement`, `ImmediateAssumeStatement`, `ImmediateCoverStatement` |
| `ModuleDeclarationSyntax` | `ModuleDeclaration`, `InterfaceDeclaration`, `PackageDeclaration`, `ProgramDeclaration` |
| `ExternModuleDeclSyntax` | extern `module` / `interface` / `program` (all one SyntaxKind, discriminator is `node.header.kind`) |
| `StructUnionTypeSyntax` (suspected) | `StructType`, `UnionType` |

**Rule:** before adding a new rule, run

```bash
python -c "import pyslang; cls = pyslang.<TheClassName>; print([k for k in pyslang.SyntaxKind.__members__ if ...])"
```

to confirm whether the class is shared. If it is, dispatch with a `{kind: variant_info}` dict (see `_PROC_DRIVE_VARIANTS`, `_EVENT_TRIGGER_VARIANTS` in `src/semantic/dispatch.py`).

`_cls(node) == "FooSyntax"` is fine for **navigation** (finding a specific child node type) inside a branch already entered via `.kind`. It is **not** fine as a top-level dispatch key.

---

## 2. Container-stack pattern — two variants, pick semantically

When a child rule needs to know "what's my enclosing semantic parent?", maintain a stack on `state` and consult `stack[-1]` from the child rule.

**Standard variant** — used for `class_stack` (S24) and `covergroup_stack` (S22): the container gets its own stack. New child rules (S25/S26/S27 for class; S23 for covergroup) explicitly check `state["class_stack"][-1]` to get the parent path. Use this when the container's children are **semantically different from module members** (methods, properties, constraints, coverpoints are not always-blocks or nets).

**Subtler variant** — used for checker (S28) and program (S30): push the container onto the **existing `state["module_stack"]`**. Any child rule that calls `_cur_module()` automatically picks up the checker/program as if it were a module. Use this when the LRM says the container *is* module-shaped (checkers hold properties/assertions/clocking exactly like modules; programs hold ports/initial blocks/instances exactly like modules) — this avoids writing new branches in S14/S15/S16/S17/S18.

**You typically need both** — they coexist. Class members and covergroup members go through the standard variant; properties/assertions/clocking inside a checker go through the subtler variant. Pick based on whether the children would conceptually live in a module or not.

Path keys follow the immediate semantic parent: `<class>.<method>`, `<covergroup>.<coverpoint>`, `<checker>.<property>`, `<package>.<class>.<method>`.

---

## 3. Score is a coverage metric, not a green-bar invariant

`scripts/score.py` walks the corpus, collects every `SyntaxKind` it encounters, and reports `(uncovered_count, total_in_corpus)`. When you add a new .sv corpus file, you typically introduce new SyntaxKinds that no rule covers yet — score goes up. That is **expected and fine**.

**The invariant for every commit is:** *score must not regress vs the parent commit.* It is **not** *score must be zero*.

**Mandatory honesty check before reporting:** every subagent must run the score script in its actual final state and report the literal output, not echo what the prompt expected. The S24 wave commit misreported "score=0" when the real value was ~35 — that was a hallucination caused by an over-strict prompt. Don't repeat it.

```bash
uv run python research/ast_experiment/scripts/score.py | head -2
```

Compare this to what `git show <parent>:research/ast_experiment/...` would have produced if you need certainty.

---

## 4. Edge-only kinds — some SyntaxKinds become edges, not nodes

Some pyslang SyntaxKinds exist only as syntactic connectors — they have no independent identity beyond linking two other entities. The right knowledge-graph representation is an **edge**, not a new node.

Examples shipped this way:
- `ExtendsClause` → `(class) -[extends]-> (parent_class)` (S25)
- `ImplementsClause` → `(class) -[implements]-> (interface_class)` (S25)
- `PackageImportDeclaration` → `(scope) -[imports]-> (package)` (S32)
- `PackageExportDeclaration` → `(scope) -[exports]-> (package)` (S32)

**Implementation pattern:** emit the edge **inline** in the parent's pass-1 branch (where the parent's `gid` is already bound) rather than dispatching the clause as its own rule. The metadata stub `(SyntaxKind.ExtendsClause, _s25_stub)` with `__rule_id__="S25"` still exists in the rule file as an **ownership marker** for the bucket1 checklist — it has no runtime function.

When a relationship-only kind references an entity that may not be in the name-index (forward ref, external library), emit the edge with `dst="_unresolved.<name>"` and `payload["unresolved"]=True` rather than failing.

---

## 5. Wrapper-kind dedup — register only the innermost queryable kind

SystemVerilog grammar nests "X at module scope" and "X inside a procedural block" differently in pyslang:

| User-level construct | Module scope parse | Procedural scope parse |
|---|---|---|
| `assert property (...)` | `ConcurrentAssertionMember` → `ConcurrentAssertionStatement` | bare `ConcurrentAssertionStatement` |
| `assert (...);` immediate | `ImmediateAssertionMember` → `ImmediateAssertStatement` | bare `ImmediateAssertStatement` |
| `label: <stmt>` | depends on stmt | `NamedLabel` wraps stmt |
| `assert #0 (...)` | `DeferredAssertion` wraps inner | `DeferredAssertion` wraps inner |

If you register both the wrapper kind AND the inner kind, the module-scope form double-promotes (once for the wrapper, once for the inner). If you register only the wrapper, the procedural-scope form silently doesn't promote (no wrapper exists).

**Rule:** register only the innermost statement kind. The wrapper stays CONTAINER (still appears in the structural graph; just no semantic promotion). One promotion fires in both contexts. Detect attributes that live on the wrapper (e.g. `DeferredAssertion` modifier) by walking direct children of the inner statement.

---

## 6. Hard invariants on every commit

Every S-rule commit must pass:

1. `uv run pytest research/ast_experiment/tests/ -x` — all green
2. `uv run python research/ast_experiment/scripts/score.py` — **no regression vs parent commit**
3. Byte-equal round-trip on every corpus file (`test_roundtrip.py` enforces; the `lift` → `unlift` pipeline must reconstruct source bytes exactly)
4. `grep -r "^import re\|^from re" research/ast_experiment/src/semantic/` — **must be empty**. Semantic rules must work off token kinds, child-node kinds, and identifier-token text. Never regex on source text. (The structural lift handles raw text; rules operate on the AST.)
5. The `rules/__init__.py` composition assertion holds — **no duplicate SyntaxKind** across rule files
6. `BUCKET_1_CHECKLIST.md` totals stay at **135 PROMOTE / 88 CONTAINER / 213 BLOB / 42 DIRECTIVE / 58 OOS = 536** (regenerate via `uv run python research/ast_experiment/scripts/build_bucket1_checklist.py`)

Losslessness is guaranteed structurally: S-rules can only **mutate `node["semantic"]`** or **append to `graph["edges"]`** — neither path is read by `unlift.py`. If you find yourself wanting to modify `node["children"]` / `node["tokens"]` / `node["text"]`, you're outside the semantic layer — stop.

---

## TDD/Ralph loop for a new S-rule

1. Confirm the exact `pyslang.SyntaxKind` value(s). Note any shared syntax classes (lesson 1).
2. Decide: is it a node or an edge (lesson 4)? Is it a wrapper of an inner kind (lesson 5)?
3. Decide the parent-resolution strategy: existing `module_stack`, new dedicated stack, or push onto `module_stack` (lesson 2)?
4. Add corpus exercising the construct. All `.sv` corpus files live under `research/ast_experiment/corpus/`. Prefer extending existing files; create a new `corpus/<concept>_corpus.sv` only when the construct doesn't fit the RTL fifo example (classes, primitives, externs all earned their own files).
5. Write tests **first**, run → red, confirm failure mode is the missing rule (not a typo).
6. Implement in `dispatch.py` pass-1, with a metadata stub in `rules/<file>.py` carrying `__rule_id__="S<N>"`.
7. Run all six invariants → green, **honestly report** the score number (lesson 3).
8. Commit `iter-NNN: ship S<N> <kind-or-concept> promotion`.
