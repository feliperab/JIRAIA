import io
import json
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from jiraia.client import JiraClient


ENDPOINT = "/rest/agile/1.0/sprint"

PAYLOAD = {
    "name": "SCRUM Sprint 2",
    "originBoardId": 1,
}


def fake_client():
    jira = object.__new__(JiraClient)
    jira.url = "https://example.invalid"
    jira.auth = "CREDENCIAL_SIMULADA"
    return jira


class JiraPostTests(unittest.TestCase):

    @patch("urllib.request.urlopen")
    def test_default_blocks_write(self, urlopen):
        jira = fake_client()

        with self.assertRaises(PermissionError):
            jira.post(ENDPOINT, PAYLOAD)

        urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_other_endpoint_blocked(self, urlopen):
        jira = fake_client()

        with self.assertRaises(ValueError):
            jira.post(
                "/rest/api/3/issue",
                PAYLOAD,
                allow_write=True,
            )

        urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_invalid_payload_blocked(self, urlopen):
        jira = fake_client()

        with self.assertRaises(ValueError):
            jira.post(
                ENDPOINT,
                {"name": "Sprint sem board"},
                allow_write=True,
            )

        urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    @patch("jiraia.client._require_write_transport_activation", lambda: None)
    def test_simulated_post(self, urlopen):
        response = MagicMock()
        response.status = 201
        response.read.return_value = json.dumps({
            "id": 123,
            "name": "SCRUM Sprint 2",
            "state": "future",
            "originBoardId": 1,
        }).encode("utf-8")

        urlopen.return_value.__enter__.return_value = response

        jira = fake_client()

        result = jira.post(
            ENDPOINT,
            PAYLOAD,
            allow_write=True,
        )

        self.assertEqual(result["id"], 123)

        urlopen.assert_called_once()
        request = urlopen.call_args.args[0]

        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(
            request.full_url,
            "https://example.invalid" + ENDPOINT,
        )
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            PAYLOAD,
        )
        self.assertEqual(
            request.get_header("Content-type"),
            "application/json",
        )

    @patch("urllib.request.urlopen")
    @patch("jiraia.client._require_write_transport_activation", lambda: None)
    def test_http_error_hides_body(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError(
            "https://example.invalid",
            403,
            "Forbidden",
            {},
            io.BytesIO(b"SEGREDO_NAO_EXIBIR"),
        )

        jira = fake_client()

        with self.assertRaises(RuntimeError) as context:
            jira.post(
                ENDPOINT,
                PAYLOAD,
                allow_write=True,
            )

        self.assertIn("HTTP 403", str(context.exception))
        self.assertNotIn(
            "SEGREDO_NAO_EXIBIR",
            str(context.exception),
        )


if __name__ == "__main__":
    unittest.main()
