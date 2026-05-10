# @summary
# SystemVerilog parser-based structural entity extraction using pyslang's
# syntax tree. Walks ModuleDeclaration / InterfaceDeclaration / PackageDeclaration
# nodes to extract modules, ports, parameters, signals, instances, generates,
# tasks/functions, and package imports.
# Exports: SVParserExtractor, AST_TO_SCHEMA_MAP, VALID_EXTENSIONS, KNOWN_UNSUPPORTED
# Deps: pyslang (hard), kgweave.knowledge_graph.common
# @end-summary
"""SystemVerilog parser-based structural entity extraction (pyslang-backed).

Uses ``pyslang.SyntaxTree.fromText`` for deterministic syntax-level extraction
of RTL structural entities (modules, ports, parameters, instances, signals,
interfaces, packages, generates, tasks/functions). Replaces the prior
tree-sitter-verilog implementation, which emitted ERROR nodes on real-world
OpenTitan SV (notably aes_control.sv, aes_core.sv, aes_sbox.sv, etc.) and
silently produced no entities for those files. pyslang's parser handles the
full LRM and degrades gracefully on individual malformed constructs without
losing the rest of the file.

All results are tagged with ``extractor_source="sv_parser"``. Entity names
for sub-module items are namespaced as ``"<module>.<name>"`` to match the
convention used by ``SlangHierarchyAnalyzer`` (see ``sv_connectivity.py``);
this lets per-file structural entities and elaborated hierarchy edges line
up on the same canonical IDs in the graph.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterator, List, Optional, Set, Tuple

from kgweave.knowledge_graph.common import (
    Entity,
    ExtractionResult,
    Triple,
)
from kgweave.knowledge_graph.common import (
    KGConfig,
    SchemaDefinition,
)

# Hard dependency: import errors are fatal. pyslang is listed in pyproject.toml.
import pyslang as _ps  # noqa: E402

__all__ = [
    "SVParserExtractor",
    "AST_TO_SCHEMA_MAP",
    "VALID_EXTENSIONS",
    "KNOWN_UNSUPPORTED",
]

logger = logging.getLogger("kgweave.knowledge_graph.sv_parser")

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

VALID_EXTENSIONS: frozenset = frozenset({".sv", ".v", ".svh"})

# Mapping from pyslang SyntaxKind names (or substrings) to our YAML schema
# entity types. Kept as a public dict for documentation / debugging — the
# extraction code dispatches on SyntaxKind directly rather than looking up
# in this dict, but external callers may want to know which kinds map to
# which schema types.
AST_TO_SCHEMA_MAP: dict[str, str] = {
    "ModuleDeclaration": "RTL_Module",
    "InterfaceDeclaration": "Interface",
    "PackageDeclaration": "Package",
    "ImplicitAnsiPort": "Port",
    "ExplicitAnsiPort": "Port",
    "NonAnsiPort": "Port",
    "ParameterDeclaration": "Parameter",
    "ParameterDeclarationStatement": "Parameter",
    "TypeParameterDeclaration": "Parameter",
    "NetDeclaration": "Signal",
    "DataDeclaration": "Signal",
    "HierarchyInstantiation": "Instance",
    "GenerateRegion": "Generate",
    "LoopGenerate": "Generate",
    "IfGenerate": "Generate",
    "TaskDeclaration": "Task_Function",
    "FunctionDeclaration": "Task_Function",
}

KNOWN_UNSUPPORTED: List[str] = [
    "bind",
    "cross_module_reference",
    "uvm_macro",
    "clock_domain_crossing",  # REQ-KG-1b-208 — deferred stretch goal
]


# ---------------------------------------------------------------------------
# Helpers — pyslang syntax tree walking
# ---------------------------------------------------------------------------


def _kind_str(node: Any) -> str:
    """Return the SyntaxKind / TokenKind of *node* as a string, or ''."""
    k = getattr(node, "kind", None)
    return str(k) if k is not None else ""


def _iter_children(node: Any) -> Iterator[Any]:
    """Iterate child nodes of a pyslang syntax node, swallowing TypeError.

    pyslang syntax nodes implement ``__iter__`` but Tokens do not. Iterating
    a Token raises TypeError; we catch it and yield nothing so callers can
    descend uniformly.
    """
    try:
        for c in node:
            yield c
    except TypeError:
        return


def _token_text(tok: Any) -> Optional[str]:
    """Return ``tok.valueText`` for a pyslang Token, or None.

    pyslang Tokens expose ``valueText`` (the lexed identifier text without
    surrounding whitespace/trivia). Some node ``.name`` attributes are also
    Tokens, so this works uniformly. Returns None if the token has no
    usable value.
    """
    if tok is None:
        return None
    text = getattr(tok, "valueText", None)
    if text is None:
        # Fallback for raw strings (declarator names sometimes appear as str).
        if isinstance(tok, str):
            return tok.strip() or None
        return None
    text = text.strip()
    return text or None


def _find_kind(node: Any, target_substrs: Tuple[str, ...]) -> Iterator[Any]:
    """Yield descendants whose kind-string contains any of *target_substrs*.

    Does not descend into a matched node — same scoping behaviour as the
    legacy tree-sitter ``_find_descendants`` helper, so we don't double-count
    nested constructs (e.g. parameters inside a nested module's header).
    """
    k = _kind_str(node)
    for t in target_substrs:
        if t in k:
            yield node
            return
    for c in _iter_children(node):
        yield from _find_kind(c, target_substrs)


def _find_declarators(node: Any) -> Iterator[Any]:
    """Yield ``Declarator`` descendants. Does not descend into matched nodes."""
    if "Declarator" in _kind_str(node):
        yield node
        return
    for c in _iter_children(node):
        yield from _find_declarators(c)


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------


class SVParserExtractor:
    """Deterministic structural extractor for SystemVerilog using pyslang.

    Extracts entities and structural relationships from the parsed syntax
    tree. All results are tagged with ``extractor_source="sv_parser"``.
    Sub-module entity names are namespaced as ``"<module>.<name>"`` so that
    they line up with the elaborated hierarchy edges produced by
    ``SlangHierarchyAnalyzer``.
    """

    @property
    def name(self) -> str:
        """Extractor identifier reported in Entity.extractor_source."""
        return "sv_parser"

    def __init__(
        self,
        schema: SchemaDefinition,
        config: KGConfig,
    ) -> None:
        """Initialise with schema and config.

        Args:
            schema: Parsed YAML schema for type validation.
            config: KG runtime configuration.
        """
        self._schema = schema
        self._config = config

    # -- Public API ----------------------------------------------------------

    def extract(self, text: str, source: str = "") -> ExtractionResult:
        """Extract structural entities and relations from SV source text.

        Args:
            text: SystemVerilog source code as a string.
            source: File path or URI for provenance.

        Returns:
            ExtractionResult with entities and triples. Returns an empty
            result if pyslang fails to parse the text outright.
        """
        try:
            tree = _ps.SyntaxTree.fromText(text)
        except Exception:  # noqa: BLE001 — pyslang may raise various exceptions
            logger.warning("pyslang parse failed for %s", source, exc_info=True)
            return ExtractionResult()

        entities: List[Entity] = []
        triples: List[Triple] = []

        for decl in self._find_top_level_declarations(tree.root):
            kind = _kind_str(decl)
            if "ModuleDeclaration" in kind:
                e, t = self._extract_module(decl, source)
            elif "InterfaceDeclaration" in kind:
                e, t = self._extract_interface(decl, source)
            elif "PackageDeclaration" in kind:
                e, t = self._extract_package(decl, source)
            else:
                continue
            entities.extend(e)
            triples.extend(t)

        return ExtractionResult(entities=entities, triples=triples)

    def extract_file(self, file_path: str) -> ExtractionResult:
        """Extract from a SystemVerilog file on disk.

        Args:
            file_path: Path to a .sv, .v, or .svh file.

        Returns:
            ExtractionResult. Empty result for non-SV extensions.

        Raises:
            FileNotFoundError: If file_path does not exist.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if path.suffix not in VALID_EXTENSIONS:
            logger.debug(
                "Skipping non-SV file: %s (extension %s)", file_path, path.suffix
            )
            return ExtractionResult()

        text = path.read_text(encoding="utf-8", errors="replace")
        return self.extract(text, source=str(path))

    def extract_entities(self, text: str) -> Set[str]:
        """Return entity name strings from *text* (EntityExtractor protocol)."""
        result = self.extract(text)
        return {e.name for e in result.entities}

    def extract_relations(self, text: str, known_entities: Set[str]) -> List[Triple]:
        """Return relation triples from *text* (EntityExtractor protocol)."""
        return self.extract(text).triples

    # -- Internal: top-level discovery ---------------------------------------

    @staticmethod
    def _find_top_level_declarations(root: Any) -> List[Any]:
        """Find all top-level Module/Interface/Package declarations.

        Walks the syntax tree but does not descend into a matched declaration
        — nested module declarations (inside a generate, for example) are
        scoped as part of the enclosing module rather than promoted to the
        top level. This matches the legacy tree-sitter behaviour.

        ``tree.root`` may itself be a single ``ModuleDeclaration`` (single-
        module file) or a ``CompilationUnit`` containing many declarations.
        Both shapes are handled uniformly.
        """
        found: List[Any] = []
        targets = ("ModuleDeclaration", "InterfaceDeclaration", "PackageDeclaration")

        def walk(node: Any) -> None:
            k = _kind_str(node)
            for t in targets:
                if t in k:
                    found.append(node)
                    return
            for c in _iter_children(node):
                walk(c)

        walk(root)
        return found

    @staticmethod
    def _decl_name(decl: Any) -> Optional[str]:
        """Return the canonical name of a Module/Interface/Package decl."""
        for c in _iter_children(decl):
            if "Header" in _kind_str(c):
                return _token_text(getattr(c, "name", None))
        return None

    @staticmethod
    def _decl_header(decl: Any) -> Optional[Any]:
        """Return the header sub-node of a declaration, if any."""
        for c in _iter_children(decl):
            if "Header" in _kind_str(c):
                return c
        return None

    @staticmethod
    def _decl_body_members(decl: Any) -> Iterator[Any]:
        """Yield direct member statements inside a declaration body.

        The shape of a ``ModuleDeclaration`` is roughly::

            [attribute-list, header, body-list, end-keyword]

        where ``body-list`` is a ``SyntaxList`` of items. We yield items
        from the list(s) that come *after* the header — which excludes
        the parameter port list and the ANSI port list (those live inside
        the header and are extracted separately).
        """
        seen_header = False
        for c in _iter_children(decl):
            if "Header" in _kind_str(c):
                seen_header = True
                continue
            if not seen_header:
                continue
            if _kind_str(c) == "SyntaxKind.SyntaxList":
                for m in _iter_children(c):
                    yield m

    # -- Internal: per-declaration extractors --------------------------------

    def _extract_module(
        self, decl: Any, source: str
    ) -> Tuple[List[Entity], List[Triple]]:
        """Extract a module declaration and its children."""
        entities: List[Entity] = []
        triples: List[Triple] = []

        module_name = self._decl_name(decl)
        if module_name is None:
            logger.warning("Could not extract module name from declaration")
            return entities, triples

        entities.append(self._make_entity(module_name, "RTL_Module", source))

        # Header-resident declarations: parameter port list, ANSI port list.
        header = self._decl_header(decl)
        if header is not None:
            e, t = self._extract_header_parameters(header, module_name, source)
            entities.extend(e)
            triples.extend(t)
            e, t = self._extract_header_ports(header, module_name, source)
            entities.extend(e)
            triples.extend(t)

        # Body-resident: parameters, ports (non-ANSI), signals, instances,
        # generates, tasks/functions, imports.
        seen_param: Set[str] = set()
        seen_port: Set[str] = set()
        seen_signal: Set[str] = set()
        seen_instance: Set[str] = set()
        seen_pkg_import: Set[str] = set()
        seen_genfn: Set[str] = set()

        for member in self._decl_body_members(decl):
            mk = _kind_str(member)

            if "ParameterDeclarationStatement" in mk or "TypeParameterDeclaration" in mk:
                e, t = self._extract_parameters_in(member, module_name, source, seen_param)
                entities.extend(e)
                triples.extend(t)
            elif "PortDeclaration" in mk and "AnsiPort" not in mk:
                # Non-ANSI port declarations inside the body.
                e, t = self._extract_body_ports(member, module_name, source, seen_port)
                entities.extend(e)
                triples.extend(t)
            elif "NetDeclaration" in mk or "DataDeclaration" in mk:
                # data_declaration may be a package import in disguise; skip those.
                if self._is_import_declaration(member):
                    e, t = self._extract_imports(member, module_name, source, seen_pkg_import)
                    triples.extend(t)
                else:
                    e, t = self._extract_signals_in(member, module_name, source, seen_signal)
                    entities.extend(e)
                    triples.extend(t)
            elif "PackageImportDeclaration" in mk:
                e, t = self._extract_imports(member, module_name, source, seen_pkg_import)
                triples.extend(t)
            elif "HierarchyInstantiation" in mk:
                e, t = self._extract_instances_in(member, module_name, source, seen_instance)
                entities.extend(e)
                triples.extend(t)
            elif "GenerateRegion" in mk or "LoopGenerate" in mk or "IfGenerate" in mk:
                e, t = self._extract_generate(member, module_name, source, seen_genfn)
                entities.extend(e)
                triples.extend(t)
            elif "TaskDeclaration" in mk or "FunctionDeclaration" in mk:
                e, t = self._extract_task_function(member, module_name, source, seen_genfn)
                entities.extend(e)
                triples.extend(t)
            # Other member kinds (always blocks, modport, typedef, assertions,
            # specify blocks, etc.) are not represented as entities by this
            # extractor — they belong to other extractors / future tiers.

        return entities, triples

    def _extract_interface(
        self, decl: Any, source: str
    ) -> Tuple[List[Entity], List[Triple]]:
        """Extract an interface declaration.

        Reuses module extraction since pyslang represents interfaces with
        the same declaration shape; only the canonical entity type differs.
        """
        # Run the module extractor and then replace the top-level RTL_Module
        # entity with an Interface entity. Cheap and avoids duplicating logic.
        entities, triples = self._extract_module(decl, source)
        if entities and entities[0].type == "RTL_Module":
            top = entities[0]
            entities[0] = Entity(
                name=top.name,
                type="Interface",
                sources=top.sources,
                extractor_source=top.extractor_source,
            )
        return entities, triples

    def _extract_package(
        self, decl: Any, source: str
    ) -> Tuple[List[Entity], List[Triple]]:
        """Extract a package declaration (parameters + typedef-bearing items).

        Packages have no header port list / ANSI ports — only body items.
        We surface the package as an entity and contains-link any parameter
        declarations inside it so downstream queries can resolve
        ``mypkg.MY_CONST`` references.
        """
        entities: List[Entity] = []
        triples: List[Triple] = []

        pkg_name = self._decl_name(decl)
        if pkg_name is None:
            logger.warning("Could not extract package name from declaration")
            return entities, triples

        entities.append(self._make_entity(pkg_name, "Package", source))

        seen_param: Set[str] = set()
        for member in self._decl_body_members(decl):
            mk = _kind_str(member)
            if "ParameterDeclarationStatement" in mk or "TypeParameterDeclaration" in mk:
                e, t = self._extract_parameters_in(member, pkg_name, source, seen_param)
                entities.extend(e)
                triples.extend(t)

        return entities, triples

    # -- Internal: header extractors -----------------------------------------

    def _extract_header_parameters(
        self, header: Any, module_name: str, source: str
    ) -> Tuple[List[Entity], List[Triple]]:
        """Extract parameters from the parameter port list inside a header."""
        entities: List[Entity] = []
        triples: List[Triple] = []
        seen: Set[str] = set()

        for pd in _find_kind(
            header, ("ParameterDeclaration", "TypeParameterDeclaration")
        ):
            for d in _find_declarators(pd):
                pname = _token_text(getattr(d, "name", None))
                if pname is None or pname in seen:
                    continue
                seen.add(pname)
                qualified = f"{module_name}.{pname}"
                entities.append(
                    self._make_entity(qualified, "Parameter", source)
                )
                triples.append(
                    self._make_triple(module_name, "contains", qualified, source)
                )

        return entities, triples

    def _extract_header_ports(
        self, header: Any, module_name: str, source: str
    ) -> Tuple[List[Entity], List[Triple]]:
        """Extract ports from an ANSI / non-ANSI port list inside a header."""
        entities: List[Entity] = []
        triples: List[Triple] = []
        seen: Set[str] = set()

        port_kinds = (
            "ImplicitAnsiPort",
            "ExplicitAnsiPort",
            "InterfacePortHeader",  # safe — no Declarator inside, ignored
            "NonAnsiPort",
        )
        for port in _find_kind(header, port_kinds):
            # Direction lives on the port header's ``direction`` token
            # (``InputKeyword`` / ``OutputKeyword`` / ``InOutKeyword``).
            # ``valueText`` is the keyword text itself, which already
            # matches our normalized values.
            port_direction: Optional[str] = None
            try:
                p_header = getattr(port, "header", None)
                if p_header is not None:
                    dtok = getattr(p_header, "direction", None)
                    dtext = _token_text(dtok)
                    if dtext in ("input", "output", "inout"):
                        port_direction = dtext
            except Exception:
                port_direction = None
            for d in _find_declarators(port):
                pname = _token_text(getattr(d, "name", None))
                if pname is None or pname in seen:
                    continue
                seen.add(pname)
                qualified = f"{module_name}.{pname}"
                entities.append(
                    self._make_entity(
                        qualified, "Port", source, port_direction=port_direction,
                    )
                )
                triples.append(
                    self._make_triple(module_name, "contains", qualified, source)
                )

        return entities, triples

    # -- Internal: body extractors -------------------------------------------

    def _extract_parameters_in(
        self, node: Any, module_name: str, source: str, seen: Set[str]
    ) -> Tuple[List[Entity], List[Triple]]:
        """Extract parameter declarators reachable from *node*."""
        entities: List[Entity] = []
        triples: List[Triple] = []

        for d in _find_declarators(node):
            pname = _token_text(getattr(d, "name", None))
            if pname is None or pname in seen:
                continue
            seen.add(pname)
            qualified = f"{module_name}.{pname}"
            entities.append(self._make_entity(qualified, "Parameter", source))
            triples.append(
                self._make_triple(module_name, "contains", qualified, source)
            )

        return entities, triples

    def _extract_body_ports(
        self, node: Any, module_name: str, source: str, seen: Set[str]
    ) -> Tuple[List[Entity], List[Triple]]:
        """Extract non-ANSI port declarators from a body-level port_decl."""
        entities: List[Entity] = []
        triples: List[Triple] = []

        # Non-ANSI ``PortDeclaration`` exposes its direction token directly
        # at the top of the node (``direction`` attribute). Same normalized
        # values as the ANSI path.
        port_direction: Optional[str] = None
        try:
            dtok = getattr(node, "direction", None)
            dtext = _token_text(dtok)
            if dtext in ("input", "output", "inout"):
                port_direction = dtext
        except Exception:
            port_direction = None

        for d in _find_declarators(node):
            pname = _token_text(getattr(d, "name", None))
            if pname is None or pname in seen:
                continue
            seen.add(pname)
            qualified = f"{module_name}.{pname}"
            entities.append(
                self._make_entity(
                    qualified, "Port", source, port_direction=port_direction,
                )
            )
            triples.append(
                self._make_triple(module_name, "contains", qualified, source)
            )

        return entities, triples

    def _extract_signals_in(
        self, node: Any, module_name: str, source: str, seen: Set[str]
    ) -> Tuple[List[Entity], List[Triple]]:
        """Extract signal declarators from a NetDeclaration / DataDeclaration."""
        entities: List[Entity] = []
        triples: List[Triple] = []

        for d in _find_declarators(node):
            sname = _token_text(getattr(d, "name", None))
            if sname is None or sname in seen:
                continue
            seen.add(sname)
            qualified = f"{module_name}.{sname}"
            entities.append(self._make_entity(qualified, "Signal", source))
            triples.append(
                self._make_triple(module_name, "contains", qualified, source)
            )

        return entities, triples

    def _extract_instances_in(
        self, node: Any, module_name: str, source: str, seen: Set[str]
    ) -> Tuple[List[Entity], List[Triple]]:
        """Extract instances from a HierarchyInstantiation node.

        Produces:
          * Instance entities (one per HierarchicalInstance, namespaced)
          * ``contains``     module -> instance
          * ``instantiates`` module -> module-type-being-instantiated
        """
        entities: List[Entity] = []
        triples: List[Triple] = []

        # The instantiated module type is the first Identifier token directly
        # underneath the HierarchyInstantiation (before the optional
        # ParameterValueAssignment and the SeparatedList of HierarchicalInstance
        # children).
        module_type: Optional[str] = None
        for c in _iter_children(node):
            if _kind_str(c) == "TokenKind.Identifier":
                module_type = _token_text(c)
                break

        # Each HierarchicalInstance has an InstanceName sub-node carrying the
        # actual instance identifier (e.g. ``u_bar``). One declaration may
        # introduce several instances:  ``bar u_a (...), u_b (...);``
        for hi in _find_kind(node, ("HierarchicalInstance",)):
            inst_name: Optional[str] = None
            for c in _iter_children(hi):
                if "InstanceName" in _kind_str(c):
                    inst_name = _token_text(getattr(c, "name", None))
                    break

            if inst_name is None:
                continue
            if inst_name in seen:
                continue
            seen.add(inst_name)

            qualified = f"{module_name}.{inst_name}"
            entities.append(self._make_entity(qualified, "Instance", source))
            triples.append(
                self._make_triple(module_name, "contains", qualified, source)
            )
            if module_type:
                triples.append(
                    self._make_triple(module_name, "instantiates", module_type, source)
                )
                # Also emit an RTL_Module entity for the instance's module
                # type. Without this, prim_*/tlul_* sub-instances referenced
                # by aes.sv stay typed 'concept' on the backend (auto-created
                # by add_edge before any entity upsert), which breaks
                # RTL_Module-typed reachability traversals. Closes the
                # top-down hierarchy trace from `aes` through library cells.
                entities.append(self._make_entity(
                    module_type, "RTL_Module", source,
                ))

        return entities, triples

    def _extract_generate(
        self, node: Any, module_name: str, source: str, seen: Set[str]
    ) -> Tuple[List[Entity], List[Triple]]:
        """Emit a Generate entity for a generate region/loop/if (SHOULD)."""
        entities: List[Entity] = []
        triples: List[Triple] = []

        # Best-effort name: search for a Declarator-or-Identifier that could
        # serve as a generate-block label. If none, synthesise one from the
        # source position to keep the entity stable across runs.
        gen_name = self._first_identifier_text(node)
        if gen_name is None:
            # Use a position-based stable id.
            start = getattr(node, "sourceRange", None)
            offset = getattr(getattr(start, "start", None), "offset", 0) if start else 0
            gen_name = f"{module_name}__gen@{offset}"

        if gen_name in seen:
            return entities, triples
        seen.add(gen_name)

        qualified = f"{module_name}.{gen_name}" if "." not in gen_name else gen_name
        entities.append(self._make_entity(qualified, "Generate", source))
        triples.append(
            self._make_triple(module_name, "contains", qualified, source)
        )
        return entities, triples

    def _extract_task_function(
        self, node: Any, module_name: str, source: str, seen: Set[str]
    ) -> Tuple[List[Entity], List[Triple]]:
        """Emit a Task_Function entity for a task or function declaration."""
        entities: List[Entity] = []
        triples: List[Triple] = []

        # pyslang puts the task/function name as an attribute on the prototype
        # sub-node. Walk children for a name attribute.
        tf_name = self._first_identifier_text(node)
        if tf_name is None or tf_name in seen:
            return entities, triples
        seen.add(tf_name)

        qualified = f"{module_name}.{tf_name}"
        entities.append(self._make_entity(qualified, "Task_Function", source))
        triples.append(
            self._make_triple(module_name, "contains", qualified, source)
        )
        return entities, triples

    def _extract_imports(
        self, node: Any, module_name: str, source: str, seen: Set[str]
    ) -> Tuple[List[Entity], List[Triple]]:
        """Emit ``depends_on`` triples from a module to imported packages."""
        triples: List[Triple] = []

        for item in _find_kind(node, ("PackageImportItem",)):
            # PackageImportItem ::= package_identifier '::' (identifier | '*')
            # The package name is the first Identifier token under the item.
            pkg_name: Optional[str] = None
            for c in _iter_children(item):
                if _kind_str(c) == "TokenKind.Identifier":
                    pkg_name = _token_text(c)
                    break
            if pkg_name and pkg_name not in seen:
                seen.add(pkg_name)
                triples.append(
                    self._make_triple(module_name, "depends_on", pkg_name, source)
                )

        return [], triples

    # -- Helpers -------------------------------------------------------------

    @staticmethod
    def _is_import_declaration(node: Any) -> bool:
        """Return True if a DataDeclaration is actually a package import.

        SystemVerilog allows ``import pkg::*;`` to appear as a data
        declaration in some grammar productions; we don't want those to
        emit Signal entities.
        """
        for c in _iter_children(node):
            if "PackageImport" in _kind_str(c):
                return True
        return False

    @staticmethod
    def _first_identifier_text(node: Any) -> Optional[str]:
        """Return the first identifier-like name found in the subtree.

        Searches for either:
          * a child with a ``.name`` Token attribute (preferred — these are
            Declarator / InstanceName / Header style nodes), or
          * the first ``TokenKind.Identifier`` token,
        whichever comes first in the walk. Returns the stripped value text.
        """
        # First pass: any node carrying a name Token.
        named = getattr(node, "name", None)
        if named is not None:
            t = _token_text(named)
            if t:
                return t
        # Second pass: walk for a Declarator / InstanceName carrying .name.
        def walk(n: Any) -> Optional[str]:
            kn = _kind_str(n)
            if "Declarator" in kn or "InstanceName" in kn or "Header" in kn:
                t = _token_text(getattr(n, "name", None))
                if t:
                    return t
            for c in _iter_children(n):
                r = walk(c)
                if r:
                    return r
            return None
        r = walk(node)
        if r:
            return r
        # Final pass: first Identifier token.
        def walk2(n: Any) -> Optional[str]:
            if _kind_str(n) == "TokenKind.Identifier":
                t = _token_text(n)
                if t:
                    return t
            for c in _iter_children(n):
                r = walk2(c)
                if r:
                    return r
            return None
        return walk2(node)

    def _make_entity(
        self,
        name: str,
        entity_type: str,
        source: str,
        port_direction: Optional[str] = None,
    ) -> Entity:
        """Create an Entity with sv_parser attribution."""
        sources = [source] if source else []
        return Entity(
            name=name,
            type=entity_type,
            sources=sources,
            extractor_source=["sv_parser"],
            port_direction=port_direction,
        )

    def _make_triple(
        self, subject: str, predicate: str, obj: str, source: str
    ) -> Triple:
        """Create a Triple with sv_parser attribution."""
        return Triple(
            subject=subject,
            predicate=predicate,
            object=obj,
            source=source,
            extractor_source="sv_parser",
        )
