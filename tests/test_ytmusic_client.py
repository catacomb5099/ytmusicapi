from unittest.mock import MagicMock

import pytest

from app.errors import NotFoundError
from app.ytmusic_client import YTMusicClient


def _client_with_mocked_instance(instance: MagicMock) -> YTMusicClient:
    client = YTMusicClient.__new__(YTMusicClient)
    client._ytmusic = instance
    import threading

    client._semaphore = threading.Semaphore(8)
    return client


class TestBrowsePageNotFoundTranslation:
    @pytest.mark.parametrize("method_name", ["get_album", "get_artist", "get_playlist"])
    def test_empty_browse_page_keyerror_becomes_not_found(self, method_name):
        instance = MagicMock()
        getattr(instance, method_name).side_effect = KeyError(
            "Unable to find 'contents' using path [...] on {...}"
        )
        client = _client_with_mocked_instance(instance)

        with pytest.raises(NotFoundError):
            client.call(method_name, "some-id")

    def test_unrelated_keyerror_on_browse_method_still_propagates(self):
        instance = MagicMock()
        instance.get_album.side_effect = KeyError("albums")
        client = _client_with_mocked_instance(instance)

        with pytest.raises(KeyError):
            client.call("get_album", "some-id")

    def test_keyerror_on_non_browse_method_propagates_unchanged(self):
        instance = MagicMock()
        instance.get_song.side_effect = KeyError("Unable to find 'contents' using path [...]")
        client = _client_with_mocked_instance(instance)

        with pytest.raises(KeyError):
            client.call("get_song", "some-id")
