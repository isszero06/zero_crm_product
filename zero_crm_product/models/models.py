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

from collections import defaultdict
from datetime import timedelta
from itertools import groupby
from markupsafe import Markup
from odoo import SUPERUSER_ID, api, fields, Command, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Command
from odoo.osv import expression
from odoo.tools import float_is_zero, format_amount, format_date, html_keep_url, is_html_empty, float_compare, float_round
from odoo.tools.sql import create_index
from odoo.http import request

from dateutil.relativedelta import relativedelta

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
        for order in self:
            if opportunity_id: 
                order.update_from_opportunity()

        
    def update_from_opportunity(self):
        for order in self:
            opportunity_id = order.opportunity_id
            if not opportunity_id:
                return
            sequence = 10
            order.update({
                'opportunity_id': opportunity_id.id,
                'company_id': self.env.company or self.company_id.id,
                'partner_id': opportunity_id.partner_id.id,
                'campaign_id': opportunity_id.campaign_id.id,
                'medium_id': opportunity_id.medium_id.id,
                'origin': opportunity_id.name,
                'order_line': [],
                'source_id': opportunity_id.source_id.id,
                'tag_ids': [(6, 0, opportunity_id.tag_ids.ids)],
                'payment_term_id' : opportunity_id.payment_term_id.id or False,
                'partner_shipping_id' : opportunity_id.partner_shipping_id.id or False,
                'pricelist_id' : opportunity_id.pricelist_id.id or False,
                'currency_id' : opportunity_id.currency_id.id,
                'fiscal_position_id' : opportunity_id.fiscal_position_id.id or False,
                'note' : opportunity_id.note or False,
               })
            order_lines_data = [fields.Command.clear()]
            order_lines_data += [
                fields.Command.create(line.crm_led_products())
                for line in opportunity_id.lead_line
            ]

            order.order_line = order_lines_data


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'


    lead_line_id = fields.Many2one('crm.lead.product', 'Opportunity Line', ondelete='set null', index='btree_not_null')
    opportunity_id = fields.Many2one('crm.lead', 'Opportunity', related='order_id.opportunity_id', readonly=True)
        
    
class Opportunity2Quotation(models.TransientModel):
    _inherit = 'crm.quotation.partner'


    def action_apply(self):
        """ Convert lead to opportunity or merge lead and opportunity and open
            the freshly created opportunity view.
        """
        self.ensure_one()
        if self.action == 'create':
            self.lead_id._handle_partner_assignment(create_missing=True)
        elif self.action == 'exist':
            self.lead_id._handle_partner_assignment(force_partner_id=self.partner_id.id, create_missing=False)
        return self.lead_id.action_quotations_with_products()


