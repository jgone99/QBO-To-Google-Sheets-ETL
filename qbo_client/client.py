import requests

class QBOAPIError(Exception):
    pass

def query(realm_id: str, access_token: str, query_string: str):
    response = requests.get(f"https://sandbox-quickbooks.api.intuit.com/v3/company/{realm_id}/query",
        params={'query': query_string},
        headers={
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json'
    })

    response.raise_for_status()

    data = response.json()

    if 'Fault' in data:
        raise QBOAPIError(data['Fault']['Error'][0]['Message'])

    return data