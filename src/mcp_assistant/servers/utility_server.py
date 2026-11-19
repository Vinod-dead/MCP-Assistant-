"""Utility MCP server -- the 'Other tools' slot: time and safe arithmetic."""
from __future__ import annotations

import ast
import math
import operator
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ._common import READ, make_server

mcp = make_server("utility", "Small helper tools: current time in any timezone, safe calculator.")

_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}
_FUNCS = {"sqrt": math.sqrt, "abs": abs, "round": round, "min": min, "max": max, "log": math.log, "log10": math.log10}
_CONSTS = {"pi": math.pi, "e": math.e}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 1000:
            raise ValueError("Exponent too large.")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Name) and node.id in _CONSTS:
        return _CONSTS[node.id]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
        return _FUNCS[node.func.id](*[_eval(a) for a in node.args])
    raise ValueError("Unsupported expression. Allowed: numbers, + - * / // % **, parentheses, sqrt/abs/round/min/max/log/log10, pi, e.")


@mcp.tool(annotations=READ)
def calculate(expression: str) -> str:
    """Evaluate an arithmetic expression exactly, e.g. '450000 * 0.18' or 'sqrt(2) * 10'."""
    if len(expression) > 200:
        raise ValueError("Expression too long.")
    result = _eval(ast.parse(expression, mode="eval"))
    return str(round(result, 10) if isinstance(result, float) else result)


@mcp.tool(annotations=READ)
def current_time(timezone: str = "Asia/Kolkata") -> str:
    """Current date and time in an IANA timezone (default Asia/Kolkata)."""
    try:
        now = datetime.now(ZoneInfo(timezone))
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone '{timezone}'. Use an IANA name like 'Asia/Kolkata' or 'UTC'.") from exc
    return now.strftime("%A, %d %B %Y, %H:%M:%S %Z (UTC%z)")


if __name__ == "__main__":
    mcp.run()
