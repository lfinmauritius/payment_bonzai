# Payment Provider: Bonzai

> ⚠️ **BETA** - This module is currently in beta testing. Use in production at your own risk.

Odoo payment provider integration for [Bonzai](https://www.bonzai.pro).

![Odoo Version](https://img.shields.io/badge/Odoo-19.0-blue)
![License](https://img.shields.io/badge/License-LGPL--3-green)
![Status](https://img.shields.io/badge/Status-Beta-orange)

## Overview

This module integrates Bonzai as a payment provider in Odoo, allowing customers to pay for their orders through Bonzai's secure checkout.

### Features

- Redirect customers to Bonzai secure checkout
- Automatic order confirmation upon successful payment
- Invoice creation and payment reconciliation
- Webhook support for real-time payment notifications
- Automatic reconciliation cron for pending transactions
- HTTPS enforced for all URLs

### Security

This module has been security-audited and includes:

- Cryptographic webhook secret generation (`secrets.token_urlsafe`)
- Constant-time comparison to prevent timing attacks
- Amount and currency verification on payment confirmation
- Transaction state validation
- Input sanitization and URL encoding
- No sensitive data in logs

## Requirements

- Odoo 19.0
- A Bonzai account with API access ([bonzai.pro](https://www.bonzai.pro))
- HTTPS enabled on your Odoo instance (required for webhooks)

## Installation

1. Clone this repository into your Odoo addons directory:

```bash
git clone https://github.com/YOUR_USERNAME/payment_bonzai.git /path/to/odoo/addons/payment_bonzai
```

2. Update the addons list in Odoo:
   - Go to **Apps** → **Update Apps List**

3. Install the module:
   - Search for "Bonzai" in Apps
   - Click **Install**

## Configuration

### 1. Get your Bonzai credentials

1. Log in to your Bonzai account at [bonzai.pro](https://www.bonzai.pro)
2. Go to your **Profile** to get your **API Token**
3. Create or select a **Product** and copy its **UUID** from the URL

### 2. Configure the provider in Odoo

1. Go to **Invoicing** → **Configuration** → **Payment Providers**
2. Select **Bonzai**
3. Enter your credentials:
   - **API Token**: Your Bonzai API token
   - **Product UUID**: The UUID of your Bonzai product
4. Set the provider state to **Enabled** or **Test Mode**

### 3. Configure the webhook in Bonzai

1. In Odoo, copy the **Webhook URL** displayed in the provider configuration
2. Go to [bonzai.pro/business](https://www.bonzai.pro/business)
3. Paste the webhook URL in the webhook configuration section

### 4. Disable Bonzai customer emails (Recommended)

By default, Bonzai sends a "You've unlocked..." email to customers after payment. To disable this:

1. Go to your **Product settings** in Bonzai
2. **Enable redirect URL** option (even though it won't actually redirect since we use dynamic checkout)
3. This disables the automatic customer email

> **Note**: This is recommended when using Bonzai as a payment gateway for Odoo, since Odoo handles all customer communications.

## How it works

```
┌──────────┐      ┌──────────┐      ┌──────────┐
│  Client  │──1──▶│   Odoo   │──2──▶│  Bonzai  │
│          │      │          │      │          │
│          │◀─────│          │◀──3──│          │
│          │──4──▶│          │      │          │
│          │      │          │◀──5──│          │
│          │◀──6──│          │      │          │
└──────────┘      └──────────┘      └──────────┘

1. Client clicks "Pay"
2. Odoo creates checkout session via Bonzai API
3. Bonzai returns checkout URL
4. Client redirected to Bonzai, completes payment
5. Bonzai sends webhook notification
6. Odoo confirms order, creates invoice & payment
```

## Supported currencies

- EUR (Euro)
- USD (US Dollar)

## Important notes

### About Bonzai

Bonzai is a **digital product sales platform** that can be used as a payment gateway. When using this module:

- A Bonzai product is required for checkout (can be an empty/placeholder product)
- Customer emails can be disabled (see configuration step 4)

### Limitations

- **Refunds**: Not supported via API (must be done manually in Bonzai)
- **Tokenization**: Not supported
- **Manual capture**: Not supported

## Webhook events

| Event | Action in Odoo |
|-------|----------------|
| `product_access_granted` | Mark transaction as done, confirm order, create invoice |
| `product_access_revoked` | Mark transaction as cancelled |

## Troubleshooting

### Payment confirmed but order not updated

The reconciliation cron runs every 15 minutes. You can also:
1. Go to the transaction in Odoo
2. Check the Bonzai Order ID
3. Verify the webhook was received in the logs

### Webhook not received

1. Verify the webhook URL is correctly configured in Bonzai
2. Ensure your Odoo instance is accessible via HTTPS
3. Check Odoo logs for incoming webhook requests

### Amount mismatch error

The module verifies that the paid amount matches the expected amount. If there's a mismatch, the transaction is marked as error. Check:
1. Currency configuration
2. Rounding settings
3. Bonzai product price vs Odoo cart total

## Development

### Running tests

```bash
odoo-bin -d test_db -i payment_bonzai --test-enable --stop-after-init
```

### Module structure

```
payment_bonzai/
├── controllers/
│   └── main.py              # Webhook & return URL handlers
├── models/
│   ├── payment_provider.py  # Provider configuration & API calls
│   └── payment_transaction.py # Transaction processing
├── views/
│   ├── payment_provider_views.xml
│   └── payment_bonzai_templates.xml
├── data/
│   ├── payment_provider_data.xml
│   └── payment_method_data.xml
├── static/
│   ├── description/
│   │   └── icon.png         # Module icon (Bonzai logo)
│   └── src/
│       └── img/
│           └── credit_debit_card.png  # Payment method icon
├── security/
│   └── ir.model.access.csv
├── __manifest__.py
├── __init__.py
└── const.py                 # API constants
```

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

This module is licensed under LGPL-3. See [LICENSE](LICENSE) for details.

## Author

**Loic FONTAINE**

## Links

- [Bonzai Website](https://www.bonzai.pro)
- [Bonzai API Documentation](https://bonzai.gitbook.io/bonzai/)
- [Odoo Payment Providers Documentation](https://www.odoo.com/documentation/19.0/developer/howtos/payment_provider.html)
