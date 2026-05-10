"""Entity and relationship extraction sub-package for the KG subsystem.

Contains LLM, SV-parser, GLiNER, regex, Python, and Bash extractor implementations.
"""

from kgweave.knowledge_graph.extraction.base import EntityExtractor
from kgweave.knowledge_graph.extraction.regex_extractor import RegexEntityExtractor, STOPWORDS
from kgweave.knowledge_graph.extraction.llm_extractor import LLMEntityExtractor
from kgweave.knowledge_graph.extraction.parser_extractor import SVParserExtractor
from kgweave.knowledge_graph.extraction.gliner_extractor import GLiNEREntityExtractor
from kgweave.knowledge_graph.extraction.python_parser import PythonParserExtractor
from kgweave.knowledge_graph.extraction.bash_parser import BashParserExtractor
from kgweave.knowledge_graph.extraction.markdown_doc_extractor import (
    MarkdownDocExtractor,
)
from kgweave.knowledge_graph.extraction.hjson_csr_extractor import (
    HJSONCSRExtractor,
)
from kgweave.knowledge_graph.extraction.sdc_extractor import (
    SDCExtractor,
    SDC_SOURCE,
)
from kgweave.knowledge_graph.extraction.ipxact_extractor import (
    IPXACTExtractor,
    IPXACT_SOURCE,
)
from kgweave.knowledge_graph.extraction.testplan_extractor import (
    TestplanExtractor,
    TESTPLAN_SOURCE,
)
from kgweave.knowledge_graph.extraction.dv_test_realization_extractor import (
    DVTestRealizationExtractor,
    DV_TEST_REALIZATION_SOURCE,
)
from kgweave.knowledge_graph.extraction.spec_claim_extractor import (
    SpecClaimExtractor,
    LLM_DOC_SOURCE,
    CLAIM_EXTRACTION_PROMPT,
    FakeLLMProvider,
)
from kgweave.knowledge_graph.extraction.testplan_normalizer import (
    TestplanNormalizer,
    TESTPLAN_NORMALIZER_PROMPT,
)
from kgweave.knowledge_graph.extraction.cpp_extractor import (
    CppRefModelExtractor,
    CPP_REF_MODEL_SOURCE,
    extract_dpi_boundaries,
    extract_dpi_boundaries_with_scope,
    build_dpi_boundary_entities,
    DPI_BOUNDARY_SOURCE,
)
from kgweave.knowledge_graph.extraction.sw_test_extractor import (
    SWTestExtractor,
    SW_TEST_SOURCE,
)
from kgweave.knowledge_graph.extraction.uvm_sample_extractor import (
    UVMSampleExtractor,
    UVM_SAMPLE_SOURCE,
)

__all__ = [
    "EntityExtractor",
    "RegexEntityExtractor",
    "GLiNEREntityExtractor",
    "LLMEntityExtractor",
    "SVParserExtractor",
    "PythonParserExtractor",
    "BashParserExtractor",
    "MarkdownDocExtractor",
    "HJSONCSRExtractor",
    "SDCExtractor",
    "SDC_SOURCE",
    "IPXACTExtractor",
    "IPXACT_SOURCE",
    "TestplanExtractor",
    "TESTPLAN_SOURCE",
    "DVTestRealizationExtractor",
    "DV_TEST_REALIZATION_SOURCE",
    "SpecClaimExtractor",
    "LLM_DOC_SOURCE",
    "CLAIM_EXTRACTION_PROMPT",
    "FakeLLMProvider",
    "TestplanNormalizer",
    "TESTPLAN_NORMALIZER_PROMPT",
    "STOPWORDS",
    "CppRefModelExtractor",
    "CPP_REF_MODEL_SOURCE",
    "extract_dpi_boundaries",
    "extract_dpi_boundaries_with_scope",
    "build_dpi_boundary_entities",
    "DPI_BOUNDARY_SOURCE",
    "SWTestExtractor",
    "SW_TEST_SOURCE",
    "UVMSampleExtractor",
    "UVM_SAMPLE_SOURCE",
]

# --- Auto-generated re-exports (fix_encapsulation.py) ---
from kgweave.knowledge_graph.extraction.sv_connectivity import (
    SlangHierarchyAnalyzer,
    SVConnectivityAnalyzer,
    SV_CONNECTIVITY_SOURCE,
)
from kgweave.knowledge_graph.extraction.sv_dataflow_extractor import (
    SVDataflowExtractor,
    SV_DATAFLOW_SOURCE,
)
from kgweave.knowledge_graph.extraction.sv_v2_integration import (
    V2IntegrationDriver,
    V2_INTEGRATION_SOURCE,
)
__all__ += [
    "SVDataflowExtractor",
    "SV_DATAFLOW_SOURCE",
    "V2IntegrationDriver",
    "V2_INTEGRATION_SOURCE",
]
