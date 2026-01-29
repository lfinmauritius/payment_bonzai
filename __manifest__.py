{
    'name': 'Payment Provider: Bonzai',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Payment Providers',
    'summary': 'Accept payments via Bonzai payment platform',
    'description': """
Payment Provider: Bonzai
========================

This module integrates Bonzai (bonzai.pro) as a payment provider in Odoo.

**Features:**

* Redirect customers to Bonzai secure checkout
* Automatic order confirmation upon successful payment
* Invoice creation and payment reconciliation
* Webhook support for real-time payment notifications
* Automatic reconciliation cron for pending transactions

**Configuration:**

1. Go to Invoicing > Configuration > Payment Providers
2. Select Bonzai and enter your API Token and Product UUID
3. Configure the Webhook URL in your Bonzai dashboard
4. Enable the provider

**Requirements:**

* A Bonzai account with API access (bonzai.pro)
* HTTPS enabled on your Odoo instance for webhooks
""",
    'author': 'Loic FONTAINE',
    'website': 'https://www.bonzai.pro',
    'license': 'LGPL-3',
    'depends': ['payment'],
    'data': [
        'security/ir.model.access.csv',
        'views/payment_bonzai_templates.xml',  # Templates first (defines bonzai_redirect_form)
        'views/payment_provider_views.xml',
        'data/payment_provider_data.xml',      # Provider before method
        'data/payment_method_data.xml',        # Method references provider via provider_ids
    ],
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'assets': {
        'web.assets_frontend': [
            'payment_bonzai/static/src/js/payment_form.js',
        ],
    },
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
}
