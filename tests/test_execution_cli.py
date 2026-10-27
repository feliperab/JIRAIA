import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from jiraia.client import JiraClient
from jiraia.execution_cli import main
from test_executor import FakeJira, create_fixture


def invoke(args, folder, factory=None):
    output = StringIO()

    with redirect_stdout(output):
        status = main(
            args,
            store=folder,
            jira_factory=factory,
        )

    return status, output.getvalue()


class ExecutionCliTests(unittest.TestCase):

    @patch("urllib.request.urlopen")
    @patch.object(JiraClient, "post")
    def test_preview_without_network(self, post, urlopen):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)

            status, output = invoke(
                [str(path)], tmp,
                factory=lambda: 1 / 0,
            )

            self.assertEqual(status, 0)
            self.assertIn("PREVIEW_ONLY", output)
            self.assertIn('"executed": false', output)
            self.assertIn("Nenhum acesso a rede", output)

            post.assert_not_called()
            urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    @patch.object(JiraClient, "post")
    def test_execute_is_always_blocked(self, post, urlopen):
        with tempfile.TemporaryDirectory() as tmp:
            status, output = invoke(
                ["--execute"], tmp,
                factory=lambda: 1 / 0,
            )

            self.assertEqual(status, 2)
            self.assertIn("[BLOQUEADO]", output)
            self.assertFalse(
                (Path(tmp) / "attempts").exists()
            )

            post.assert_not_called()
            urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    @patch.object(JiraClient, "post")
    def test_check_jira_uses_fake_get(self, post, urlopen):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)

            status, output = invoke(
                [str(path), "--check-jira"],
                tmp,
                factory=FakeJira,
            )

            self.assertEqual(status, 0)
            self.assertIn("Preflight GET concluido", output)
            self.assertIn('"ready_to_execute": false', output)

            post.assert_not_called()
            urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_expired_preflight_blocked(self, urlopen):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp, expired=True)

            status, output = invoke(
                [str(path), "--check-jira"],
                tmp,
                factory=FakeJira,
            )

            self.assertEqual(status, 2)
            self.assertIn("EXPIRADA", output)
            self.assertIn("[BLOQUEADO]", output)

            urlopen.assert_not_called()

    def test_modified_proposal_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)

            envelope = json.loads(
                path.read_text(encoding="utf-8")
            )
            envelope["proposal"]["parameters"]["name"] = (
                "Sprint adulterada"
            )

            path.write_text(
                json.dumps(envelope), encoding="utf-8"
            )

            status, output = invoke([str(path)], tmp)

            self.assertEqual(status, 2)
            self.assertIn("[BLOQUEADO]", output)

    def test_proposal_outside_store_blocked(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            tempfile.TemporaryDirectory() as other,
        ):
            path = create_fixture(other)

            status, output = invoke([str(path)], tmp)

            self.assertEqual(status, 2)
            self.assertIn("fora do diretorio", output)


if __name__ == "__main__":
    unittest.main()