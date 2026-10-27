import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jiraia.client import JiraClient
from jiraia.execution_guard import execution_phrase
from jiraia.real_execution import execute_create_sprint_once
from test_executor import create_fixture


class DerivedJiraClient(JiraClient):
    pass


class ProductionGateTests(unittest.TestCase):

    def check_blocked(self, client_class):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)

            # Instancia sem inicializador:
            # nenhuma credencial e carregada.
            client = object.__new__(client_class)

            confirmation = execution_phrase(
                path.stem,
                "SCRUM Sprint 2",
            )

            with (
                patch.object(
                    JiraClient,
                    "get",
                    side_effect=AssertionError(
                        "GET inesperado"
                    ),
                ) as get,
                patch.object(
                    JiraClient,
                    "post",
                    side_effect=AssertionError(
                        "POST inesperado"
                    ),
                ) as post,
                patch(
                    "urllib.request.urlopen",
                    side_effect=AssertionError(
                        "Acesso HTTP inesperado"
                    ),
                ) as urlopen,
            ):
                with self.assertRaisesRegex(
                    PermissionError,
                    "Cliente Jira real bloqueado",
                ):
                    execute_create_sprint_once(
                        path,
                        client,
                        confirmation,
                        enable_real_write=True,
                        store=tmp,
                    )

                get.assert_not_called()
                post.assert_not_called()
                urlopen.assert_not_called()

            self.assertFalse(
                (Path(tmp) / "attempts").exists()
            )
            self.assertFalse(
                (Path(tmp) / "real_dispatch").exists()
            )
            self.assertFalse(
                (Path(tmp) / "real_outcomes").exists()
            )

    def test_real_client_blocked(self):
        self.check_blocked(JiraClient)

    def test_real_client_subclass_blocked(self):
        self.check_blocked(DerivedJiraClient)


if __name__ == "__main__":
    unittest.main()