import logging
import re
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.payment_bonzai.const import (
    API_URL,
    DEFAULT_PAYMENT_METHOD_CODES,
    SUPPORTED_CURRENCIES,
)

_logger = logging.getLogger(__name__)


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    # === SELECTION EXTENSION ===#
    code = fields.Selection(
        selection_add=[('bonzai', 'Bonzai')],
        ondelete={'bonzai': 'set default'},
    )

    # === BONZAI CREDENTIALS ===#
    bonzai_api_token = fields.Char(
        string="API Token",
        required_if_provider='bonzai',
        copy=False,
        groups='base.group_system',
        help="Your Bonzai API token from https://www.bonzai.pro/user/profile",
    )
    bonzai_product_uuid = fields.Char(
        string="Product UUID",
        required_if_provider='bonzai',
        copy=False,
        help="The UUID of the Bonzai product to use for payments",
    )
    bonzai_webhook_secret = fields.Char(
        string="Webhook Secret",
        copy=False,
        readonly=True,
        default=lambda self: secrets.token_urlsafe(32),
        groups='base.group_system',
        help="Secret token used to secure the webhook URL",
    )
    bonzai_webhook_url = fields.Char(
        string="Webhook URL",
        compute='_compute_bonzai_webhook_url',
        groups='base.group_system',
        help="Full webhook URL to configure in Bonzai dashboard",
    )

    # === COMPUTE METHODS ===#

    @api.depends('bonzai_webhook_secret')
    def _compute_bonzai_webhook_url(self):
        """ Compute the full webhook URL for display in the backend. """
        for provider in self:
            if provider.code == 'bonzai' and provider.bonzai_webhook_secret:
                base_url = provider.get_base_url()
                # Force HTTPS for webhook URL (required for production)
                if base_url.startswith('http://'):
                    base_url = base_url.replace('http://', 'https://', 1)
                provider.bonzai_webhook_url = (
                    f"{base_url}/payment/bonzai/webhook/{provider.bonzai_webhook_secret}"
                )
            else:
                provider.bonzai_webhook_url = False

    def _compute_feature_support_fields(self):
        """ Override to set Bonzai-specific feature support. """
        super()._compute_feature_support_fields()
        for provider in self.filtered(lambda p: p.code == 'bonzai'):
            provider.support_express_checkout = False
            provider.support_manual_capture = False  # No manual capture support
            provider.support_refund = 'none'  # Bonzai API doesn't support refunds
            provider.support_tokenization = False

    # === CONSTRAINT METHODS ===#

    # Regex pattern for valid Bonzai product UUID (alphanumeric, typically 8 chars)
    _BONZAI_UUID_PATTERN = re.compile(r'^[a-zA-Z0-9]{6,20}$')

    @api.constrains('bonzai_api_token', 'bonzai_product_uuid')
    def _check_bonzai_credentials(self):
        """ Ensure credentials are set and valid when provider is enabled. """
        for provider in self.filtered(lambda p: p.code == 'bonzai' and p.state != 'disabled'):
            if not provider.bonzai_api_token or not provider.bonzai_product_uuid:
                raise ValidationError(_(
                    "Bonzai API Token and Product UUID are required to enable the provider."
                ))
            # Security: Validate product UUID format to prevent injection
            if not self._BONZAI_UUID_PATTERN.match(provider.bonzai_product_uuid):
                raise ValidationError(_(
                    "Invalid Product UUID format. It should contain only alphanumeric characters."
                ))

    # === CRUD OVERRIDES ===#

    def write(self, vals):
        """ Override to sync payment method countries when provider countries change. """
        result = super().write(vals)
        if 'available_country_ids' in vals:
            for provider in self.filtered(lambda p: p.code == 'bonzai'):
                bonzai_methods = provider.payment_method_ids.filtered(
                    lambda pm: pm.code == 'bonzai'
                )
                bonzai_methods.supported_country_ids = provider.available_country_ids
        return result

    # === BUSINESS METHODS ===#

    def _get_supported_currencies(self):
        """ Override to return Bonzai-supported currencies only. """
        supported = super()._get_supported_currencies()
        if self.code == 'bonzai':
            return supported.filtered(lambda c: c.name in SUPPORTED_CURRENCIES)
        return supported

    def _get_default_payment_method_codes(self):
        """ Override to return Bonzai default payment method codes. """
        if self.code != 'bonzai':
            return super()._get_default_payment_method_codes()
        return DEFAULT_PAYMENT_METHOD_CODES

    # === API REQUEST METHODS ===#

    def _bonzai_get_api_url(self):
        """ Return the Bonzai API base URL. """
        return API_URL

    def _build_request_url(self, endpoint):
        """ Build the full API URL for Bonzai requests.

        :param str endpoint: The API endpoint (e.g., '/products/{uuid}/checkout')
        :return: The full URL
        :rtype: str
        """
        return f"{self._bonzai_get_api_url()}{endpoint}"

    def _build_request_headers(self, method=None, endpoint=None, payload=None, **kwargs):
        """ Build the headers for Bonzai API requests.

        :param str method: The HTTP method (unused, for Odoo 19 compatibility)
        :param str endpoint: The API endpoint (unused, for Odoo 19 compatibility)
        :param dict payload: The request payload (unused, for Odoo 19 compatibility)
        :return: The headers dict
        :rtype: dict
        """
        return {
            'Authorization': f'Bearer {self.bonzai_api_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

    def _bonzai_make_request(self, endpoint, payload=None, method='POST'):
        """ Make an API request to Bonzai.

        :param str endpoint: The API endpoint
        :param dict payload: The request payload (for POST requests)
        :param str method: The HTTP method ('GET' or 'POST')
        :return: The JSON response
        :rtype: dict
        :raises ValidationError: If the request fails
        """
        self.ensure_one()

        _logger.info(
            "Bonzai API request: %s %s",
            method,
            endpoint,
        )

        try:
            # Use Odoo 19 _send_api_request signature: (method, endpoint, *, json=None, ...)
            response = self._send_api_request(
                method,
                endpoint,
                json=payload,
            )
            return response
        except ValidationError:
            raise
        except Exception as e:
            _logger.exception("Bonzai API request failed: %s", e)
            raise ValidationError(_(
                "Communication with Bonzai failed. Please try again later."
            )) from e

    def _bonzai_create_checkout(
        self, amount, currency, metadata=None, partner=None, redirect_url=None
    ):
        """ Create a Bonzai checkout session.

        :param float amount: The payment amount
        :param recordset currency: The res.currency record
        :param dict metadata: Optional metadata to attach to the order
        :param recordset partner: Optional res.partner for prefilling
        :param str redirect_url: URL to redirect to after payment
        :return: The checkout response with 'order_id' and 'checkout_url'
        :rtype: dict
        """
        self.ensure_one()

        payload = {
            'amount': amount,  # Bonzai expects amount in currency units (not cents)
            'currency': currency.name,
            'mode': 'one_off',
        }

        if metadata:
            payload['metadata'] = metadata

        # Add redirect URL if provided
        if redirect_url:
            payload['redirect_url'] = redirect_url

        # Prefill customer info if available
        if partner:
            if partner.email:
                payload['email'] = partner.email
            if partner.name:
                # Split name into firstname/lastname
                name_parts = partner.name.split(' ', 1)
                payload['firstname'] = name_parts[0]
                if len(name_parts) > 1:
                    payload['lastname'] = name_parts[1]
            if partner.zip:
                payload['postal_code'] = partner.zip

        endpoint = f'/products/{self.bonzai_product_uuid}/checkout'
        response = self._bonzai_make_request(endpoint, payload=payload, method='POST')

        return response

    def _bonzai_get_order(self, order_id):
        """ Retrieve order details from Bonzai.

        :param str order_id: The Bonzai order ID
        :return: The order details
        :rtype: dict
        """
        self.ensure_one()

        endpoint = f'/orders/{order_id}'
        response = self._bonzai_make_request(endpoint, method='GET')

        return response

    def _get_redirect_form_view(self, is_validation=False):
        """ Override to return Bonzai redirect form view. """
        if self.code != 'bonzai':
            return super()._get_redirect_form_view(is_validation=is_validation)
        return self.env.ref('payment_bonzai.bonzai_redirect_form')

    # === WEBHOOK URL HELPER ===#

    def _bonzai_get_webhook_url(self):
        """ Get the full webhook URL for this provider.

        :return: The webhook URL
        :rtype: str
        """
        self.ensure_one()
        base_url = self.get_base_url()
        # Force HTTPS for webhook URL (required for production)
        if base_url.startswith('http://'):
            base_url = base_url.replace('http://', 'https://', 1)
        return f"{base_url}/payment/bonzai/webhook/{self.bonzai_webhook_secret}"
