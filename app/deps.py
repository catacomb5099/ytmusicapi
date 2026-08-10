from app.ytmusic_client import YTMusicClient, get_client


def get_ytmusic() -> YTMusicClient:
    return get_client()
