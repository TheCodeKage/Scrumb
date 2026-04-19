import requests
from django.conf import settings

import jwt
import time

_APP_ID = settings.GITHUB_APP_ID
_APP_RSA_PATH = settings.GITHUB_APP_PRIVATE_KEY_PATH

with open(_APP_RSA_PATH, 'r') as f:
    _APP_RSA = f.read()


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

    print("JWT:", get_token())
    print("Status:", response.status_code)
    print("Response:", response.text)

    response.raise_for_status()

    return response.json()["token"]


if __name__ == '__main__':
    print(get_token())
