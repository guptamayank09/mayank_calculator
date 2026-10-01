import ast
import json
import math
import operator
import re
import time
import urllib.request

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def evaluate(node, deg):
    """Walk the parsed expression and only allow numbers, + - * /, e and sin()."""
    if isinstance(node, ast.Expression):
        return evaluate(node.body, deg)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.Name) and node.id == "e":
        return math.e
    if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY_OPS:
        return UNARY_OPS[type(node.op)](evaluate(node.operand, deg))
    if isinstance(node, ast.BinOp) and type(node.op) in BIN_OPS:
        return BIN_OPS[type(node.op)](evaluate(node.left, deg), evaluate(node.right, deg))
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "sin"
        and len(node.args) == 1
    ):
        x = evaluate(node.args[0], deg)
        return math.sin(math.radians(x) if deg else x)
    raise ValueError("Unsupported expression")


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/calculate", methods=["POST"])
def calculate():
    data = request.get_json(silent=True) or {}
    expr = str(data.get("expr", "")).strip()
    deg = bool(data.get("deg", False))

    # Display symbols -> Python operators
    expr = expr.replace("×", "*").replace("÷", "/").replace("−", "-")
    # 50% -> (50/100)
    expr = re.sub(r"(\d+(?:\.\d+)?)%", r"(\1/100)", expr)
    # Auto-close open brackets so live results work while typing "sin(30"
    expr += ")" * max(0, expr.count("(") - expr.count(")"))

    try:
        value = evaluate(ast.parse(expr, mode="eval"), deg)
    except ZeroDivisionError:
        return jsonify({"error": "Cannot divide by zero"})
    except (SyntaxError, ValueError):
        return jsonify({"error": "Invalid expression"})

    value = round(value, 10)
    if value == int(value) and abs(value) < 1e15:
        value = int(value)
    return jsonify({"result": value})


# ---------- Converter tabs ----------
UNITS = {
    "Length": {"m": 1, "km": 1000, "cm": 0.01, "mm": 0.001, "mi": 1609.344, "ft": 0.3048, "in": 0.0254},
    "Weight": {"kg": 1, "g": 0.001, "lb": 0.45359237, "oz": 0.028349523125},
    "Temperature": {"°C": None, "°F": None, "K": None},
}
TO_C = {"°C": lambda v: v, "°F": lambda v: (v - 32) * 5 / 9, "K": lambda v: v - 273.15}
FROM_C = {"°C": lambda c: c, "°F": lambda c: c * 9 / 5 + 32, "K": lambda c: c + 273.15}

POPULAR = ["USD", "INR", "EUR", "GBP", "JPY", "AUD", "CAD", "CNY", "AED", "SGD", "CHF"]
# Used only when the live rates can't be downloaded (approximate)
FALLBACK_RATES = {"USD": 1, "INR": 83.5, "EUR": 0.92, "GBP": 0.79, "JPY": 150, "AUD": 1.52,
                  "CAD": 1.36, "CNY": 7.2, "AED": 3.67, "SGD": 1.34, "CHF": 0.88}
_cache = {"time": 0, "rates": FALLBACK_RATES, "live": False}


def get_rates():
    """Live rates (cached for an hour); falls back to approximate rates offline."""
    if time.time() - _cache["time"] < 3600:
        return _cache
    try:
        with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=4) as r:
            data = json.load(r)
        if data.get("result") == "success":
            _cache.update(rates=data["rates"], live=True)
    except Exception:
        pass
    # if offline, try again in 5 minutes
    _cache["time"] = time.time() - (0 if _cache["live"] else 3300)
    return _cache


@app.route("/units")
def units():
    return jsonify({name: list(table) for name, table in UNITS.items()})


@app.route("/rates")
def rates():
    info = get_rates()
    return jsonify({"codes": [c for c in POPULAR if c in info["rates"]], "live": info["live"]})


@app.route("/convert", methods=["POST"])
def convert():
    d = request.get_json(silent=True) or {}
    try:
        value = float(str(d.get("value", "")).replace(",", ""))
    except ValueError:
        return jsonify({"error": "Enter a number"})
    src, dst = d.get("from"), d.get("to")
    try:
        if d.get("kind") == "currency":
            r = get_rates()["rates"]
            result = value / r[src] * r[dst]
        elif d.get("category") == "Temperature":
            result = FROM_C[dst](TO_C[src](value))
        else:
            table = UNITS[d.get("category")]
            result = value * table[src] / table[dst]
    except KeyError:
        return jsonify({"error": "Unsupported conversion"})
    return jsonify({"result": round(result, 6)})


if __name__ == "__main__":
    app.run(debug=True)