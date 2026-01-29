import hmac
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class BonzaiController(http.Controller):
    """ Controller for Bonzai payment provider. """

    _return_url = '/payment/bonzai/return'
    _webhook_url = '/payment/bonzai/webhook/<string:webhook_secret>'

    @http.route(
        _return_url,
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
        save_session=False,
    )
    def bonzai_return_from_checkout(self, **kwargs):
        """ Handle the return from Bonzai checkout.

        The user is redirected here after completing (or canceling) the payment
        on Bonzai. We poll the order status to update the transaction.

        :param dict kwargs: The query parameters (reference, etc.)
        :return: Redirect to the payment status page
        """
        reference = kwargs.get('reference')

        if reference:
            # Sanitize reference for logging (no sensitive data)
            _logger.info("Bonzai return received for reference: %s", reference[:50] if reference else None)

            # Find transaction and verify it belongs to current user's session
            tx = request.env['payment.transaction'].sudo().search([
                ('reference', '=', reference),
                ('provider_code', '=', 'bonzai'),
            ], limit=1)

            # Security: Only allow polling if transaction is linked to current partner
            # or if user is not logged in (public checkout)
            if tx and tx.state == 'pending':
                current_partner = request.env.user.partner_id
                is_public_user = request.env.user._is_public()

                if is_public_user or tx.partner_id == current_partner:
                    _logger.info(
                        "Bonzai return: transaction %s still pending, polling status",
                        tx.reference,
                    )
                    tx._bonzai_poll_order_status()
                else:
                    _logger.warning(
                        "Bonzai return: unauthorized polling attempt for transaction %s",
                        tx.reference,
                    )

        return request.redirect('/payment/status')

    @http.route(
        _webhook_url,
        type='http',
        auth='public',
        methods=['GET', 'POST'],
        csrf=False,
    )
    def bonzai_webhook(self, webhook_secret, **kwargs):
        """ Handle Bonzai webhook notifications.

        Bonzai sends POST requests with JSON payloads for events:
        - product_access_granted: Payment completed successfully
        - product_access_revoked: Access revoked (subscription ended, etc.)

        Also accepts GET for URL verification.

        :param str webhook_secret: The secret token in the URL
        :return: Response
        """
        # Handle GET (URL verification) vs POST (actual webhook)
        if request.httprequest.method == 'GET':
            _logger.info("Bonzai webhook GET (URL verification)")
            return request.make_json_response({'status': 'ok'})

        # POST - parse JSON body
        try:
            data = json.loads(request.httprequest.data.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            _logger.warning("Bonzai webhook: Invalid JSON body")
            return request.make_json_response(
                {'status': 'error', 'message': 'Invalid JSON'},
                status=400
            )

        # Log only non-sensitive webhook info
        _logger.info(
            "Bonzai webhook received: event_type=%s, order_id=%s",
            data.get('event_type'),
            data.get('order_id'),
        )

        # Verify the webhook secret using constant-time comparison
        # First, find all active Bonzai providers
        providers = request.env['payment.provider'].sudo().search([
            ('code', '=', 'bonzai'),
            ('state', '!=', 'disabled'),
        ])

        # Use constant-time comparison to prevent timing attacks
        provider = None
        for p in providers:
            if p.bonzai_webhook_secret and hmac.compare_digest(
                p.bonzai_webhook_secret,
                webhook_secret or ''
            ):
                provider = p
                break

        if not provider:
            _logger.warning("Bonzai webhook: Invalid or unknown webhook secret")
            return request.make_json_response(
                {'status': 'error', 'message': 'Unauthorized'},
                status=403
            )

        # Find the transaction
        tx = None

        # Try to find by order_id first
        order_id = data.get('order_id')
        if order_id:
            tx = request.env['payment.transaction'].sudo().search([
                ('bonzai_order_id', '=', str(order_id)),
                ('provider_code', '=', 'bonzai'),
                ('provider_id', '=', provider.id),  # Security: verify transaction belongs to this provider
            ], limit=1)

        # Fallback: find by metadata reference (metadata is in order.metadata)
        if not tx:
            order_data = data.get('order', {})
            metadata = order_data.get('metadata', {}) or {}
            reference = metadata.get('odoo_tx_reference')
            if reference:
                tx = request.env['payment.transaction'].sudo().search([
                    ('reference', '=', reference),
                    ('provider_code', '=', 'bonzai'),
                    ('provider_id', '=', provider.id),  # Security: verify transaction belongs to this provider
                ], limit=1)

        if not tx:
            _logger.warning(
                "Bonzai webhook: No transaction found for order_id=%s",
                order_id,
            )
            return request.make_json_response(
                {'status': 'error', 'message': 'Transaction not found'},
                status=404
            )

        # Process the notification
        try:
            tx._bonzai_process_webhook(data)
            return request.make_json_response(
                {'status': 'ok', 'message': 'Webhook processed successfully'}
            )
        except Exception as e:
            _logger.exception("Bonzai webhook processing error for tx %s", tx.reference)
            # Don't expose internal error details to external callers
            return request.make_json_response(
                {'status': 'error', 'message': 'Internal processing error'},
                status=500
            )
