import os
import unittest
from unittest.mock import patch

from jiraia.client import JiraClient


ENDPOINT = "/rest/agile/1.0/sprint"
PAYLOAD = {
    "name": "SCRUM Sprint 2",
    "originBoardId": 1,
}


def fake_client(client_class=JiraClient):
    client = object.__new__(client_class)
    client.url = "https://example.invalid"
    client.auth = "AUTENTICACAO_FICTICIA"
    return client


class DerivedClient(JiraClient):
    pass


class HttpWriteGateTests(unittest.TestCase):

    @patch("urllib.request.urlopen")
    @patch("urllib.request.Request")
    def test_allow_write_true_does_not_unlock(
        self, request, urlopen
    ):
        jira = fake_client()

        with self.assertRaisesRegex(
            PermissionError,
            "Transporte HTTP de escrita desabilitado",
        ):
            jira.post(
                ENDPOINT,
                PAYLOAD,
                allow_write=True,
            )

        request.assert_not_called()
        urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_environment_cannot_unlock(self, urlopen):
        jira = fake_client()

        with patch.dict(
            os.environ,
            {
                "JIRAIA_ALLOW_WRITE": "true",
                "JIRAIA_ENABLE_POST": "1",
            },
        ):
            with self.assertRaises(PermissionError):
                jira.post(
                    ENDPOINT,
                    PAYLOAD,
                    allow_write=True,
                )

        urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_subclass_cannot_unlock(self, urlopen):
        jira = fake_client(DerivedClient)

        with self.assertRaises(PermissionError):
            jira.post(
                ENDPOINT,
                PAYLOAD,
                allow_write=True,
            )

        urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()