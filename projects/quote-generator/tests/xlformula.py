"""A very small Excel formula evaluator — just enough for QuoteTool.xlsx.

Why this exists: the workbook is the deliverable, and a workbook whose formulas
were never executed is an untested deliverable. There is no Excel on a CI box,
so the tests evaluate the generated formulas here and compare the result against
quotekit/pricing.py. If the two ever disagree, the build fails.

Supported: IF, INDEX, MATCH (exact only), LOOKUP (sorted vector form), IFERROR,
MIN, MAX, ROUND, SUM, TODAY; the operators + - * / ^ & = <> < <= > >=; numbers,
quoted strings, cell and range references with or without a sheet prefix.
Anything else raises, so an unsupported formula fails loudly instead of quietly
returning the wrong number.
"""

import re
from datetime import date

TOKEN = re.compile(
    r"""
    (?P<string>"(?:[^"]|"")*")
  | (?P<ref>(?:'[^']+'|[A-Za-z_][A-Za-z0-9_.]*)?!?\$?[A-Z]{1,3}\$?[0-9]{1,7}
            (?::\$?[A-Z]{1,3}\$?[0-9]{1,7})?)
  | (?P<func>[A-Za-z][A-Za-z0-9_.]*(?=\())
  | (?P<number>[0-9]+(?:\.[0-9]+)?)
  | (?P<op><>|<=|>=|[+\-*/^&=<>])
  | (?P<punct>[(),])
  | (?P<space>\s+)
    """,
    re.VERBOSE,
)

COLUMN = re.compile(r"^(?:(?:'([^']+)'|([A-Za-z_][A-Za-z0-9_.]*))!)?\$?([A-Z]{1,3})\$?([0-9]+)$")


class FormulaError(ValueError):
    pass


class _ExcelError(Exception):
    """An in-formula error value, e.g. what #N/A means to IFERROR."""


def _tokenize(text):
    tokens, position = [], 0
    while position < len(text):
        match = TOKEN.match(text, position)
        if not match:
            raise FormulaError(f"cannot tokenize at {text[position:position + 20]!r}")
        position = match.end()
        kind = match.lastgroup
        if kind != "space":
            tokens.append((kind, match.group()))
    return tokens


class _Parser:
    """Recursive descent over the token list; returns a nested tuple AST."""

    COMPARISONS = {"=", "<>", "<", "<=", ">", ">="}

    def __init__(self, tokens):
        self.tokens = tokens
        self.index = 0

    def peek(self):
        return self.tokens[self.index] if self.index < len(self.tokens) else (None, None)

    def take(self, expected=None):
        kind, value = self.peek()
        if expected is not None and value != expected:
            raise FormulaError(f"expected {expected!r}, found {value!r}")
        self.index += 1
        return kind, value

    def parse(self):
        node = self.comparison()
        if self.index != len(self.tokens):
            raise FormulaError(f"trailing tokens from {self.peek()!r}")
        return node

    def comparison(self):
        node = self.concat()
        while self.peek()[1] in self.COMPARISONS:
            operator = self.take()[1]
            node = ("op", operator, node, self.concat())
        return node

    def concat(self):
        node = self.additive()
        while self.peek()[1] == "&":
            self.take()
            node = ("op", "&", node, self.additive())
        return node

    def additive(self):
        node = self.multiplicative()
        while self.peek()[1] in ("+", "-"):
            operator = self.take()[1]
            node = ("op", operator, node, self.multiplicative())
        return node

    def multiplicative(self):
        node = self.power()
        while self.peek()[1] in ("*", "/"):
            operator = self.take()[1]
            node = ("op", operator, node, self.power())
        return node

    def power(self):
        node = self.unary()
        while self.peek()[1] == "^":
            self.take()
            node = ("op", "^", node, self.unary())
        return node

    def unary(self):
        if self.peek()[1] in ("-", "+"):
            operator = self.take()[1]
            return ("unary", operator, self.unary())
        return self.primary()

    def primary(self):
        kind, value = self.take()
        if kind == "number":
            return ("number", float(value))
        if kind == "string":
            return ("string", value[1:-1].replace('""', '"'))
        if kind == "ref":
            return ("ref", value)
        if kind == "func":
            self.take("(")
            args = []
            if self.peek()[1] != ")":
                args.append(self.comparison())
                while self.peek()[1] == ",":
                    self.take()
                    args.append(self.comparison())
            self.take(")")
            return ("call", value.upper(), args)
        if value == "(":
            node = self.comparison()
            self.take(")")
            return node
        raise FormulaError(f"unexpected token {value!r}")


