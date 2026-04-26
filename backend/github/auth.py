import requests
from django.conf import settings

import jwt
import time
from pathlib import Path
from django.conf import settings

def get_private_key():
    path = Path(settings.BASE_DIR) / "scrumbapp.2026-04-14.private-key.pem"

    with open(path, "r") as f:
        return f.read()

_APP_ID = settings.GITHUB_APP_ID
_APP_RSA = get_private_key()


def get_token():
    now = int(time.time())
    payload = {
        'iat': now - 60,
        'exp': now + (10 * 60) - 60,
        'iss': _APP_ID
    }
    return jwt.encode(payload, _APP_RSA, algorithm='RS256')


def get_installation_token(installation_id):
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"

    headers = {
        "Authorization": f"Bearer {get_token()}",
        "Accept": "application/vnd.github+json"
    }

    response = requests.post(url, headers=headers)

    response.raise_for_status()

    return response.json()["token"]


if __name__ == '__main__':
    print(get_token())
