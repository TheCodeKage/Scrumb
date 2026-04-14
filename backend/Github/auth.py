import time
import jwt          # pip install PyJWT
import requests
from django.conf import settings


def _get_private_key() -> str:
    """
    Loads the GitHub App private key from either a .pem file path
    or an env variable where newlines are stored as literal \n.
    """
    pem_path = getattr(settings, 'GITHUB_APP_PRIVATE_KEY_PATH', None)
    if pem_path:
        with open(pem_path, 'r') as f:
            return f.read()

    # Env variable — stored with literal \n, restore real newlines
    raw = getattr(settings, 'GITHUB_APP_PRIVATE_KEY', '')
    return raw.replace('\\n', '\n')


def get_installation_access_token(installation_id: int) -> str | None:
    """
    Exchanges a GitHub App JWT for a short-lived installation access token.
    This token is what lets you call GitHub API on behalf of an installation.

    Returns the token string, or None on failure.
    """
    app_id = settings.GITHUB_APP_ID
    private_key = _get_private_key()

    if not app_id or not private_key:
        return None

    # 1. Build the App JWT — valid for 60 seconds, enough for one API call
    now = int(time.time())
    payload = {
        'iat': now - 60,   # issued at (60s skew tolerance)
        'exp': now + 600,  # expires in 10 minutes
        'iss': str(app_id),
    }

    try:
        app_jwt = jwt.encode(payload, private_key, algorithm='RS256')
    except Exception:
        return None

    # 2. Exchange App JWT for installation access token
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    headers = {
        'Authorization': f'Bearer {app_jwt}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }

    try:
        resp = requests.post(url, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json().get('token')
    except requests.RequestException:
        return None