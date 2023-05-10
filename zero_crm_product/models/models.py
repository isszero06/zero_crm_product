# -*- coding: utf-8 -*-
#################################################################################
# Author      : Zero For Information Systems (<www.erpzero.com>)
# Copyright(c): 2016-Zero For Information Systems
# All Rights Reserved.
#
# This program is copyright property of the author mentioned above.
# You can`t redistribute it and/or modify it.
#
#################################################################################


from odoo.exceptions import UserError
from odoo.tools.misc import get_lang

from datetime import datetime, timedelta
from itertools import groupby
import json

from odoo import api, fields, models, SUPERUSER_ID, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.osv import expression
from odoo.tools import float_is_zero, html_keep_url, is_html_empty, float_compare, float_round


class ProductAttributeCustomValue(models.Model):
    _inherit = "product.attribute.custom.value"

    crm_lead_line_id = fields.Many2one('crm.lead.product', string="CRM Order Line", required=True, ondelete='cascade')

    _sql_constraints = [
        ('crm_custom_value_unique', 'unique(custom_product_template_attribute_value_id, crm_lead_line_id)', "Only one Custom Value is allowed per Attribute Value per CRM Order Line.")
    ]


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    
    @api.onchange('opportunity_id')
    def opportunity_id_change(self):
        opportunity_id = self.opportunity_id.with_context(lang=self.partner_id.lang)
        if opportunity_id:
            self.payment_term_id = opportunity_id.payment_term_id.id
            self.partner_shipping_id = opportunity_id.partner_shipping_id.id
            self.pricelist_id = opportunity_id.pricelist_id.id
            self.currency_id = opportunity_id.currency_id.id
            self.fiscal_position_id = opportunity_id.fiscal_position_id.id
            self.note = opportunity_id.note

            order_line_data = [fields.Command.clear()]
            order_line_data += [
                fields.Command.create(line.crm_led_products())
                for line in opportunity_id.lead_line
            ]

            self.order_line = order_line_data
    


class CrmLeadProduct(models.Model):
    _inherit = 'sale.order.line'

    lead_line = fields.One2many('crm.lead.product', 'sale_line_ids', string='Lead Lines')
    product_type = fields.Selection(related='product_id.detailed_type', depends=['product_id'],store=True)

