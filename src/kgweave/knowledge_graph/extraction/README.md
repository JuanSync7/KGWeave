<!-- @summary
Entity and relationship extraction sub-package with multiple extractor implementations.
@end-summary -->

# extraction/ — Entity and Relationship Extractors

All extractors implement the `EntityExtractor` protocol defined in `base.py`.

## Files

| File | Phase | Purpose |
|------|-------|---------|
| `base.py` | 1 | `EntityExtractor` protocol — `extract()`, `extract_entities()`, `extract_relations()` |
| `regex_extractor.py` | 1 | Rule-based entity extraction with YAML schema awareness |
| `gliner_extractor.py` | 1 | GLiNER zero-shot NER model extraction |
| `llm_extractor.py` | 1b | LLM structured-output extraction with JSON schema |
| `parser_extractor.py` | 1b | tree-sitter-verilog SystemVerilog parser |
| `python_parser.py` | 2 | Python AST-based extractor (classes, functions, imports, constants) |
| `bash_parser.py` | 2 | Regex-based Bash script extractor (functions, exported vars, sourced files) |

## Adding a New Extractor

1. Create `my_extractor.py` implementing the `EntityExtractor` protocol
2. Add a config toggle (`enable_my_extractor`) to `KGConfig` in `common/types.py`
3. Wire the env var in `config/settings.py`
4. Export from `extraction/__init__.py`
5. Register in `extractor_priority` list in `KGConfig`
6. Add the extractor's `(source_type, target_type, predicate)` rows to
   `EXTRACTOR_PREDICATE_MATRIX` in
   `tests/knowledge_graph/test_backend_predicate_collisions.py`
7. Add at least one **round-trip integration test** (see below)

## Round-Trip Test Convention

**Every extractor must include at least one test that:**

1. Calls `extract(text)` to produce entities and triples,
2. Pushes them through `NetworkXBackend.upsert_entities()` and
   `upsert_triples()`,
3. Reads them back via `get_outgoing_edges()` / `get_all_entities()` /
   `query_neighbors_typed()`, and asserts the predicates and entity
   names survive the round-trip.

This catches the class of bug where an extractor emits N triples but the
backend stores fewer (e.g. NetworkX `DiGraph` collapsing parallel edges
between the same `(subject, object)` pair). A real instance of this:
the slang extractor emitted both `connects_to` and `drives` between the
same instance-port and net pair; the second silently shadowed the first
in storage. Every unit test passed; the bug only surfaced on a real
OpenTitan integration query that depended on directional info.

Canonical example: `tests/knowledge_graph/test_backend_predicate_collisions.py`
documents the predicate matrix and the known DiGraph hazards.
Per-extractor round-trips live in `tests/knowledge_graph/test_extractor_round_trips.py`
and the existing `test_*_extractor*.py` / `test_slang_hierarchy.py` files.
