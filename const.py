# Bonzai API constants

# API base URL
API_URL = 'https://www.bonzai.pro/api/v1'

# Supported currencies by Bonzai
SUPPORTED_CURRENCIES = ['EUR', 'USD']

# Default payment method codes
DEFAULT_PAYMENT_METHOD_CODES = ['bonzai']

# Webhook event types
WEBHOOK_EVENTS = {
    'product_access_granted': 'done',
    'product_access_revoked': 'cancel',
}

# Payment modes
PAYMENT_MODE_ONE_OFF = 'one_off'
PAYMENT_MODE_SUBSCRIPTION = 'subscription'
