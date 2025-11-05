import requests
import streamlit as st

def get_amazon_access_token():
    """
    Exchanges your LWA refresh token for a short-lived SP-API access token.
    Uses secrets:
      - LWA_CLIENT_ID
      - LWA_CLIENT_SECRET
      - REFRESH_TOKEN
    """
    data = {
        "grant_type": "refresh_token",
        "refresh_token": st.secrets["REFRESH_TOKEN"],
        "client_id": st.secrets["LWA_CLIENT_ID"],
        "client_secret": st.secrets["LWA_CLIENT_SECRET"],
    }
    r = requests.post("https://api.amazon.com/auth/o2/token", data=data)
    r.raise_for_status()
    return r.json()["access_token"]