class CrmLead(models.Model):
    _inherit = ['crm.lead']

    lead_line = fields.One2many('crm.lead.product', 'lead_id', string='Order Lines', copy=True, auto_join=True)
    ordered = fields.Boolean(string="Converted to Quotation",compute='ordered_state',store=True)

  

    def action_quotations_with_products(self):
        if not self.partner_id:
            return self.env["ir.actions.actions"]._for_xml_id("sale_crm.crm_quotation_partner_action")
        order_lines_data = [fields.Command.clear()]
        order_lines_data += [
            fields.Command.create(line.crm_led_products())
            for line in self.lead_line
        ]
        sale_order = self.env['sale.order']
        for record in self.lead_line:  
            sale_create_obj = sale_order.create({
                            'opportunity_id': self.id,
                            'partner_id': self.partner_id.id,
                            'order_line': order_lines_data,
                            'state': "draft",
                            'campaign_id': self.campaign_id.id,
                            'medium_id': self.medium_id.id,
                            'origin': self.name,
                            'source_id': self.source_id.id,
                            'tag_ids': [(6, 0, self.tag_ids.ids)],
                            'payment_term_id' : self.payment_term_id.id,
                            'partner_shipping_id' : self.partner_shipping_id.id,
                            'pricelist_id' : self.pricelist_id.id,
                            'currency_id' : self.currency_id.id,
                            'fiscal_position_id' : self.fiscal_position_id.id,
                            'note' : self.note,
                            })
            return {
                'name': "Sale Order",
                'type': 'ir.actions.act_window',
                'view_type': 'form',
                'view_mode': 'form',
                'res_model': 'sale.order',
                'view_id': self.env.ref('sale.view_order_form').id,
                'target': "new",
                'res_id': sale_create_obj.id
            }
            # return self.env["ir.actions.actions"]._for_xml_id("sale_crm.sale_action_quotations_new") 
  
    
    def action_open_discount_wizard(self):
        self.ensure_one()
        return {
            'name': _("Discount"),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.discount',
            'view_mode': 'form',
            'target': 'new',
        }
    @api.depends('quotation_count')
    def ordered_state(self):
        for rec in self:
            if rec.quotation_count and rec.quotation_count >0:
                rec.ordered = True

    note = fields.Html(
        string="Terms and conditions",
        compute='_compute_note',
        store=True, readonly=False, precompute=True)

    fiscal_position_id = fields.Many2one(
        comodel_name='account.fiscal.position',
        string="Fiscal Position",
        compute='_compute_fiscal_position_id',
        store=True, readonly=False, precompute=True, check_company=True,
        help="Fiscal positions are used to adapt taxes and accounts for particular customers or sales orders/invoices."
            "The default value comes from the customer.",
        domain="[('company_id', '=', company_id)]")
    pricelist_id = fields.Many2one(
        comodel_name='product.pricelist',
        string="Pricelist",
        compute='_compute_pricelist_id',
        store=True, readonly=False, precompute=True, check_company=True,
        tracking=1,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        help="If you change the pricelist, only newly added lines will be affected.")
    payment_term_id = fields.Many2one(
        comodel_name='account.payment.term',
        string="Payment Terms",
        compute='_compute_payment_term_id',
        store=True, readonly=False, precompute=True, check_company=True,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        compute='_compute_currency_id',
        store=True,
        precompute=True,
        ondelete='restrict'
    )
    currency_rate = fields.Float(
        string="Currency Rate",
        compute='_compute_currency_rate',
        digits=(12, 6),
        store=True, precompute=True)
    partner_shipping_id = fields.Many2one(
        comodel_name='res.partner',
        string="Delivery Address",
        compute='_compute_partner_shipping_id',
        store=True, readonly=False, required=False, precompute=True,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",)

    terms_type = fields.Selection(related='company_id.terms_type')
    
    @api.depends('partner_id')
    def _compute_note(self):
        use_invoice_terms = self.env['ir.config_parameter'].sudo().get_param('account.use_invoice_terms')
        if not use_invoice_terms:
            return
        for order in self:
            order = order.with_company(order.company_id)
            if order.terms_type == 'html' and self.env.company.invoice_terms_html:
                baseurl = html_keep_url(order._get_note_url() + '/terms')
                order.note = _('Terms & Conditions: %s', baseurl)
            elif not is_html_empty(self.env.company.invoice_terms):
                order.note = order.with_context(lang=order.partner_id.lang).env.company.invoice_terms


    @api.model
    def _get_note_url(self):
        return self.env.company.get_base_url()

    @api.depends('partner_id')
    def _compute_partner_shipping_id(self):
        for order in self:
            order.partner_shipping_id = order.partner_id.address_get(['delivery'])['delivery'] if order.partner_id else False

    @api.depends('partner_shipping_id', 'partner_id', 'company_id')
    def _compute_fiscal_position_id(self):
        cache = {}
        for order in self:
            if not order.partner_id:
                order.fiscal_position_id = False
                continue
            key = (order.company_id.id, order.partner_id.id, order.partner_shipping_id.id)
            if key not in cache:
                cache[key] = self.env['account.fiscal.position'].with_company(
                    order.company_id
                )._get_fiscal_position(order.partner_id, order.partner_shipping_id)
            order.fiscal_position_id = cache[key]


    amount_untaxed = fields.Monetary(string="Untaxed Amount", store=True, compute='_compute_amounts', tracking=5)
    amount_tax = fields.Monetary(string="Taxes", store=True, compute='_compute_amounts')
    amount_total = fields.Monetary(string="Total", store=True, compute='_compute_amounts', tracking=4)
    amount_undiscounted = fields.Float(
        string="Amount Before Discount",
        compute='_compute_amount_undiscounted', digits=0)
    country_code = fields.Char(related='company_id.account_fiscal_country_id.code', string="Country code")
    partner_credit_warning = fields.Text(
        compute='_compute_partner_credit_warning',
        groups='account.group_account_invoice,account.group_account_readonly')
    tax_calculation_rounding_method = fields.Selection(
        related='company_id.tax_calculation_rounding_method',
        depends=['company_id'])
    tax_country_id = fields.Many2one(
        comodel_name='res.country',
        compute='_compute_tax_country_id',
        compute_sudo=True)
    tax_totals = fields.Binary(compute='_compute_tax_totals', exportable=False)

    @api.depends('company_id', 'fiscal_position_id')
    def _compute_tax_country_id(self):
        for line in self:
            if line.fiscal_position_id.foreign_vat:
                line.tax_country_id = line.fiscal_position_id.country_id
            else:
                line.tax_country_id = line.company_id.account_fiscal_country_id

    show_update_fpos = fields.Boolean(
        string="Has Fiscal Position Changed", store=False)  # True if the fiscal position was changed
    show_update_pricelist = fields.Boolean(
        string="Has Pricelist Changed", store=False)  # True if the pricelist was changed

    def _compute_amount_undiscounted(self):
        for order in self:
            total = 0.0
            for line in order.lead_line:
                total += (line.price_subtotal * 100)/(100-line.discount) if line.discount != 100 else (line.price_unit * line.product_uom_qty)
            order.amount_undiscounted = total

    @api.depends('lead_line.price_subtotal', 'lead_line.price_tax', 'lead_line.price_total')
    def _compute_amounts(self):
        for order in self:
            order_lines = order.lead_line.filtered(lambda x: not x.display_type)

            if order.company_id.tax_calculation_rounding_method == 'round_globally':
                tax_results = self.env['account.tax']._compute_taxes([
                    line._convert_to_tax_base_line_dict()
                    for line in order_lines
                ])
                totals = tax_results['totals']
                amount_untaxed = totals.get(order.currency_id, {}).get('amount_untaxed', 0.0)
                amount_tax = totals.get(order.currency_id, {}).get('amount_tax', 0.0)
            else:
                amount_untaxed = sum(order_lines.mapped('price_subtotal'))
                amount_tax = sum(order_lines.mapped('price_tax'))

            order.amount_untaxed = amount_untaxed
            order.amount_tax = amount_tax
            order.amount_total = order.amount_untaxed + order.amount_tax
            if order.amount_total:
                order.write({'expected_revenue':order.amount_total})

    @api.depends('partner_id')
    def _compute_payment_term_id(self):
        for order in self:
            order = order.with_company(order.company_id)
            order.payment_term_id = order.partner_id.property_payment_term_id

  

    @api.depends('pricelist_id', 'company_id')
    def _compute_currency_id(self):
        for order in self:
            order.currency_id = order.pricelist_id.currency_id or order.company_id.currency_id

    @api.depends('partner_id', 'company_id')
    def _compute_pricelist_id(self):
        for order in self:
            if not order.partner_id:
                order.pricelist_id = order.user_id.partner_id.property_product_pricelist
                continue
            order = order.with_company(order.company_id)
            order.pricelist_id = order.partner_id.property_product_pricelist

    def init(self):
        create_index(self._cr, 'crm_lead_date_last_stage_update_id_idx', 'crm_lead', ["date_last_stage_update desc", "id desc"])

    @api.depends('currency_id', 'date_last_stage_update', 'company_id')
    def _compute_currency_rate(self):
        cache = {}
        for order in self:
            order_date = order.date_last_stage_update.date()
            if not order.company_id:
                order.currency_rate = order.currency_id.with_context(date=order_date).rate or 1.0
                continue
            elif not order.currency_id:
                order.currency_rate = 1.0
            else:
                key = (order.company_id.id, order_date, order.currency_id.id)
                if key not in cache:
                    cache[key] = self.env['res.currency']._get_conversion_rate(
                        from_currency=order.company_id.currency_id,
                        to_currency=order.currency_id,
                        company=order.company_id,
                        date=order_date,
                    )
                order.currency_rate = cache[key]

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


    @api.depends_context('lang')
    @api.depends('lead_line.tax_id', 'lead_line.price_unit', 'amount_total', 'amount_untaxed', 'currency_id')
    def _compute_tax_totals(self):
        for order in self:
            lead_line = order.lead_line.filtered(lambda x: not x.display_type)
            order.tax_totals = self.env['account.tax']._prepare_tax_totals(
                [x._convert_to_tax_base_line_dict() for x in lead_line],
                order.currency_id or order.company_id.currency_id,
            )


  
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

    @api.onchange('fiscal_position_id')
    def _onchange_fpos_id_show_update_fpos(self):
        if self and (
            not self.fiscal_position_id
            or (self.fiscal_position_id and self._origin.fiscal_position_id != self.fiscal_position_id)
        ):
            self.show_update_fpos = True

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
                self.partner_id = False
            return {
                'warning': {
                    'title': _("Warning for %s", partner.name),
                    'message': partner.sale_warn_msg,
                }
            }

    @api.onchange('pricelist_id')
    def _onchange_pricelist_id_show_update_prices(self):
        if self and self.pricelist_id and self._origin.pricelist_id != self.pricelist_id:
            self.show_update_pricelist = True


    def _merge_get_fields_specific(self):
        fields_info = super(CrmLead, self)._merge_get_fields_specific()
        fields_info['lead_line'] = lambda fname, leads: [(4, order.id) for order in leads.lead_line]
        return fields_info

    def action_update_taxes(self):
        self.ensure_one()

        self._recompute_taxes()

        if self.partner_id:
            self.message_post(body=_("Product taxes have been recomputed according to fiscal position %s.",
                self.fiscal_position_id._get_html_link() if self.fiscal_position_id else "")
            )

    def _recompute_taxes(self):
        lines_to_recompute = self.lead_line.filtered(lambda line: not line.display_type)
        lines_to_recompute._compute_tax_id()
        self.show_update_fpos = False

    def action_update_prices(self):
        self.ensure_one()

        self._recompute_prices()

        if self.pricelist_id:
            self.message_post(body=_(
                "Product prices have been recomputed according to pricelist %s.",
                self.pricelist_id._get_html_link(),
            ))

    def _recompute_prices(self):
        lines_to_recompute = self.lead_line.filtered(lambda line: not line.display_type)
        lines_to_recompute.invalidate_recordset(['pricelist_item_id'])
        lines_to_recompute._compute_price_unit()
        lines_to_recompute.discount = 0.0
        lines_to_recompute._compute_discount()
        self.show_update_pricelist = False


class CrmLeadProduct(models.Model):
    _name = 'crm.lead.product'
    _inherit = 'analytic.mixin'
    _description = 'CRM Order Line'
    _rec_names_search = ['name', 'lead_id.name']
    _order = 'lead_id, sequence, id'
    _check_company_auto = True

    def crm_led_products(self, order=False):
        self.ensure_one()
        aml_currency = order and order.currency_id or self.currency_id
        date = order and order.date_order or fields.Date.today()
        res = {
            'sequence': self.sequence,
            'display_type': self.display_type,
            'name': self.name,
            'product_id': self.product_id.id,
            'product_uom_qty': self.product_uom_qty,
            'product_uom': self.product_uom.id,
            'price_unit': self.currency_id._convert(self.price_unit, aml_currency, self.company_id, date, round=False),
            'tax_id': [(6, 0, self.tax_id.ids)],
            'product_packaging_id' :self.product_packaging_id.id,
            'product_packaging_qty' :self.product_packaging_qty,
            'product_type': self.product_type,
            'customer_lead': self.customer_lead,
            'discount': self.discount,
        }
        return res


    sale_order_lines = fields.One2many('sale.order.line', 'lead_line_id', string="Sales Lines", readonly=True, copy=False)
    ordered = fields.Boolean(string="Converted to Quotation",related='lead_id.ordered',store=True)
    lead_id = fields.Many2one(
        comodel_name='crm.lead',
        string="Opportunity Reference",
        required=True, ondelete='cascade', index=True, copy=False)
    sequence = fields.Integer(string="Sequence", default=10)
    state = fields.Many2one(
        related='lead_id.stage_id',
        string="Order Stage",
        copy=False, store=True, precompute=True)
    company_id = fields.Many2one(
        related='lead_id.company_id',
        store=True, index=True, precompute=True)
    currency_id = fields.Many2one(
        related='lead_id.currency_id',
        depends=['lead_id.currency_id'],
        store=True, precompute=True)
    order_partner_id = fields.Many2one(
        related='lead_id.partner_id',
        string="Customer",
        store=True, index=True, precompute=True)
    salesman_id = fields.Many2one(
        related='lead_id.user_id',
        string="Salesperson",
        store=True, precompute=True)
    display_type = fields.Selection(
        selection=[
            ('line_section', "Section"),
            ('line_note', "Note"),
        ],
        default=False)
    product_id = fields.Many2one(
        comodel_name='product.product',
        string="Product",
        change_default=True, ondelete='restrict', check_company=True, index='btree_not_null',
        domain="[('sale_ok', '=', True), '|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    product_template_id = fields.Many2one(
        string="Product Template",
        comodel_name='product.template',
        compute='_compute_product_template_id',
        readonly=False,
        search='_search_product_template_id',
        domain=[('sale_ok', '=', True)])
    product_uom_category_id = fields.Many2one(related='product_id.uom_id.category_id', depends=['product_id'])
    product_custom_attribute_value_ids = fields.One2many(
        comodel_name='product.attribute.custom.value', inverse_name='crm_lead_line_id',
        string="Custom Values",
        compute='_compute_custom_attribute_values',
        store=True, readonly=False, precompute=True, copy=True)

    product_no_variant_attribute_value_ids = fields.Many2many(
        comodel_name='product.template.attribute.value',
        string="Extra Values",
        compute='_compute_no_variant_attribute_values',
        store=True, readonly=False, precompute=True, ondelete='restrict')
    name = fields.Text(
        string="Description",
        compute='_compute_name',
        store=True, readonly=False, required=True, precompute=True)
    product_uom_qty = fields.Float(
        string="Quantity",
        compute='_compute_product_uom_qty',
        digits='Product Unit of Measure', default=1.0,
        store=True, readonly=False, required=True, precompute=True)
    product_uom = fields.Many2one(
        comodel_name='uom.uom',
        string="Unit of Measure",
        compute='_compute_product_uom',
        store=True, readonly=False, precompute=True, ondelete='restrict',
        domain="[('category_id', '=', product_uom_category_id)]")
    tax_id = fields.Many2many(
        comodel_name='account.tax',
        string="Taxes",
        compute='_compute_tax_id',
        store=True, readonly=False, precompute=True,
        context={'active_test': False})
    pricelist_item_id = fields.Many2one(
        comodel_name='product.pricelist.item',
        compute='_compute_pricelist_item_id')
    price_unit = fields.Float(
        string="Unit Price",
        compute='_compute_price_unit',
        digits='Product Price',
        store=True, readonly=False, required=True, precompute=True)
    discount = fields.Float(
        string="Discount (%)",
        compute='_compute_discount',
        digits='Discount',
        store=True, readonly=False, precompute=True)
    price_reduce = fields.Float(
        string="Price Reduce",
        compute='_compute_price_reduce',
        digits='Product Price',
        store=True, precompute=True)
    price_subtotal = fields.Monetary(
        string="Subtotal",
        compute='_compute_amount',
        store=True, precompute=True)
    price_tax = fields.Float(
        string="Total Tax",
        compute='_compute_amount',
        store=True, precompute=True)
    price_total = fields.Monetary(
        string="Total",
        compute='_compute_amount',
        store=True, precompute=True)
    price_reduce_taxexcl = fields.Monetary(
        string="Price Reduce Tax excl",
        compute='_compute_price_reduce_taxexcl',
        store=True, precompute=True)
    price_reduce_taxinc = fields.Monetary(
        string="Price Reduce Tax incl",
        compute='_compute_price_reduce_taxinc',
        store=True, precompute=True)
    customer_lead = fields.Float(
        string="Lead Time",
        compute='_compute_customer_lead',
        store=True, readonly=False, required=True, precompute=True,
        help="Number of days between the order confirmation and the shipping of the products to the customer")
    product_type = fields.Selection(related='product_id.detailed_type', depends=['product_id'])
    tax_calculation_rounding_method = fields.Selection(
        related='company_id.tax_calculation_rounding_method',
        string='Tax calculation rounding method', readonly=True)
    product_packaging_id = fields.Many2one(
        comodel_name='product.packaging',
        string="Packaging",
        compute='_compute_product_packaging_id',
        store=True, readonly=False, precompute=True,
        domain="[('sales', '=', True), ('product_id','=',product_id)]",
        check_company=True)
    product_packaging_qty = fields.Float(
        string="Packaging Quantity",
        compute='_compute_product_packaging_qty',
        store=True, readonly=False, precompute=True)


    @api.depends('product_id', 'product_uom_qty', 'product_uom')
    def _compute_product_packaging_id(self):
        for line in self:
            if line.product_packaging_id.product_id != line.product_id:
                line.product_packaging_id = False
            if line.product_id and line.product_uom_qty and line.product_uom:
                suggested_packaging = line.product_id.packaging_ids\
                        .filtered(lambda p: p.sales and (p.product_id.company_id <= p.company_id <= line.company_id))\
                        ._find_suitable_product_packaging(line.product_uom_qty, line.product_uom)
                line.product_packaging_id = suggested_packaging or line.product_packaging_id


    def _compute_customer_lead(self):
        self.customer_lead = 0.0

    @api.depends('product_packaging_id', 'product_uom', 'product_uom_qty')
    def _compute_product_packaging_qty(self):
        self.product_packaging_qty = 0
        for line in self:
            if not line.product_packaging_id:
                continue
            line.product_packaging_qty = line.product_packaging_id._compute_qty(line.product_uom_qty, line.product_uom)

    @api.depends('product_id')
    def _compute_product_template_id(self):
        for line in self:
            line.product_template_id = line.product_id.product_tmpl_id

    def _search_product_template_id(self, operator, value):
        return [('product_id.product_tmpl_id', operator, value)]

    @api.depends('product_id')
    def _compute_custom_attribute_values(self):
        for line in self:
            if not line.product_id:
                line.product_custom_attribute_value_ids = False
                continue
            if not line.product_custom_attribute_value_ids:
                continue
            valid_values = line.product_id.product_tmpl_id.valid_product_template_attribute_line_ids.product_template_value_ids
            for pacv in line.product_custom_attribute_value_ids:
                if pacv.custom_product_template_attribute_value_id not in valid_values:
                    line.product_custom_attribute_value_ids -= pacv

    @api.depends('product_id')
    def _compute_no_variant_attribute_values(self):
        for line in self:
            if not line.product_id:
                line.product_no_variant_attribute_value_ids = False
                continue
            if not line.product_no_variant_attribute_value_ids:
                continue
            valid_values = line.product_id.product_tmpl_id.valid_product_template_attribute_line_ids.product_template_value_ids
            for ptav in line.product_no_variant_attribute_value_ids:
                if ptav._origin not in valid_values:
                    line.product_no_variant_attribute_value_ids -= ptav

    @api.depends('product_id')
    def _compute_name(self):
        for line in self:
            if not line.product_id:
                continue

            name = line.with_context(lang=line.order_partner_id.lang)._get_sale_lead_line_multiline_description_sale()
            line.name = name

    def _get_sale_lead_line_multiline_description_sale(self):
        self.ensure_one()
        return self.product_id.get_product_multiline_description_sale() + self._get_sale_order_line_multiline_description_variants()

    def _get_sale_order_line_multiline_description_variants(self):
        if not self.product_custom_attribute_value_ids and not self.product_no_variant_attribute_value_ids:
            return ""

        name = "\n"

        custom_ptavs = self.product_custom_attribute_value_ids.custom_product_template_attribute_value_id
        no_variant_ptavs = self.product_no_variant_attribute_value_ids._origin

        for ptav in (no_variant_ptavs - custom_ptavs):
            name += "\n" + ptav.display_name

        custom_values = sorted(self.product_custom_attribute_value_ids, key=lambda r: (r.custom_product_template_attribute_value_id.id, r.id))
        for pacv in custom_values:
            name += "\n" + pacv.display_name

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

    @api.depends('product_id')
    def _compute_tax_id(self):
        taxes_by_product_company = defaultdict(lambda: self.env['account.tax'])
        lines_by_company = defaultdict(lambda: self.env['crm.lead.product'])
        cached_taxes = {}
        for line in self:
            lines_by_company[line.company_id] += line
        for product in self.product_id:
            for tax in product.taxes_id:
                taxes_by_product_company[(product, tax.company_id)] += tax
        for company, lines in lines_by_company.items():
            for line in lines.with_company(company):
                taxes = taxes_by_product_company[(line.product_id, company)]
                if not line.product_id or not taxes:
                    line.tax_id = False
                    continue
                fiscal_position = line.lead_id.fiscal_position_id
                cache_key = (fiscal_position.id, company.id, tuple(taxes.ids))
                if cache_key in cached_taxes:
                    result = cached_taxes[cache_key]
                else:
                    result = fiscal_position.map_tax(taxes)
                    cached_taxes[cache_key] = result
                line.tax_id = result

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

    def _get_display_price(self):
        self.ensure_one()

        pricelist_price = self._get_pricelist_price()

        if self.lead_id.pricelist_id.discount_policy == 'with_discount':
            return pricelist_price

        if not self.pricelist_item_id:
            return pricelist_price

        base_price = self._get_pricelist_price_before_discount()

        return max(base_price, pricelist_price)

    def _get_pricelist_price(self):
        self.ensure_one()
        self.product_id.ensure_one()

        pricelist_rule = self.pricelist_item_id
        order_date = self.lead_id.date_last_stage_update or fields.Date.context_today(self)
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
        self.ensure_one()
        self.product_id.ensure_one()

        pricelist_rule = self.pricelist_item_id
        order_date = fields.Date.context_today(self)
        product = self.product_id.with_context(**self._get_product_price_context())
        qty = self.product_uom_qty or 1.0
        uom = self.product_uom

        if pricelist_rule:
            pricelist_item = pricelist_rule
            if pricelist_item.pricelist_id.discount_policy == 'without_discount':
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
                    line.discount = discount

    @api.depends('price_unit', 'discount')
    def _compute_price_reduce(self):
        for line in self:
            line.price_reduce = line.price_unit * (1.0 - line.discount / 100.0)

    def _convert_to_tax_base_line_dict(self):
        self.ensure_one()
        return self.env['account.tax']._convert_to_tax_base_line_dict(
            self,
            partner=self.lead_id.partner_id,
            currency=self.lead_id.currency_id,
            product=self.product_id,
            taxes=self.tax_id,
            price_unit=self.price_unit,
            quantity=self.product_uom_qty,
            discount=self.discount,
            price_subtotal=self.price_subtotal,
        )

    @api.depends('product_uom_qty', 'discount', 'price_unit', 'tax_id')
    def _compute_amount(self):
        for line in self:
            tax_results = self.env['account.tax']._compute_taxes([line._convert_to_tax_base_line_dict()])
            totals = list(tax_results['totals'].values())[0]
            amount_untaxed = totals['amount_untaxed']
            amount_tax = totals['amount_tax']

            line.update({
                'price_subtotal': amount_untaxed,
                'price_tax': amount_tax,
                'price_total': amount_untaxed + amount_tax,
            })
            if self.env.context.get('import_file', False) and not self.env.user.user_has_groups('account.group_account_manager'):
                line.tax_id.invalidate_recordset(['invoice_repartition_line_ids'])

    @api.depends('price_subtotal', 'product_uom_qty')
    def _compute_price_reduce_taxexcl(self):
        for line in self:
            line.price_reduce_taxexcl = line.price_subtotal / line.product_uom_qty if line.product_uom_qty else 0.0

    @api.depends('price_total', 'product_uom_qty')
    def _compute_price_reduce_taxinc(self):
        for line in self:
            line.price_reduce_taxinc = line.price_total / line.product_uom_qty if line.product_uom_qty else 0.0




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


    def _convert_to_sol_currency(self, amount, currency):
        self.ensure_one()
        to_currency = self.currency_id or self.lead_id.currency_id
        if currency and to_currency and currency != to_currency:
            conversion_date = self.lead_id.date_last_stage_update or fields.Date.context_today(self)
            company = self.company_id or self.lead_id.company_id or self.env.company
            return currency._convert(
                from_amount=amount,
                to_currency=to_currency,
                company=company,
                date=conversion_date,
                round=False,
            )
        return amount

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


    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('display_type') or self.default_get(['display_type']).get('display_type'):
                vals['product_uom_qty'] = 0.0

        lines = super().create(vals_list)
        quotation_count = len(self.lead_id.order_ids.filtered_domain(self.lead_id._get_lead_quotation_domain()))
        for line in lines:
            if line.product_id and quotation_count >0:
                msg = _("Extra line with %s", line.product_id.display_name)
                line.lead_id.message_post(body=msg)
        return lines

