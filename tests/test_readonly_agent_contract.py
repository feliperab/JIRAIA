import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / ".kiro" / "agents" / "jiraia-readonly.json"

EXPECTED_TOOLS = {
    "@jiraia_local/jiraia_daily",
    "@jiraia_local/jiraia_sprint_planning",
    "@jiraia_local/jiraia_pi_planning",
}


class ReadonlyAgentContractTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(
            AGENT.read_text(encoding="utf-8-sig")
        )

    def test_exact_tool_allowlist(self):
        self.assertEqual(
            set(self.config["tools"]),
            EXPECTED_TOOLS,
        )
        self.assertEqual(
            len(self.config["tools"]),
            len(EXPECTED_TOOLS),
        )

    def test_no_broad_tool_selectors(self):
        forbidden = {
            "*",
            "@builtin",
            "@mcp",
            "shell",
            "write",
            "read",
            "web",
            "subagent",
            "@atlassian",
        }

        self.assertTrue(
            forbidden.isdisjoint(self.config["tools"])
        )

        self.assertTrue(
            self.config["includeMcpJson"]
        )
        self.assertFalse(
            self.config["includePowers"]
        )

    def test_explicit_denials(self):
        rules = self.config["permissions"]["rules"]

        denied = {
            rule["capability"]
            for rule in rules
            if rule.get("effect") == "deny"
            and not rule.get("match")
        }

        self.assertTrue(
            {"shell", "fs_write", "subagent"}
            .issubset(denied)
        )

        self.assertTrue(
            any(
                rule.get("capability") == "mcp"
                and rule.get("effect") == "deny"
                and "atlassian/*" in rule.get("match", [])
                for rule in rules
            )
        )

    def test_no_embedded_mcp_credentials(self):
        self.assertNotIn(
            "mcpServers",
            self.config,
        )
        self.assertNotIn(
            "allowedTools",
            self.config,
        )
        self.assertNotIn(
            "toolsSettings",
            self.config,
        )

        self.assertEqual(
            self.config["name"],
            "jiraia-readonly",
        )


if __name__ == "__main__":
    unittest.main()