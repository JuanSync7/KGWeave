# @summary
# dvsim hjson reader (Tier B Phase 2 + V3 #2). Parses dvsim
# *_sim_cfg.hjson regression configs (a lowRISC-authored open spec) and
# emits one BuildSystemLink per test entry, linking that test to the IP
# under test (`dut:` field, falling back to `name:`). V3 #2 adds
# recursive `import_cfgs:` resolution with cycle protection, depth
# limiting, and `{proj_root}` token expansion so chip-level cfgs that
# contain only imports surface their per-IP tests.
# Confidence tier: high (machine-readable, used by dvsim).
# Exports: DvsimHjsonReader
# Deps: hjson, pathlib, kgweave.knowledge_graph.common.sw_test_buildsys
# @end-summary
"""dvsim sim_cfg.hjson reader (lowRISC's regression spec format)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from kgweave.knowledge_graph.common.sw_test_buildsys import BuildSystemLink

try:  # pragma: no cover - import guard
    import hjson
except ImportError:  # pragma: no cover
    hjson = None  # type: ignore[assignment]

__all__ = ["DvsimHjsonReader"]

_logger = logging.getLogger("rag.knowledge_graph.buildsys_dvsim")

DEFAULT_MAX_IMPORT_DEPTH = 5


class DvsimHjsonReader:
    """Reader for dvsim's ``*_sim_cfg.hjson`` regression configs.

    Each cfg file declares the IP module under test and a ``tests:``
    array. We emit one ``BuildSystemLink`` per (test entry, module),
    using ``dut:`` if present (the actual SV module name) and falling
    back to ``name:`` otherwise.

    The ``test_path`` field is set to the test entry's ``name`` field —
    callers cross-reference it against on-disk test files by basename.
    In conventional dvsim flows test names match SV testbench filenames
    closely enough that this is the only sensible key without
    duplicating filelist resolution here.

    V3 #2 — ``import_cfgs:`` recursion
    ----------------------------------
    Chip-level dvsim layouts typically use cfgs (for example, the
    OpenTitan-style ``chip_earlgrey_asic_sim_cfg.hjson``) that carry
    only an ``import_cfgs:`` list pointing to per-IP cfgs. Without recursion the
    chip cfg contributes zero links. This reader follows ``import_cfgs:``
    transitively, with cycle protection (visited-set keyed on the
    resolved absolute path) and a configurable depth limit
    (``max_import_depth``, default 5). Tests reached via recursion carry
    two extra ``raw_match`` keys for provenance:

    - ``dvsim_import_chain``: list of cfg paths from root to the cfg the
      test was defined in (most recent last, length ≥ 2 for transitive).
    - ``dvsim_root_cfg``: the original entry-point cfg path.

    The ``source_file`` attribution is preserved as the cfg the test was
    *defined in* (not the importing root) so downstream consumers see the
    most specific provenance.

    Path tokens
    -----------
    Import paths may use ``{proj_root}`` which expands to the
    ``project_root`` passed to ``read()``. Bare relative paths resolve
    against the importing cfg's parent directory.
    """

    name = "dvsim_hjson"

    # Default glob accepts both ``*_sim_cfg.hjson`` (regression configs)
    # and ``*_fpv_cfg.hjson`` (formal property verification configs);
    # both share the same schema (name/dut/tests[]) and are tool-agnostic
    # for our purposes. Callers can narrow via the ``glob`` arg.
    def __init__(
        self,
        glob: str = "**/*_cfg.hjson",
        max_import_depth: int = DEFAULT_MAX_IMPORT_DEPTH,
    ) -> None:
        self._glob = glob
        self._max_import_depth = max_import_depth

    def applies_to(self, project_root: Path) -> bool:
        try:
            return next(project_root.glob(self._glob), None) is not None
        except OSError:
            return False

    def read(self, project_root: Path) -> List[BuildSystemLink]:
        if hjson is None:  # pragma: no cover
            _logger.warning("hjson package not installed; skipping dvsim reader")
            return []
        project_root = Path(project_root)
        links: List[BuildSystemLink] = []
        for cfg_path in sorted(project_root.glob(self._glob)):
            links.extend(
                self._resolve_cfg(
                    cfg_path=cfg_path,
                    project_root=project_root,
                    visited=set(),
                    chain=[],
                    root_cfg=cfg_path.resolve(),
                    depth=0,
                )
            )
        return links

    # ------------------------------------------------------------------
    # Internal: recursive cfg resolution
    # ------------------------------------------------------------------

    def _resolve_cfg(
        self,
        cfg_path: Path,
        project_root: Path,
        visited: Set[Path],
        chain: List[Path],
        root_cfg: Path,
        depth: int,
    ) -> List[BuildSystemLink]:
        """Parse a cfg, emit own tests, then recurse into ``import_cfgs:``."""
        try:
            resolved_path = cfg_path.resolve()
        except OSError:
            resolved_path = cfg_path

        if resolved_path in visited:
            _logger.warning(
                "dvsim: cycle detected importing %s (chain: %s); breaking",
                resolved_path,
                " -> ".join(str(p) for p in chain),
            )
            return []

        if depth > self._max_import_depth:
            _logger.warning(
                "dvsim: max import depth %d exceeded at %s; stopping recursion",
                self._max_import_depth,
                resolved_path,
            )
            return []

        try:
            text = cfg_path.read_text(errors="replace")
        except OSError as exc:
            _logger.warning("dvsim: cannot read %s: %s", cfg_path, exc)
            return []
        try:
            data = hjson.loads(text)
        except Exception as exc:  # noqa: BLE001 — hjson raises various types
            _logger.warning("dvsim: malformed hjson at %s: %s", cfg_path, exc)
            return []
        if not isinstance(data, dict):
            return []

        # Mark visited *for this DFS branch*. We pass a fresh chain at each
        # recursion so siblings don't see each other in the chain, but the
        # visited-set is shared per-branch to break cycles.
        new_visited = visited | {resolved_path}
        new_chain = chain + [resolved_path]

        out: List[BuildSystemLink] = []

        # 1. Own tests first (union semantics — own tests + imported tests).
        own_links = self._emit_own_tests(
            data=data,
            cfg_path=resolved_path,
            chain=new_chain,
            root_cfg=root_cfg,
        )
        out.extend(own_links)

        # 2. Recurse into import_cfgs.
        imports = data.get("import_cfgs") or []
        if isinstance(imports, list):
            for raw_target in imports:
                if not isinstance(raw_target, str):
                    continue
                target = self._resolve_import_path(
                    raw_target=raw_target,
                    cfg_dir=cfg_path.parent,
                    project_root=project_root,
                )
                if target is None:
                    continue
                if not target.exists():
                    _logger.warning(
                        "dvsim: import_cfgs target not found: %s "
                        "(referenced by %s)",
                        target,
                        cfg_path,
                    )
                    continue
                out.extend(
                    self._resolve_cfg(
                        cfg_path=target,
                        project_root=project_root,
                        visited=new_visited,
                        chain=new_chain,
                        root_cfg=root_cfg,
                        depth=depth + 1,
                    )
                )

        return out

    def _emit_own_tests(
        self,
        data: Dict[str, Any],
        cfg_path: Path,
        chain: List[Path],
        root_cfg: Path,
    ) -> List[BuildSystemLink]:
        """Emit ``BuildSystemLink``s for this cfg's own ``tests:`` array.

        ``chain`` here is the full path from the root cfg to ``cfg_path``
        inclusive (length 1 for direct, ≥ 2 for transitively-imported).
        """
        # `dut:` is the real SV module name when present (sometimes name is
        # a variant like aes_masked but dut is still aes).
        module = data.get("dut") or data.get("name")
        if not module or not isinstance(module, str):
            return []
        tests = data.get("tests") or []
        if not isinstance(tests, list):
            return []
        out: List[BuildSystemLink] = []
        seen_names: Set[str] = set()
        is_transitive = len(chain) >= 2
        chain_strs = [str(p) for p in chain] if is_transitive else None
        root_str = str(root_cfg) if is_transitive else None
        for entry in tests:
            if not isinstance(entry, dict):
                continue
            test_name = entry.get("name")
            if not test_name or not isinstance(test_name, str):
                continue
            if test_name in seen_names:
                continue
            seen_names.add(test_name)
            raw_match: Dict[str, Any] = {
                "name": test_name,
                "module": module,
                "uvm_test": entry.get("uvm_test"),
            }
            attributes: Dict[str, Any] = {}
            if chain_strs is not None:
                raw_match["dvsim_import_chain"] = chain_strs
                raw_match["dvsim_root_cfg"] = root_str
                attributes["dvsim_import_chain"] = chain_strs
                attributes["dvsim_root_cfg"] = root_str
            link_kwargs: Dict[str, Any] = dict(
                test_path=test_name,
                module_name=module,
                source_format=self.name,
                source_file=str(cfg_path),
                confidence_tier="high",
                raw_match=raw_match,
            )
            # ``attributes`` is a recently-added optional field on
            # BuildSystemLink; pass it positionally only when populated and
            # supported by the dataclass to avoid TypeError on older
            # versions that may be checked out alongside this code.
            try:
                out.append(BuildSystemLink(attributes=attributes, **link_kwargs))
            except TypeError:
                out.append(BuildSystemLink(**link_kwargs))
        return out

    def _resolve_import_path(
        self,
        raw_target: str,
        cfg_dir: Path,
        project_root: Path,
    ) -> Optional[Path]:
        """Expand ``{proj_root}`` and resolve relative paths.

        Returns ``None`` if the path string is malformed (e.g. empty
        after stripping). Existence is checked by the caller.
        """
        s = raw_target.strip()
        if not s:
            return None
        # Token expansion — dvsim historically uses {proj_root}.
        s = s.replace("{proj_root}", str(project_root))
        candidate = Path(s)
        if not candidate.is_absolute():
            candidate = cfg_dir / candidate
        try:
            return candidate.resolve()
        except OSError:
            return candidate
