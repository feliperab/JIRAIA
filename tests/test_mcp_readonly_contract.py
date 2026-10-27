import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MCP_FILE = ROOT / "scripts" / "mcp_jiraia.py"

EXPECTED_TOOLS = {
    "jiraia_daily",
    "jiraia_sprint_planning",
    "jiraia_pi_planning",
}


def called_name(node):
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


class McpReadonlyContractTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(
            MCP_FILE.read_text(encoding="utf-8-sig"),
            filename=str(MCP_FILE),
        )

    def test_only_three_approved_tools(self):
        names = set()

        for node in ast.walk(self.tree):
            if not isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                continue

            if any(
                called_name(decorator) == "tool"
                for decorator in node.decorator_list
            ):
                names.add(node.name)

        self.assertEqual(names, EXPECTED_TOOLS)

    def test_no_dynamic_tool_registration(self):
        forbidden = {
            "add_tool",
            "register_tool",
            "remove_tool",
        }

        violations = [
            node.lineno
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Call)
            and called_name(node) in forbidden
        ]

        self.assertEqual(
            violations, [],
            "Registro dinamico de MCP detectado",
        )

    def test_no_direct_write_or_dispatch_calls(self):
        forbidden = {
            "post",
            "put",
            "patch",
            "delete",
            "request",
            "urlopen",
            "Request",
            "execute_create_sprint_once",
            "reserve_attempt",
            "persist_once",
            "run_offline_once",
        }

        violations = [
            (node.lineno, called_name(node))
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Call)
            and called_name(node) in forbidden
        ]

        self.assertEqual(
            violations, [],
            "Possivel escrita direta no servidor MCP",
        )

    def test_no_write_engine_imports(self):
        forbidden_modules = {
            "jiraia.action_engine",
            "jiraia.attempt_ledger",
            "jiraia.execution_guard",
            "jiraia.executor",
            "jiraia.execution_pipeline",
            "jiraia.execution_cli",
            "jiraia.outcome_simulator",
            "jiraia.real_execution",
        }

        imported = []

        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported.extend(
                    alias.name for alias in node.names
                )

            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imported.append(module)

                imported.extend(
                    f"{module}.{alias.name}"
                    for alias in node.names
                )

        violations = [
            name
            for name in imported
            if any(
                name == blocked
                or name.startswith(blocked + ".")
                for blocked in forbidden_modules
            )
        ]

        self.assertEqual(
            violations, [],
            "Servidor MCP importou modulo de escrita",
        )

    def test_no_dynamic_code_or_process_calls(self):
        forbidden_calls = {
            "exec",
            "eval",
            "__import__",
            "Popen",
            "popen",
            "system",
            "check_call",
            "check_output",
        }

        forbidden_imports = {
            "subprocess",
        }

        violations = []

        for node in ast.walk(self.tree):
            if (
                isinstance(node, ast.Call)
                and called_name(node) in forbidden_calls
            ):
                violations.append(
                    f"chamada:{node.lineno}"
                )

            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in forbidden_imports:
                        violations.append(
                            f"import:{node.lineno}"
                        )

            if isinstance(node, ast.ImportFrom):
                if node.module in forbidden_imports:
                    violations.append(
                        f"import:{node.lineno}"
                    )

        self.assertEqual(
            violations, [],
            "Execucao dinamica ou subprocesso detectado",
        )


if __name__ == "__main__":
    unittest.main()