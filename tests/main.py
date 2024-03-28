import logging
import os
import sys
from contextlib import contextmanager
from io import StringIO
from unittest import TestCase
from unittest import main as unittest_main
from unittest.mock import MagicMock, patch
from uuid import uuid4

from picterra import APIClient, client

from pycterra_cli import logger, parse_args


@contextmanager
def captured_output():
    new_out, new_err = StringIO(), StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    try:
        sys.stdout, sys.stderr = new_out, new_err
        yield sys.stdout, sys.stderr
    finally:
        sys.stdout, sys.stderr = old_out, old_err


def create_http_mock(json_resp: dict, code: int = 200):
    return MagicMock(return_value=MagicMock(
        ok=True,
        json=lambda: json_resp,
        text=f'status code != {code}',
        status_code=code
    ))


class AnyStringWith(str):
    def __eq__(self: str, other: str):
        return type(other) is str and self in other


class AnyDictWith(dict):
    def __eq__(self: dict, other: dict):
        ok = type(other) is dict
        for k, v in other.items():
            if type(v) is dict:
                for kk, vv in v.items():
                    if self[k][kk] != vv:
                        ok = False
            else:
                if self[k] != v:
                    print(2)
                    ok = False
        return ok


class TestApiKeyEnvVar(TestCase):
    # def setUp(self):
    #     self.old_key = os.environ.get("PICTERRA_API_KEY", None)
    #     del os.environ["PICTERRA_API_KEY"]

    # def tearDown(self):
    #     if self.old_key is not None:
    #         os.environ["PICTERRA_API_KEY"] = self.old_key

    def test_presence(self):
        os.environ["PICTERRA_API_KEY"] = "xxxx"
        mock_return_results_page = MagicMock(return_value=[])
        with patch.object(APIClient, '_return_results_page', mock_return_results_page):
            parse_args(['list-detectors'])
        mock_return_results_page.assert_called_once()

    def test_absence(self):
        os.environ.pop("PICTERRA_API_KEY", None)
        with self.assertRaises(SystemExit) as cm:
            parse_args(['create-detector'])
        self.assertRegex(cm.exception.code, r"PICTERRA_API_KEY")


class TestHelps(TestCase):
    def setUp(self):
        pass

    def test_root_help_message(self):
        with captured_output() as (out, err):
            parse_args([])
            out = out.getvalue().strip().replace('\n', '')
            self.assertRegex(out, r'^usage: pycterra.*create-detector.*get-raster')


class TestArguments(TestCase):
    def test_abbreviations(self):
        op_mock = MagicMock()
        sess_mock = create_http_mock({"operation_id": "spam"})
        with patch.object(client._RequestsSession, 'post', sess_mock), patch.object(APIClient, '_wait_until_operation_completes', op_mock):
            d, r = str(uuid4()), str(uuid4())
            parse_args(['run-detector', '-d', d, '-r', r])
            sess_mock.assert_called_once_with(AnyStringWith(d), json=AnyDictWith({'raster_id': r}))
            op_mock.assert_called_once_with({'operation_id': 'spam'})

    def test_normal(self):
        op_mock = MagicMock()
        sess_mock = create_http_mock({"operation_id": "spam"})
        with patch.object(client._RequestsSession, 'post', sess_mock), patch.object(APIClient, '_wait_until_operation_completes', op_mock):
            d, r = str(uuid4()), str(uuid4())
            parse_args(['run-detector', '--detector-id', d, '--raster-id', r])
            sess_mock.assert_called_once_with(
                AnyStringWith(d),
                json=AnyDictWith({'raster_id': str(r)})
            )
            op_mock.assert_called_once_with({'operation_id': 'spam'})

    def test_defaults(self):
        sess_mock = create_http_mock({"id": "foobar"}, 201)
        with patch.object(client._RequestsSession, 'post', sess_mock):
            parse_args(['create-detector', '--name', 'spam', '--tile-size', '1234'])
            sess_mock.assert_called_once_with(
                AnyStringWith('detectors'),
                json=AnyDictWith({
                    'name': 'spam',
                    'configuration': {
                        "detection_type": 'count',
                        "tile_size": 1234,
                        "background_sample_ratio": 0.25,
                        'output_type': 'polygon',
                        'training_steps': 500,
                        'backbone': 'resnet34',
                    }
                })
            )


class TestMethods(TestCase):
    def setUp(self):
        self.old_key = os.environ.get("PICTERRA_API_KEY", None)
        os.environ["PICTERRA_API_KEY"] = "xxxx"
        self.stream_handler = logging.StreamHandler(sys.stdout)
        logger.addHandler(self.stream_handler)

    def tearDown(self):
        if self.old_key is not None:
            os.environ["PICTERRA_API_KEY"] = self.old_key
        else:
            del os.environ["PICTERRA_API_KEY"]

    def test_isupper(self):
        self.assertTrue("FOO".isupper())
        self.assertFalse("Foo".isupper())

    def test_split(self):
        s = "hello world"
        self.assertEqual(s.split(), ["hello", "world"])
        # check that s.split fails when the separator is not a string
        with self.assertRaises(TypeError):
            s.split(2)

    def test_list_rasters(self):
        mock_return_results_page = MagicMock(return_value=[1, 2])
        with captured_output() as (out, err), patch.object(APIClient, '_return_results_page', mock_return_results_page):
            with self.assertNoLogs(logger, level='ERROR'):
                parse_args(['list-rasters'])
                self.assertEqual(out.getvalue().strip(), '[1, 2]')
                self.assertEqual(err.getvalue().strip(), '')
                mock_return_results_page.assert_called_once()


if __name__ == "__main__":
    unittest_main()