class Evaluator:
    """Evaluates formulas against an openpyxl workbook, memoising cell values."""

    def __init__(self, workbook, default_sheet):
        self.workbook = workbook
        self.default_sheet = default_sheet
        self._cache = {}
        self._in_progress = set()

    # -- reference handling -------------------------------------------------
    def _split(self, reference):
        if ":" in reference:
            left, right = reference.split(":", 1)
            sheet, column, row = self._parse_cell(left)
            _, column2, row2 = self._parse_cell(right if "!" in right else f"{sheet}!{right}")
            return sheet, (column, row), (column2, row2)
        sheet, column, row = self._parse_cell(reference)
        return sheet, (column, row), (column, row)

    def _parse_cell(self, reference):
        match = COLUMN.match(reference)
        if not match:
            raise FormulaError(f"bad reference {reference!r}")
        quoted, plain, column, row = match.groups()
        return (quoted or plain or self.default_sheet), column, int(row)

    def cell_value(self, sheet_name, column, row):
        key = (sheet_name, column, row)
        if key in self._cache:
            return self._cache[key]
        if key in self._in_progress:
            raise FormulaError(f"circular reference at {sheet_name}!{column}{row}")

        raw = self.workbook[sheet_name][f"{column}{row}"].value
        if isinstance(raw, str) and raw.startswith("="):
            self._in_progress.add(key)
            try:
                value = self.evaluate(raw, sheet_name)
            finally:
                self._in_progress.discard(key)
        else:
            value = raw
        self._cache[key] = value
        return value

    def range_values(self, reference):
        sheet, (col1, row1), (col2, row2) = self._split(reference)
        from openpyxl.utils import column_index_from_string, get_column_letter

        start_col, end_col = column_index_from_string(col1), column_index_from_string(col2)
        values = []
        for row in range(row1, row2 + 1):
            for column in range(start_col, end_col + 1):
                values.append(self.cell_value(sheet, get_column_letter(column), row))
        return values

    # -- evaluation ---------------------------------------------------------
    def evaluate(self, formula, sheet_name=None):
        previous = self.default_sheet
        if sheet_name:
            self.default_sheet = sheet_name
        try:
            text = formula[1:] if formula.startswith("=") else formula
            return self._eval(_Parser(_tokenize(text)).parse())
        finally:
            self.default_sheet = previous

    def _scalar(self, node):
        value = self._eval(node)
        return value[0] if isinstance(value, list) else value

    def _eval(self, node):
        kind = node[0]
        if kind in ("number", "string"):
            return node[1]
        if kind == "ref":
            values = self.range_values(node[1])
            return values if len(values) > 1 else values[0]
        if kind == "unary":
            value = self._number(self._scalar(node[2]))
            return -value if node[1] == "-" else value
        if kind == "op":
            return self._binary(node[1], node[2], node[3])
        if kind == "call":
            return self._call(node[1], node[2])
        raise FormulaError(f"unknown node {kind}")

    @staticmethod
    def _number(value):
        if value is None or value == "":
            return 0.0
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        return float(value)

    @staticmethod
    def _text(value):
        if value is None:
            return ""
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    def _binary(self, operator, left_node, right_node):
        left, right = self._scalar(left_node), self._scalar(right_node)
        if operator == "&":
            return self._text(left) + self._text(right)
        if operator in ("=", "<>", "<", "<=", ">", ">="):
            if isinstance(left, str) or isinstance(right, str):
                left, right = self._text(left), self._text(right)
            else:
                left, right = self._number(left), self._number(right)
            return {
                "=": left == right, "<>": left != right, "<": left < right,
                "<=": left <= right, ">": left > right, ">=": left >= right,
            }[operator]
        left, right = self._number(left), self._number(right)
        if operator == "+":
            return left + right
        if operator == "-":
            return left - right
        if operator == "*":
            return left * right
        if operator == "/":
            if right == 0:
                raise _ExcelError("#DIV/0!")
            return left / right
        if operator == "^":
            return left ** right
        raise FormulaError(f"unknown operator {operator!r}")

    def _call(self, name, args):
        if name == "IF":
            condition = self._scalar(args[0])
            truthy = bool(condition) if not isinstance(condition, str) else condition != ""
            if truthy:
                return self._eval(args[1])
            return self._eval(args[2]) if len(args) > 2 else False
        if name == "IFERROR":
            try:
                return self._eval(args[0])
            except _ExcelError:
                return self._eval(args[1])
        if name == "INDEX":
            values = self._eval(args[0])
            position = int(self._number(self._scalar(args[1])))
            values = values if isinstance(values, list) else [values]
            if not 1 <= position <= len(values):
                raise _ExcelError("#REF!")
            return values[position - 1]
        if name == "MATCH":
            needle = self._scalar(args[0])
            haystack = self._eval(args[1])
            haystack = haystack if isinstance(haystack, list) else [haystack]
            mode = int(self._number(self._scalar(args[2]))) if len(args) > 2 else 1
            if mode != 0:
                raise FormulaError("only exact MATCH (0) is supported")
            for offset, candidate in enumerate(haystack, start=1):
                if self._text(candidate) == self._text(needle):
                    return float(offset)
            raise _ExcelError("#N/A")
        if name == "LOOKUP":
            needle = self._number(self._scalar(args[0]))
            keys = self._eval(args[1])
            results = self._eval(args[2])
            keys = keys if isinstance(keys, list) else [keys]
            results = results if isinstance(results, list) else [results]
            found = None
            for key, result in zip(keys, results):
                if key is None or key == "":
                    continue
                if self._number(key) <= needle:
                    found = result
            if found is None:
                raise _ExcelError("#N/A")
            return found
        if name in ("MIN", "MAX", "SUM"):
            values = []
            for argument in args:
                value = self._eval(argument)
                values.extend(value if isinstance(value, list) else [value])
            numbers = [self._number(v) for v in values if v is not None and v != ""
                       and not isinstance(v, str)]
            if not numbers:
                return 0.0
            return {"MIN": min, "MAX": max, "SUM": sum}[name](numbers)
        if name == "ROUND":
            value = self._number(self._scalar(args[0]))
            digits = int(self._number(self._scalar(args[1])))
            factor = 10 ** digits
            shifted = value * factor
            epsilon = 1e-9 if shifted >= 0 else -1e-9
            return int(shifted + (0.5 if shifted >= 0 else -0.5) + epsilon) / factor
        if name == "TODAY":
            return date.today()
        raise FormulaError(f"unsupported function {name}()")
