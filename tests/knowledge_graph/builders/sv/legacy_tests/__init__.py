"""Package marker so legacy SV builder tests get fully-qualified module names.

Without this file, basenames like ``test_structure`` collide with the live
``research/ast_experiment/tests/test_structure.py`` when both trees are
collected in a single pytest invocation.
"""
