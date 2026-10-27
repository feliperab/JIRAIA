import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STEERING = ROOT / ".kiro" / "steering"

REQUIRED = (
    "product.md",
    "tech.md",
    "structure.md",
    "jira-safety.md",
)

NEW_DOCUMENTS = (
    "tech.md",
    "structure.md",
    "jira-safety.md",
)


class SteeringContractTests(unittest.TestCase):

    def test_required_documents_exist(self):
        for name in REQUIRED:
            with self.subTest(file=name):
                path = STEERING / name
                self.assertTrue(path.is_file())
                self.assertGreater(path.stat().st_size, 0)

    def test_new_documents_always_included(self):
        for name in NEW_DOCUMENTS:
            with self.subTest(file=name):
                content = (STEERING / name).read_text(
                    encoding="utf-8-sig"
                )
                self.assertTrue(
                    content.startswith(
                        "---\ninclusion: always\n---\n"
                    ),
                    f"Front matter incorreto: {name}",
                )

    def test_jira_safety_contract(self):
        content = (
            STEERING / "jira-safety.md"
        ).read_text(encoding="utf-8-sig")

        for required in (
            "aprovacao humana",
            "JiraClient.post",
            "POST",
            "allow_write=True",
            "MCP",
        ):
            with self.subTest(text=required):
                self.assertIn(required, content)

    def test_mcp_tools_documented(self):
        content = (
            STEERING / "structure.md"
        ).read_text(encoding="utf-8-sig")

        for tool in (
            "jiraia_daily",
            "jiraia_sprint_planning",
            "jiraia_pi_planning",
        ):
            with self.subTest(tool=tool):
                self.assertIn(tool, content)


if __name__ == "__main__":
    unittest.main()