class CrmLead(models.Model):
    _inherit = 'crm.lead'


    ordered = fields.Boolean(string="Converted to Quotation",compute='ordered_state',store=True)

    @api.depends('quotation_count')
    def ordered_state(self):
        for rec in self:
            if rec.quotation_count and rec.quotation_count >0:
                rec.ordered = True

    lead_line = fields.One2many('crm.lead.product', 'lead_id', string='Order Lines', copy=True, auto_join=True)


    @api.model
    def _get_note_url(self):
        return self.env.company.get_base_url()

    @api.model
    def _default_note(self):
        use_invoice_terms = self.env['ir.config_parameter'].sudo().get_param('account.use_invoice_terms')
        if use_invoice_terms and self.env.company.terms_type == "html":
            baseurl = html_keep_url(self._default_note_url() + '/terms')
            return _('Terms & Conditions: %s', baseurl)
        return use_invoice_terms and self.env.company.invoice_terms or ''


    note = fields.Html('Terms and conditions', default=_default_note)

    payment_term_id = fields.Many2one(
        'account.payment.term', string='Payment Terms', check_company=True,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",)
    terms_type = fields.Selection(related='company_id.terms_type')
 
    partner_shipping_id = fields.Many2one(
        'res.partner', string='Delivery Address', readonly=False, required=True,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",)

    pricelist_id = fields.Many2one(
        'product.pricelist', string='Pricelist', check_company=True,  # Unrequired company
        required=True, readonly=True, 
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]", tracking=1,
        help="If you change the pricelist, only newly added lines will be affected.")
    currency_id = fields.Many2one(related='pricelist_id.currency_id', depends=["pricelist_id"], store=True, ondelete="restrict")
    amount_untaxed = fields.Monetary(string='Untaxed Amount', store=True, compute='_amount_all', tracking=5)
    tax_totals_json = fields.Char(compute='_compute_tax_totals_json')

    @api.depends('lead_line.tax_id', 'lead_line.price_unit', 'amount_total', 'amount_untaxed')
    def _compute_tax_totals_json(self):
        def compute_taxes(lead_line):
            price = lead_line.price_unit * (1 - (lead_line.discount or 0.0) / 100.0)
            order = lead_line.lead_id
            return lead_line.tax_id._origin.compute_all(price, order.currency_id, lead_line.product_uom_qty, product=lead_line.product_id, partner=order.partner_shipping_id)

        account_move = self.env['account.move']
        for order in self:
            tax_lines_data = account_move._prepare_tax_lines_data_for_totals_from_object(order.lead_line, compute_taxes)
            tax_totals = account_move._get_tax_totals(order.partner_id, tax_lines_data, order.amount_total, order.amount_untaxed, order.currency_id)
            order.tax_totals_json = json.dumps(tax_totals)

    amount_tax = fields.Monetary(string='Taxes', store=True, compute='_amount_all')
    amount_total = fields.Monetary(string='Total', store=True, compute='_amount_all', tracking=4)
    currency_rate = fields.Float("Currency Rate", compute='_compute_currency_rate', store=True, digits=(12, 6), help='The rate of the currency to the currency of rate 1 applicable at the date of the order')

    payment_term_id = fields.Many2one(
        'account.payment.term', string='Payment Terms', check_company=True,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",)
    fiscal_position_id = fields.Many2one(
        'account.fiscal.position', string='Fiscal Position',
        domain="[('company_id', '=', company_id)]", check_company=True,
        help="Fiscal positions are used to adapt taxes and accounts for particular customers or sales orders/invoices."
        "The default value comes from the customer.")
    tax_country_id = fields.Many2one(
        comodel_name='res.country',
        compute='_compute_tax_country_id',
        # Avoid access error on fiscal position when reading a sale order with company != user.company_ids
        compute_sudo=True,
        help="Technical field to filter the available taxes depending on the fiscal country and fiscal position.")

    @api.onchange('fiscal_position_id')
    def _compute_tax_id(self):
        for order in self:
            order.lead_line._compute_tax_id()

    amount_undiscounted = fields.Float(
        string="Amount Before Discount",
        compute='_compute_amount_undiscounted', digits=0)
    country_code = fields.Char(related='company_id.account_fiscal_country_id.code', string="Country code")
    partner_credit_warning = fields.Text(
        compute='_compute_partner_credit_warning',
        groups='account.group_account_invoice,account.group_account_readonly')

    @api.depends('company_id.account_fiscal_country_id', 'fiscal_position_id.country_id', 'fiscal_position_id.foreign_vat')
    def _compute_tax_country_id(self):
        for record in self:
            if record.fiscal_position_id.foreign_vat:
                record.tax_country_id = record.fiscal_position_id.country_id
            else:
                record.tax_country_id = record.company_id.account_fiscal_country_id

    show_update_pricelist = fields.Boolean(
        string="Has Pricelist Changed", store=False)

    def _compute_amount_undiscounted(self):
        for order in self:
            total = 0.0
            for line in order.lead_line:
                total += (line.price_subtotal * 100)/(100-line.discount) if line.discount != 100 else (line.price_unit * line.product_uom_qty)
            order.amount_undiscounted = total

    @api.depends('lead_line.price_total')
    def _amount_all(self):
        for order in self:
            amount_untaxed = amount_tax = 0.0
            for line in order.lead_line:
                amount_untaxed += line.price_subtotal
                amount_tax += line.price_tax
            order.update({
                'amount_untaxed': amount_untaxed,
                'amount_tax': amount_tax,
                'amount_total': amount_untaxed + amount_tax,
            })
            if order.amount_total:
                order.write({'expected_revenue':order.amount_total})


    @api.depends('pricelist_id', 'date_open', 'company_id')
    def _compute_currency_rate(self):
        for order in self:
            if not order.company_id:
                order.currency_rate = order.currency_id.with_context(date=order.date_open).rate or 1.0
                continue
            elif order.company_id.currency_id and order.currency_id:
                order.currency_rate = self.env['res.currency']._get_conversion_rate(order.company_id.currency_id, order.currency_id, order.company_id, order.date_open)
            else:
                order.currency_rate = 1.0

    @api.depends('company_id', 'partner_id', 'amount_total')
    def _compute_partner_credit_warning(self):
        for order in self:
            order.with_company(order.company_id)
            order.partner_credit_warning = ''
            show_warning = order.company_id.account_use_credit_limit
            if show_warning:
                updated_credit = order.partner_id.commercial_partner_id.credit + (order.amount_total * order.currency_rate)
                order.partner_credit_warning = self.env['account.move']._build_credit_warning_message(
                    order, updated_credit)

              
    @api.constrains('company_id', 'lead_line')
    def _check_lead_line_company_id(self):
        for order in self:
            companies = order.lead_line.product_id.company_id
            if companies and companies != order.company_id:
                bad_products = order.lead_line.product_id.filtered(lambda p: p.company_id and p.company_id != order.company_id)
                raise ValidationError(_(
                    "Your opportunity contains products from company %(product_company)s whereas your opportunity belongs to company %(quote_company)s. \n Please change the company of your opportunity or remove the products from other companies (%(bad_products)s).",
                    product_company=', '.join(companies.mapped('display_name')),
                    quote_company=order.company_id.display_name,
                    bad_products=', '.join(bad_products.mapped('display_name')),
                ))


    @api.onchange('partner_id')
    def onchange_partner_id(self):
        if not self.partner_id:
            self.update({
                'partner_shipping_id': False,
                'fiscal_position_id': False,
            })
            return

        self = self.with_company(self.company_id)

        addr = self.partner_id.address_get(['delivery'])
        partner_user = self.partner_id.user_id or self.partner_id.commercial_partner_id.user_id
        values = {
            'pricelist_id': self.partner_id.property_product_pricelist and self.partner_id.property_product_pricelist.id or False,
            'payment_term_id': self.partner_id.property_payment_term_id and self.partner_id.property_payment_term_id.id or False,
            'partner_shipping_id': addr['delivery'],
        }
        user_id = partner_user.id
        if not self.env.context.get('not_self_saleperson'):
            user_id = user_id or self.env.context.get('default_user_id', self.env.uid)
        if user_id and self.user_id.id != user_id:
            values['user_id'] = user_id

        if self.env['ir.config_parameter'].sudo().get_param('account.use_invoice_terms'):
            if self.terms_type == 'html' and self.env.company.invoice_terms_html:
                baseurl = html_keep_url(self.get_base_url() + '/terms')
                values['note'] = _('Terms & Conditions: %s', baseurl)
            elif not is_html_empty(self.env.company.invoice_terms):
                values['note'] = self.with_context(lang=self.partner_id.lang).env.company.invoice_terms
        if not self.env.context.get('not_self_saleperson') or not self.team_id:
            default_team = self.env.context.get('default_team_id', False) or self.partner_id.team_id.id
            values['team_id'] = self.env['crm.team'].with_context(
                default_team_id=default_team
            )._get_default_team_id(domain=['|', ('company_id', '=', self.company_id.id), ('company_id', '=', False)], user_id=user_id)
        self.update(values)

    @api.onchange('partner_shipping_id', 'partner_id', 'company_id')
    def onchange_partner_shipping_id(self):
        self.fiscal_position_id = self.env['account.fiscal.position'].with_company(self.company_id).get_fiscal_position(self.partner_id.id, self.partner_shipping_id.id)
        return {}

    @api.onchange('partner_id')
    def _onchange_partner_id_warning(self):
        if not self.partner_id:
            return
        partner = self.partner_id

        if partner.sale_warn == 'no-message' and partner.parent_id:
            partner = partner.parent_id

        if partner.sale_warn and partner.sale_warn != 'no-message':
            if partner.sale_warn != 'block' and partner.parent_id and partner.parent_id.sale_warn == 'block':
                partner = partner.parent_id

            if partner.sale_warn == 'block':
                self.update({'partner_id': False, 'partner_shipping_id': False, 'pricelist_id': False})

            return {
                'warning': {
                    'title': _("Warning for %s", partner.name),
                    'message': partner.sale_warn_msg,
                }
            }


    @api.onchange('pricelist_id', 'lead_line')
    def _onchange_pricelist_id(self):
        if self.lead_line and self.pricelist_id and self._origin.pricelist_id != self.pricelist_id:
            self.show_update_pricelist = True
        else:
            self.show_update_pricelist = False

    def _get_update_prices_lines(self):
        return self.lead_line.filtered(lambda line: not line.display_type)

    def action_update_prices(self):
        self.ensure_one()
        for line in self._get_update_prices_lines():
            line.product_uom_change()
            line.discount = 0  # Force 0 as discount for the cases when _onchange_discount directly returns
            line._onchange_discount()
        self.show_update_pricelist = False
        self.message_post(body=_("Product prices have been recomputed according to pricelist <b>%s<b> ", self.pricelist_id.display_name))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'company_id' in vals_list:
                self = self.with_company(vals['company_id'])
            if any(f not in vals for f in ['partner_shipping_id', 'pricelist_id']):
                partner = self.env['res.partner'].browse(vals.get('partner_id'))
                addr = partner.address_get(['delivery'])
                vals['partner_shipping_id'] = vals.setdefault('partner_shipping_id', addr['delivery'])
                vals['pricelist_id'] = vals.setdefault('pricelist_id', partner.property_product_pricelist.id)
            leads = super(CrmLead, self).create(vals_list)
            return leads

   
    def _merge_get_fields_specific(self):
        fields_info = super(CrmLead, self)._merge_get_fields_specific()
        fields_info['lead_line'] = lambda fname, leads: [(4, order.id) for order in leads.lead_line]
        return fields_info


class CrmLeadProduct(models.Model):
    _name = 'crm.lead.product'
    _description = 'CRM Order Line'
    _rec_names_search = ['name', 'lead_id.name']
    _order = 'lead_id, sequence, id'
    _check_company_auto = True

    def crm_led_products(self):
        self.ensure_one()
        return {
            'sequence': self.sequence,
            'display_type': self.display_type,
            'name': self.name,
            'product_id': self.product_id.id,
            'product_uom_qty': self.product_uom_qty,
            'product_uom': self.product_uom.id,
            'price_unit':self.price_unit,
            'tax_id': [(6, 0, self.tax_id.ids)],
            'product_packaging_id' :self.product_packaging_id.id,
            'product_packaging_qty' :self.product_packaging_qty,
            'product_type': self.product_type,
            'customer_lead': self.customer_lead,
            'discount': self.discount,
        }

    sale_line_ids = fields.Many2one('sale.order.line', 'Sales Order Lines', index='btree_not_null')
    lead_id = fields.Many2one(
        comodel_name='crm.lead',
        string="Opportunity Reference",
        required=True, ondelete='cascade', index=True, copy=False)

    ordered = fields.Boolean(string="Converted to Quotation",related='lead_id.ordered',store=True)


    def _check_line_unlink(self):
        return self.filtered(lambda line: line.ordered  and not line.display_type)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_confirmed(self):
        if self._check_line_unlink():
            raise UserError(_('You can not remove an Opportunity line once the Quotation is Created.\nYou should rather set the quantity to 0.'))


    sequence = fields.Integer(string="Sequence", default=10)
    state = fields.Many2one(
        related='lead_id.stage_id',
        string="Order Stage",
        copy=False, store=True)
    salesman_id = fields.Many2one(related='lead_id.user_id', store=True, string='Salesperson')
    currency_id = fields.Many2one(related='lead_id.currency_id', depends=['lead_id.currency_id'], store=True, string='Currency')
    company_id = fields.Many2one(related='lead_id.company_id', string='Company', store=True, index=True)
    order_partner_id = fields.Many2one(related='lead_id.partner_id', store=True, string='Customer', index=True)
    display_type = fields.Selection(
        selection=[
            ('line_section', "Section"),
            ('line_note', "Note"),
        ],
        default=False)
    product_id = fields.Many2one(
        'product.product', string='Product', domain="[('sale_ok', '=', True), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        change_default=True, ondelete='restrict', check_company=True)  # Unrequired company
    product_template_id = fields.Many2one(
        'product.template', string='Product Template',
        related="product_id.product_tmpl_id", domain=[('sale_ok', '=', True)])
    product_uom_category_id = fields.Many2one(related='product_id.uom_id.category_id', depends=['product_id'])
    product_custom_attribute_value_ids = fields.One2many('product.attribute.custom.value', 'crm_lead_line_id', string="Custom Values", copy=True)
    product_no_variant_attribute_value_ids = fields.Many2many('product.template.attribute.value', string="Extra Values", ondelete='restrict')
    name = fields.Text(string='Description', required=True)
    product_uom_qty = fields.Float(
        string="Quantity",
        compute='_compute_product_uom_qty',
        digits='Product Unit of Measure', default=1.0,
        store=True, readonly=False, required=True)
    product_uom = fields.Many2one(
        comodel_name='uom.uom',
        string="Unit of Measure",
        compute='_compute_product_uom',
        store=True, readonly=False,  ondelete='restrict',
        domain="[('category_id', '=', product_uom_category_id)]")
    price_unit = fields.Float('Unit Price', required=True, digits='Product Price', default=0.0)

    price_subtotal = fields.Monetary(compute='_compute_amount', string='Subtotal', store=True)
    price_tax = fields.Float(compute='_compute_amount', string='Total Tax', store=True)
    price_total = fields.Monetary(compute='_compute_amount', string='Total', store=True)

    price_reduce = fields.Float(compute='_compute_price_reduce', string='Price Reduce', digits='Product Price', store=True)
    tax_id = fields.Many2many('account.tax', string='Taxes', context={'active_test': False})
    price_reduce_taxinc = fields.Monetary(compute='_compute_price_reduce_taxinc', string='Price Reduce Tax inc', store=True)
    price_reduce_taxexcl = fields.Monetary(compute='_compute_price_reduce_taxexcl', string='Price Reduce Tax excl', store=True)

    pricelist_item_id = fields.Many2one(
        comodel_name='product.pricelist.item',
        compute='_compute_pricelist_item_id')
    discount = fields.Float(string='Discount (%)', digits='Discount', default=0.0)
    customer_lead = fields.Float(
        string="Lead Time",
        compute='_compute_customer_lead',
        store=True, readonly=False, required=True, 
        help="Number of days between the order confirmation and the shipping of the products to the customer")
    product_type = fields.Selection(related='product_id.detailed_type', depends=['product_id'],store=True)
    product_packaging_id = fields.Many2one('product.packaging', string='Packaging', default=False, domain="[('sales', '=', True), ('product_id','=',product_id)]", check_company=True)
    product_packaging_qty = fields.Float('Packaging Quantity')
    product_updatable = fields.Boolean(compute='_compute_product_updatable', string='Can Edit Product', default=True)

    @api.depends('product_id', 'ordered')
    def _compute_product_updatable(self):
        for line in self:
            if line.ordered:
                line.product_updatable = False
            else:
                line.product_updatable = True


    @api.onchange('product_packaging_id', 'product_uom', 'product_uom_qty')
    def _onchange_update_product_packaging_qty(self):
        if not self.product_packaging_id:
            self.product_packaging_qty = False
        else:
            packaging_uom = self.product_packaging_id.product_uom_id
            packaging_uom_qty = self.product_uom._compute_quantity(self.product_uom_qty, packaging_uom)
            self.product_packaging_qty = float_round(packaging_uom_qty / self.product_packaging_id.qty, precision_rounding=packaging_uom.rounding)

    @api.onchange('product_packaging_qty')
    def _onchange_product_packaging_qty(self):
        if self.product_packaging_id:
            packaging_uom = self.product_packaging_id.product_uom_id
            qty_per_packaging = self.product_packaging_id.qty
            product_uom_qty = packaging_uom._compute_quantity(self.product_packaging_qty * qty_per_packaging, self.product_uom)
            if float_compare(product_uom_qty, self.product_uom_qty, precision_rounding=self.product_uom.rounding) != 0:
                self.product_uom_qty = product_uom_qty

    def _compute_customer_lead(self):
        self.customer_lead = 0.0

    def _get_real_price_currency(self, product, rule_id, qty, uom, pricelist_id):
        PricelistItem = self.env['product.pricelist.item']
        field_name = 'lst_price'
        currency_id = None
        product_currency = product.currency_id
        if rule_id:
            pricelist_item = PricelistItem.browse(rule_id)
            if pricelist_item.pricelist_id.discount_policy == 'without_discount':
                while pricelist_item.base == 'pricelist' and pricelist_item.base_pricelist_id and pricelist_item.base_pricelist_id.discount_policy == 'without_discount':
                    _price, rule_id = pricelist_item.base_pricelist_id.with_context(uom=uom.id).get_product_price_rule(product, qty, self.lead_id.partner_id)
                    pricelist_item = PricelistItem.browse(rule_id)

            if pricelist_item.base == 'standard_price':
                field_name = 'standard_price'
                product_currency = product.cost_currency_id
            elif pricelist_item.base == 'pricelist' and pricelist_item.base_pricelist_id:
                field_name = 'price'
                product = product.with_context(pricelist=pricelist_item.base_pricelist_id.id)
                product_currency = pricelist_item.base_pricelist_id.currency_id
            currency_id = pricelist_item.pricelist_id.currency_id

        if not currency_id:
            currency_id = product_currency
            cur_factor = 1.0
        else:
            if currency_id.id == product_currency.id:
                cur_factor = 1.0
            else:
                cur_factor = currency_id._get_conversion_rate(product_currency, currency_id, self.company_id or self.env.company, self.lead_id.date_open or fields.Date.today())

        product_uom = self.env.context.get('uom') or product.uom_id.id
        if uom and uom.id != product_uom:
            # the unit price is in a different uom
            uom_factor = uom._compute_price(1.0, product.uom_id)
        else:
            uom_factor = 1.0

        return product[field_name] * uom_factor * cur_factor, currency_id

    def get_sale_lead_line_multiline_description_sale(self, product):
        self.ensure_one()
        return self.product_id.get_product_multiline_description_sale() + self._get_sale_lead_line_multiline_description_variants()

    def _get_sale_lead_line_multiline_description_variants(self):
        if not self.product_custom_attribute_value_ids and not self.product_no_variant_attribute_value_ids:
            return ""

        name = "\n"

        custom_ptavs = self.product_custom_attribute_value_ids.custom_product_template_attribute_value_id
        no_variant_ptavs = self.product_no_variant_attribute_value_ids._origin
        for ptav in (no_variant_ptavs - custom_ptavs):
            name += "\n" + ptav.with_context(lang=self.lead_id.partner_id.lang).display_name

        custom_values = sorted(self.product_custom_attribute_value_ids, key=lambda r: (r.custom_product_template_attribute_value_id.id, r.id))
        # display the is_custom values
        for pacv in custom_values:
            name += "\n" + pacv.with_context(lang=self.lead_id.partner_id.lang).display_name

        return name

    @api.depends('display_type', 'product_id', 'product_packaging_qty')
    def _compute_product_uom_qty(self):
        for line in self:
            if line.display_type:
                line.product_uom_qty = 0.0
                continue

            if not line.product_packaging_id:
                continue
            packaging_uom = line.product_packaging_id.product_uom_id
            qty_per_packaging = line.product_packaging_id.qty
            product_uom_qty = packaging_uom._compute_quantity(
                line.product_packaging_qty * qty_per_packaging, line.product_uom)
            if float_compare(product_uom_qty, line.product_uom_qty, precision_rounding=line.product_uom.rounding) != 0:
                line.product_uom_qty = product_uom_qty

    @api.depends('product_id')
    def _compute_product_uom(self):
        for line in self:
            if not line.product_uom or (line.product_id.uom_id.id != line.product_uom.id):
                line.product_uom = line.product_id.uom_id

    @api.onchange('product_id')
    def product_id_change(self):
        self._update_description()
        self._update_taxes()

        product = self.product_id
        if product and product.sale_line_warn != 'no-message':
            if product.sale_line_warn == 'block':
                self.product_id = False
            return {
                'warning': {
                    'title': _("Warning for %s", product.name),
                    'message': product.sale_line_warn_msg,
                }
            }

    def _update_description(self):
        if not self.product_id:
            return
        valid_values = self.product_id.product_tmpl_id.valid_product_template_attribute_line_ids.product_template_value_ids
        # remove the is_custom values that don't belong to this template
        for pacv in self.product_custom_attribute_value_ids:
            if pacv.custom_product_template_attribute_value_id not in valid_values:
                self.product_custom_attribute_value_ids -= pacv

        # remove the no_variant attributes that don't belong to this template
        for ptav in self.product_no_variant_attribute_value_ids:
            if ptav._origin not in valid_values:
                self.product_no_variant_attribute_value_ids -= ptav

        vals = {}
        if not self.product_uom or (self.product_id.uom_id.id != self.product_uom.id):
            vals['product_uom'] = self.product_id.uom_id
            vals['product_uom_qty'] = self.product_uom_qty or 1.0

        product = self.product_id.with_context(
            lang=get_lang(self.env, self.lead_id.partner_id.lang).code,
        )

        self.update({'name': self.get_sale_lead_line_multiline_description_sale(product)})

    def _update_taxes(self):
        if not self.product_id:
            return

        vals = {}
        if not self.product_uom or (self.product_id.uom_id.id != self.product_uom.id):
            vals['product_uom'] = self.product_id.uom_id
            vals['product_uom_qty'] = self.product_uom_qty or 1.0

        product = self.product_id.with_context(
            partner=self.lead_id.partner_id,
            quantity=vals.get('product_uom_qty') or self.product_uom_qty,
            date=self.lead_id.date_open,
            pricelist=self.lead_id.pricelist_id.id,
            uom=self.product_uom.id
        )

        self._compute_tax_id()

        if self.lead_id.pricelist_id and self.lead_id.partner_id:
            vals['price_unit'] = product._get_tax_included_unit_price(
                self.company_id,
                self.lead_id.currency_id,
                self.lead_id.date_open,
                'sale',
                fiscal_position=self.lead_id.fiscal_position_id,
                product_price_unit=self._get_display_price(product),
                product_currency=self.lead_id.currency_id
            )

        self.update(vals)

    @api.onchange('product_uom', 'product_uom_qty')
    def product_uom_change(self):
        if not self.product_uom or not self.product_id:
            self.price_unit = 0.0
            return
        if self.lead_id.pricelist_id and self.lead_id.partner_id:
            product = self.product_id.with_context(
                lang=self.lead_id.partner_id.lang,
                partner=self.lead_id.partner_id,
                quantity=self.product_uom_qty,
                date=self.lead_id.date_open,
                pricelist=self.lead_id.pricelist_id.id,
                uom=self.product_uom.id,
                fiscal_position=self.env.context.get('fiscal_position')
            )
            self.price_unit = product._get_tax_included_unit_price(
                self.company_id or self.lead_id.company_id,
                self.lead_id.currency_id,
                self.lead_id.date_open,
                'sale',
                fiscal_position=self.lead_id.fiscal_position_id,
                product_price_unit=self._get_display_price(product),
                product_currency=self.lead_id.currency_id
            )

    @api.depends('price_unit', 'discount')
    def _compute_price_reduce(self):
        for line in self:
            line.price_reduce = line.price_unit * (1.0 - line.discount / 100.0)

    @api.depends('price_total', 'product_uom_qty')
    def _compute_price_reduce_taxinc(self):
        for line in self:
            line.price_reduce_taxinc = line.price_total / line.product_uom_qty if line.product_uom_qty else 0.0

    @api.depends('price_subtotal', 'product_uom_qty')
    def _compute_price_reduce_taxexcl(self):
        for line in self:
            line.price_reduce_taxexcl = line.price_subtotal / line.product_uom_qty if line.product_uom_qty else 0.0


    def _compute_tax_id(self):
        for line in self:
            line = line.with_company(line.company_id)
            fpos = line.lead_id.fiscal_position_id or line.lead_id.fiscal_position_id.get_fiscal_position(line.order_partner_id.id)
            # If company_id is set, always filter taxes by the company
            taxes = line.product_id.taxes_id.filtered(lambda t: t.company_id == line.env.company)
            line.tax_id = fpos.map_tax(taxes)

    def name_get(self):
        result = []
        for so_line in self.sudo():
            name = '%s - %s' % (so_line.lead_id.name, so_line.name and so_line.name.split('\n')[0] or so_line.product_id.name)
            if so_line.order_partner_id.ref:
                name = '%s (%s)' % (name, so_line.order_partner_id.ref)
            result.append((so_line.id, name))
        return result

    @api.model
    def _name_search(self, name, args=None, operator='ilike', limit=100, name_get_uid=None):
        if operator in ('ilike', 'like', '=', '=like', '=ilike'):
            args = expression.AND([
                args or [],
                ['|', ('lead_id.name', operator, name), ('name', operator, name)]
            ])
            return self._search(args, limit=limit, access_rights_uid=name_get_uid)
        return super(CrmLeadProduct, self)._name_search(name, args=args, operator=operator, limit=limit, name_get_uid=name_get_uid)

    @api.depends('product_id', 'product_uom', 'product_uom_qty')
    def _compute_pricelist_item_id(self):
        for line in self:
            if not line.product_id or line.display_type or not line.lead_id.pricelist_id:
                line.pricelist_item_id = False
            else:
                line.pricelist_item_id = line.lead_id.pricelist_id._get_product_rule(
                    line.product_id,
                    line.product_uom_qty or 1.0,
                    uom=line.product_uom,
                    date=line.lead_id.date_last_stage_update,
                )

    @api.depends('product_id', 'product_uom', 'product_uom_qty')
    def _compute_price_unit(self):
        for line in self:
            if not line.product_uom or not line.product_id or not line.lead_id.pricelist_id:
                line.price_unit = 0.0
            else:
                price = line.with_company(line.company_id)._get_display_price()
                line.price_unit = line.product_id._get_tax_included_unit_price(
                    line.company_id,
                    line.lead_id.currency_id,
                    line.lead_id.date_last_stage_update,
                    'sale',
                    fiscal_position=line.lead_id.fiscal_position_id,
                    product_price_unit=price,
                    product_currency=line.currency_id
                )

    def _get_display_price(self, product):
        no_variant_attributes_price_extra = [
            ptav.price_extra for ptav in self.product_no_variant_attribute_value_ids.filtered(
                lambda ptav:
                    ptav.price_extra and
                    ptav not in product.product_template_attribute_value_ids
            )
        ]
        if no_variant_attributes_price_extra:
            product = product.with_context(
                no_variant_attributes_price_extra=tuple(no_variant_attributes_price_extra)
            )

        if self.lead_id.pricelist_id.discount_policy == 'with_discount':
            return product.with_context(pricelist=self.lead_id.pricelist_id.id, uom=self.product_uom.id).price
        product_context = dict(self.env.context, partner_id=self.lead_id.partner_id.id, date=self.lead_id.date_open, uom=self.product_uom.id)

        final_price, rule_id = self.lead_id.pricelist_id.with_context(product_context).get_product_price_rule(product or self.product_id, self.product_uom_qty or 1.0, self.lead_id.partner_id)
        base_price, currency = self.with_context(product_context)._get_real_price_currency(product, rule_id, self.product_uom_qty, self.product_uom, self.lead_id.pricelist_id.id)
        if currency != self.lead_id.pricelist_id.currency_id:
            base_price = currency._convert(
                base_price, self.lead_id.pricelist_id.currency_id,
                self.lead_id.company_id or self.env.company, self.lead_id.date_open or fields.Date.today())
        # negative discounts (= surcharge) are included in the display price
        return max(base_price, final_price)

    def _get_pricelist_price(self):
        self.ensure_one()
        self.product_id.ensure_one()

        pricelist_rule = self.pricelist_item_id
        order_date = self.lead_id.date_last_stage_update or fields.Date.today()
        product = self.product_id.with_context(**self._get_product_price_context())
        qty = self.product_uom_qty or 1.0
        uom = self.product_uom or self.product_id.uom_id

        price = pricelist_rule._compute_price(
            product, qty, uom, order_date, currency=self.currency_id)

        return price

    def _get_product_price_context(self):
        self.ensure_one()
        res = {}
        no_variant_attributes_price_extra = [
            ptav.price_extra for ptav in self.product_no_variant_attribute_value_ids.filtered(
                lambda ptav:
                    ptav.price_extra and
                    ptav not in self.product_id.product_template_attribute_value_ids
            )
        ]
        if no_variant_attributes_price_extra:
            res['no_variant_attributes_price_extra'] = tuple(no_variant_attributes_price_extra)

        return res


    def _get_pricelist_price_before_discount(self):
        """Compute the price used as base for the pricelist price computation.

        :return: the product sales price in the order currency (without taxes)
        :rtype: float
        """
        self.ensure_one()
        self.product_id.ensure_one()

        pricelist_rule = self.pricelist_item_id
        order_date = fields.Date.today()
        # order_date = self.lead_id.date_last_stage_update or fields.Date.today()
        product = self.product_id.with_context(**self._get_product_price_context())
        qty = self.product_uom_qty or 1.0
        uom = self.product_uom

        if pricelist_rule:
            pricelist_item = pricelist_rule
            if pricelist_item.pricelist_id.discount_policy == 'without_discount':
                # Find the lowest pricelist rule whose pricelist is configured
                # to show the discount to the customer.
                while pricelist_item.base == 'pricelist' and pricelist_item.base_pricelist_id.discount_policy == 'without_discount':
                    rule_id = pricelist_item.base_pricelist_id._get_product_rule(
                        product, qty, uom=uom, date=order_date)
                    pricelist_item = self.env['product.pricelist.item'].browse(rule_id)

            pricelist_rule = pricelist_item

        price = pricelist_rule._compute_base_price(
            product,
            qty,
            uom,
            order_date,
            target_currency=self.currency_id,
        )

        return price

    @api.depends('product_id', 'product_uom', 'product_uom_qty')
    def _compute_discount(self):
        for line in self:
            if not line.product_id or line.display_type:
                line.discount = 0.0

            if not (
                line.lead_id.pricelist_id
                and line.lead_id.pricelist_id.discount_policy == 'without_discount'
            ):
                continue

            line.discount = 0.0

            if not line.pricelist_item_id:
                continue

            line = line.with_company(line.company_id)
            pricelist_price = line._get_pricelist_price()
            base_price = line._get_pricelist_price_before_discount()

            if base_price != 0:  # Avoid division by zero
                discount = (base_price - pricelist_price) / base_price * 100
                if (discount > 0 and base_price > 0) or (discount < 0 and base_price < 0):
                    # only show negative discounts if price is negative
                    # otherwise it's a surcharge which shouldn't be shown to the customer
                    line.discount = discount

    @api.depends('product_uom_qty', 'discount', 'price_unit', 'tax_id')
    def _compute_amount(self):
        for line in self:
            price = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
            taxes = line.tax_id.compute_all(price, line.lead_id.currency_id, line.product_uom_qty, product=line.product_id, partner=line.lead_id.partner_shipping_id)
            line.update({
                'price_tax': sum(t.get('amount', 0.0) for t in taxes.get('taxes', [])),
                'price_total': taxes['total_included'],
                'price_subtotal': taxes['total_excluded'],
            })
            if self.env.context.get('import_file', False) and not self.env.user.user_has_groups('account.group_account_manager'):
                line.tax_id.invalidate_cache(['invoice_repartition_line_ids'], [line.tax_id.id])




    @api.onchange('product_id')
    def _onchange_product_id_warning(self):
        if not self.product_id:
            return

        product = self.product_id
        if product.sale_line_warn != 'no-message':
            if product.sale_line_warn == 'block':
                self.product_id = False

            return {
                'warning': {
                    'title': _("Warning for %s", product.name),
                    'message': product.sale_line_warn_msg,
                }
            }


    @api.onchange('product_packaging_id')
    def _onchange_product_packaging_id(self):
        if self.product_packaging_id and self.product_uom_qty:
            newqty = self.product_packaging_id._check_qty(self.product_uom_qty, self.product_uom, "UP")
            if float_compare(newqty, self.product_uom_qty, precision_rounding=self.product_uom.rounding) != 0:
                return {
                    'warning': {
                        'title': _('Warning'),
                        'message': _(
                            "This product is packaged by %(pack_size).2f %(pack_name)s. You should sell %(quantity).2f %(unit)s.",
                            pack_size=self.product_packaging_id.qty,
                            pack_name=self.product_id.uom_id.name,
                            quantity=newqty,
                            unit=self.product_uom.name
                        ),
                    },
                }
    def _add_precomputed_values(self, vals_list):
        precision = self.env['decimal.precision'].precision_get('Discount')
        for vals in vals_list:
            if vals.get('discount'):
                vals['discount'] = float_round(vals['discount'], precision_digits=precision)
        return super()._add_precomputed_values(vals_list)


    @api.model
    def _prepare_add_missing_fields(self, values):
        """ Deduce missing required fields from the onchange """
        res = {}
        onchange_fields = ['name', 'price_unit', 'product_uom', 'tax_id']
        if values.get('lead_id') and values.get('product_id') and any(f not in values for f in onchange_fields):
            line = self.new(values)
            line.product_id_change()
            for field in onchange_fields:
                if field not in values:
                    res[field] = line._fields[field].convert_to_write(line[field], line)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if values.get('display_type', self.default_get(['display_type'])['display_type']):
                values.update(product_id=False, price_unit=0, product_uom_qty=0, product_uom=False, customer_lead=0)

            values.update(self._prepare_add_missing_fields(values))

        lines = super().create(vals_list)
        for line in lines:
            if line.product_id and line.lead_id.ordered:
                msg = _("Extra line with %s", line.product_id.display_name)
                line.lead_id.message_post(body=msg)
        return lines

    _sql_constraints = [
        ('accountable_required_fields',
            "CHECK(display_type IS NOT NULL OR (product_id IS NOT NULL AND product_uom IS NOT NULL))",
            "Missing required fields on accountable opportunity order line."),
        ('non_accountable_null_fields',
            "CHECK(display_type IS NULL OR (product_id IS NULL AND price_unit = 0 AND product_uom_qty = 0 AND product_uom IS NULL AND customer_lead = 0))",
            "Forbidden values on non-accountable opportunity order line"),
    ]

    def _update_line_quantity(self, values):
        orders = self.mapped('lead_id')
        for order in orders:
            lead_line = self.filtered(lambda x: x.lead_id == order)
            msg = "<b>" + _("The ordered quantity has been updated.") + "</b><ul>"
            for line in lead_line:
                msg += "<li> %s: <br/>" % line.product_id.display_name
                msg += _(
                    "Ordered Quantity: %(old_qty)s -> %(new_qty)s",
                    old_qty=line.product_uom_qty,
                    new_qty=values["product_uom_qty"]
                ) + "<br/>"
            msg += "</ul>"
            order.message_post(body=msg)

    def write(self, values):
        if 'display_type' in values and self.filtered(lambda line: line.display_type != values.get('display_type')):
            raise UserError(_("You cannot change the type of a Opportunity order line. Instead you should delete the current line and create a new line of the proper type."))

        if 'product_uom_qty' in values:
            precision = self.env['decimal.precision'].precision_get('Product Unit of Measure')
            self.filtered(
                lambda r: r.ordered == True and float_compare(r.product_uom_qty, values['product_uom_qty'], precision_digits=precision) != 0)._update_line_quantity(values)

        result = super(CrmLeadProduct, self).write(values)
        return result
