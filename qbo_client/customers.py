from qbo_client.client import query
from qbo_client.auth import get_access_token
import os

def get_customers_by_ids(customer_ids: list[str]) -> list[dict]:
    realm_id = os.getenv("QBO_REALM_ID")
    access_token = get_access_token()

    formatted_list = ", ".join([f"'{item}'" for item in customer_ids])

    query_string = f"SELECT * FROM Customer WHERE Id IN ({formatted_list})"

    response = query(realm_id, access_token, query_string)

    raw_customers = response['QueryResponse'].get('Customer', [])

    clean_customers = []

    for customer in raw_customers:
        clean_customer = {
            'Id': customer['Id'],
            'PrimaryEmailAddr': customer.get('PrimaryEmailAddr', {}).get('Address', None),
            'DisplayName': customer.get('DisplayName')
        }
        clean_customers.append(clean_customer)

    return clean_customers