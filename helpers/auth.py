import requests

def get_amazon_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    """
    Exchanges LWA refresh_token for a short-lived access_token.
    """
    res = requests.post(
        "https://api.amazon.com/auth/o2/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret
        }
    )
    res.raise_for_status()
    return res.json()["access_token"]

