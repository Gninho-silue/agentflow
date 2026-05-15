"""Matplotlib chart generation helpers for AgentFlow."""

import re
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
import os


_ALLOWED_IMPORT_ROOTS: frozenset[str] = frozenset({"pandas", "matplotlib"})

_UPLOAD_DIR = "uploads"


def generate_chart_from_code(code: str, file_data: dict[str, object] | None, task_id: str) -> str | None:
    """Execute matplotlib code and save a PNG chart when chart code is present."""

    if "matplotlib" not in code and "plt." not in code:
        return None

    if _has_dangerous_imports(code):
        print("Chart generation blocked: code contains disallowed import statements.")
        return None

    os.makedirs(_UPLOAD_DIR, exist_ok=True)
    chart_path = f"{_UPLOAD_DIR}/chart_{task_id}.png"

    # Validate chart_path stays inside the uploads directory
    if not chart_path.startswith(f"{_UPLOAD_DIR}/"):
        print(f"Chart generation blocked: path '{chart_path}' is outside uploads/.")
        return None

    cleaned_code = _sanitize_code(code, chart_path)

    try:
        if file_data and file_data.get("rows") and file_data.get("columns"):
            dataframe = pd.DataFrame(file_data["rows"], columns=file_data["columns"])
        else:
            dataframe = pd.DataFrame()

        exec_globals: dict[str, object] = {
            "pd": pd,
            "pandas": pd,
            "plt": plt,
            "df": dataframe,
            "file_data": file_data or {},
            "__builtins__": {
                "__import__": _safe_import,
                "abs": abs,
                "print": print,
                "range": range,
                "len": len,
                "list": list,
                "dict": dict,
                "str": str,
                "int": int,
                "float": float,
                "zip": zip,
                "enumerate": enumerate,
                "sum": sum,
                "min": min,
                "max": max,
                "sorted": sorted,
                "round": round,
            },
        }
        try:
            exec(cleaned_code, exec_globals)
        except SyntaxError as e:
            print(f"Syntax error in generated code: {e}")
            return None
        except Exception as e:
            print(f"Runtime error in chart generation: {e}")
            return None

        if os.path.exists(chart_path):
            return chart_path
        return None
    except Exception as exc:
        print(f"Chart generation error: {exc}")
        return None


def _has_dangerous_imports(code: str) -> bool:
    """Return True when the code imports any module outside the allowed set."""

    for match in re.finditer(r"^\s*(?:import|from)\s+([A-Za-z_]\w*)", code, re.MULTILINE):
        root = match.group(1).split(".")[0]
        if root not in _ALLOWED_IMPORT_ROOTS:
            return True
    return False


def _sanitize_code(code: str, chart_path: str) -> str:
    """Remove markdown fences, strip whitespace, and inject savefig/close."""

    cleaned = re.sub(r"^```(?:python)?\s*\n?", "", code.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned.strip(), flags=re.MULTILINE)
    cleaned = cleaned.strip()

    cleaned = cleaned.replace(
        "plt.show()",
        f'plt.savefig("{chart_path}", dpi=100, bbox_inches="tight")',
    )
    if "plt.savefig" not in cleaned:
        cleaned += f'\nplt.savefig("{chart_path}", dpi=100, bbox_inches="tight")'
    cleaned += "\nplt.close()"

    return cleaned


def _safe_import(
    name: str,
    globals_dict: dict[str, object] | None = None,
    locals_dict: dict[str, object] | None = None,
    fromlist: tuple[str, ...] = (),
    level: int = 0,
) -> object:
    """Allow only pandas and matplotlib imports inside generated chart code."""

    if name == "pandas":
        return pd
    if name == "matplotlib":
        return matplotlib
    if name == "matplotlib.pyplot":
        return plt
    raise ImportError(f"Import of '{name}' is not allowed in chart generation.")
