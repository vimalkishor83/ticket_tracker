import os
import requests

CREDVAULT_URL = os.environ.get('CREDVAULT_URL', 'http://172.20.0.1:5200')
CREDVAULT_API_TOKEN = os.environ.get('CREDVAULT_API_TOKEN', '')


def get_credential(name, default=''):
    if not CREDVAULT_API_TOKEN:
        return default
    try:
        resp = requests.get(
            f'{CREDVAULT_URL}/api/credential/{name}',
            headers={'Authorization': f'Bearer {CREDVAULT_API_TOKEN}'},
            timeout=5,
        )
        if resp.status_code == 200:
            return resp.json()['value']
    except requests.RequestException:
        pass
    return default
