"""Loads the shared Excel formula evaluator from projects/_shared.

One evaluator with one set of bugs is easier to trust than a copy per project,
so it lives outside this directory. See projects/_shared/README.md.
"""

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "_shared" / "xlformula.py"

_spec = importlib.util.spec_from_file_location("xlformula", _PATH)
xlformula = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(xlformula)

Evaluator = xlformula.Evaluator
FormulaError = xlformula.FormulaError
