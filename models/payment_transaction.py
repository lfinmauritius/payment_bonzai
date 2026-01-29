import logging
from urllib.parse import urlparse, parse_qs, quote

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    # === BONZAI-SPECIFIC FIELDS ===#
    bonzai_order_id = fields.Char(
        string="Bonzai Order ID",
        readonly=True,
        copy=False,
        help="The order ID returned by Bonzai",
    )

    # === BUSINESS METHODS ===#

    def _get_specific_processing_values(self, processing_values):
        """ Override to return Bonzai-specific processing values.

        :param dict processing_values: The generic processing values
        :return: The Bonzai-specific processing values
        :rtype: dict
        """
        res = super()._get_specific_processing_values(processing_values)
        if self.provider_code != 'bonzai':
            return res

        # Build metadata for reconciliation
        metadata = {
            'odoo_tx_reference': self.reference,
            'odoo_tx_id': str(self.id),
        }

        # Add sale order reference if available
        if self.sale_order_ids:
            metadata['odoo_sale_orders'] = ','.join(self.sale_order_ids.mapped('name'))

        # Add invoice reference if available
        if self.invoice_ids:
            metadata['odoo_invoices'] = ','.join(self.invoice_ids.mapped('name'))

        # Build redirect URL (force HTTPS for production)
        base_url = self.provider_id.get_base_url()
        if base_url.startswith('http://'):
            base_url = base_url.replace('http://', 'https://', 1)
        # URL-encode reference to handle special characters safely
        encoded_reference = quote(self.reference, safe='')
        redirect_url = f"{base_url}/payment/bonzai/return?reference={encoded_reference}"

        # Create Bonzai checkout session
        checkout_response = self.provider_id._bonzai_create_checkout(
            amount=self.amount,
            currency=self.currency_id,
            metadata=metadata,
            partner=self.partner_id,
            redirect_url=redirect_url,
        )

        # Store the Bonzai order ID for reconciliation
        self.bonzai_order_id = checkout_response.get('order_id')

        _logger.info(
            "Bonzai checkout created for transaction %s: order_id=%s",
            self.reference,
            self.bonzai_order_id,
        )

        res['api_url'] = checkout_response.get('checkout_url')
        return res

    def _get_specific_rendering_values(self, processing_values):
        """ Override to return Bonzai-specific rendering values for the redirect form.

        :param dict processing_values: The processing values (includes specific values)
        :return: The rendering values for the redirect form template
        :rtype: dict
        """
        res = super()._get_specific_rendering_values(processing_values)
        if self.provider_code != 'bonzai':
            return res

        # Parse the checkout URL to extract base URL and query parameters
        # This is needed because HTML form GET overwrites existing query params
        checkout_url = processing_values.get('api_url', '')
        parsed = urlparse(checkout_url)

        # Base URL without query string
        base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

        # Extract query parameters as dict for hidden form fields
        query_params = parse_qs(parsed.query)
        # parse_qs returns lists, we need single values
        url_params = {k: v[0] for k, v in query_params.items()}

        res['api_url'] = base_url
        res['url_params'] = url_params
        return res

    # === WEBHOOK PROCESSING ===#

    def _bonzai_process_webhook(self, data):
        """ Process Bonzai webhook notification data.

        :param dict data: The webhook payload from Bonzai
        :raises ValueError: If amount verification fails
        """
        self.ensure_one()

        event_type = data.get('event_type')
        order_id = data.get('order_id')

        _logger.info(
            "Processing Bonzai webhook for %s: event_type=%s, order_id=%s",
            self.reference,
            event_type,
            order_id,
        )

        # Update provider reference if not set
        if order_id and not self.provider_reference:
            self.provider_reference = str(order_id)

        # Map Bonzai event_type to transaction state
        if event_type == 'product_access_granted':
            # Security: Only allow transition from 'pending' or 'draft' states
            if self.state in ('pending', 'draft'):
                # Security: Verify the amount paid matches expected amount
                order_data = data.get('order', {})
                paid_amount = order_data.get('amount')
                paid_currency = order_data.get('currency', '').upper()

                if paid_amount is not None:
                    # Convert to float for comparison (handle string amounts)
                    try:
                        paid_amount = float(paid_amount)
                    except (ValueError, TypeError):
                        _logger.error(
                            "Bonzai webhook: Invalid amount format for %s: %s",
                            self.reference,
                            paid_amount,
                        )
                        raise ValueError("Invalid amount format in webhook")

                    # Verify amount matches (with small tolerance for rounding)
                    if abs(paid_amount - self.amount) > 0.01:
                        _logger.error(
                            "Bonzai webhook: Amount mismatch for %s! "
                            "Expected %.2f, received %.2f",
                            self.reference,
                            self.amount,
                            paid_amount,
                        )
                        self._set_error(_("Payment amount mismatch detected"))
                        raise ValueError(
                            f"Amount mismatch: expected {self.amount}, got {paid_amount}"
                        )

                    # Verify currency matches
                    if paid_currency and paid_currency != self.currency_id.name:
                        _logger.error(
                            "Bonzai webhook: Currency mismatch for %s! "
                            "Expected %s, received %s",
                            self.reference,
                            self.currency_id.name,
                            paid_currency,
                        )
                        self._set_error(_("Payment currency mismatch detected"))
                        raise ValueError(
                            f"Currency mismatch: expected {self.currency_id.name}, "
                            f"got {paid_currency}"
                        )

                self._set_done()
                _logger.info("Bonzai transaction %s marked as done", self.reference)
                # Trigger post-processing: confirm sale order, create invoice & payment
                self._post_process()
            elif self.state == 'done':
                _logger.info(
                    "Bonzai webhook: transaction %s already done, skipping",
                    self.reference,
                )
            else:
                _logger.warning(
                    "Bonzai webhook: cannot mark transaction %s as done from state %s",
                    self.reference,
                    self.state,
                )
        elif event_type == 'product_access_revoked':
            if self.state not in ('cancel', 'error'):
                self._set_canceled(state_message=_("Payment was revoked by Bonzai"))
                _logger.info("Bonzai transaction %s marked as canceled", self.reference)
        else:
            _logger.warning(
                "Bonzai: Unknown event_type '%s' for transaction %s",
                event_type,
                self.reference,
            )

    # === RECONCILIATION METHODS ===#

    def _bonzai_poll_order_status(self):
        """ Poll Bonzai API to check order status.

        This method is called when returning from Bonzai if the webhook
        hasn't been received yet, or by the reconciliation cron.
        """
        self.ensure_one()

        if self.provider_code != 'bonzai' or not self.bonzai_order_id:
            return

        # Security: Only allow polling from valid source states
        if self.state not in ('pending', 'draft'):
            _logger.info(
                "Bonzai poll: transaction %s already in final state %s",
                self.reference,
                self.state,
            )
            return

        _logger.info(
            "Polling Bonzai order status for transaction %s (order_id=%s)",
            self.reference,
            self.bonzai_order_id,
        )

        try:
            order_data = self.provider_id._bonzai_get_order(self.bonzai_order_id)

            # Update provider reference
            if not self.provider_reference:
                self.provider_reference = str(self.bonzai_order_id)

            # Check order status and update transaction
            status = order_data.get('status')
            _logger.info(
                "Bonzai order %s status: %s",
                self.bonzai_order_id,
                status,
            )

            if status == 'completed':
                # Security: Verify amount before marking as done
                paid_amount = order_data.get('amount')
                paid_currency = order_data.get('currency', '').upper()

                if paid_amount is not None:
                    try:
                        paid_amount = float(paid_amount)
                    except (ValueError, TypeError):
                        _logger.error(
                            "Bonzai poll: Invalid amount format for %s",
                            self.reference,
                        )
                        return

                    # Verify amount matches (with small tolerance for rounding)
                    if abs(paid_amount - self.amount) > 0.01:
                        _logger.error(
                            "Bonzai poll: Amount mismatch for %s! "
                            "Expected %.2f, received %.2f",
                            self.reference,
                            self.amount,
                            paid_amount,
                        )
                        self._set_error(_("Payment amount mismatch detected"))
                        return

                    # Verify currency matches
                    if paid_currency and paid_currency != self.currency_id.name:
                        _logger.error(
                            "Bonzai poll: Currency mismatch for %s! "
                            "Expected %s, received %s",
                            self.reference,
                            self.currency_id.name,
                            paid_currency,
                        )
                        self._set_error(_("Payment currency mismatch detected"))
                        return

                self._set_done()
                _logger.info(
                    "Bonzai transaction %s marked as done after polling",
                    self.reference,
                )
                # Trigger post-processing: confirm sale order, create invoice & payment
                self._post_process()
            elif status == 'canceled':
                self._set_canceled(state_message=_("Payment was canceled on Bonzai"))
            elif status == 'failed':
                self._set_error(_("Payment failed on Bonzai"))

        except Exception as e:
            _logger.warning(
                "Failed to poll Bonzai order status for %s: %s",
                self.reference,
                e,
            )

    @api.model
    def _bonzai_cron_reconcile_pending(self):
        """ Cron job to reconcile pending Bonzai transactions.

        This method polls the Bonzai API for transactions that have been
        pending for more than 30 minutes, in case the webhook was not received.
        """
        # Find pending Bonzai transactions older than 30 minutes
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), minutes=30)
        pending_txs = self.search([
            ('provider_code', '=', 'bonzai'),
            ('state', '=', 'pending'),
            ('bonzai_order_id', '!=', False),
            ('create_date', '<', cutoff),
        ])

        _logger.info(
            "Bonzai reconciliation cron: found %d pending transactions",
            len(pending_txs),
        )

        for tx in pending_txs:
            try:
                tx._bonzai_poll_order_status()
            except Exception as e:
                _logger.exception(
                    "Bonzai reconciliation failed for transaction %s: %s",
                    tx.reference,
                    e,
                )
