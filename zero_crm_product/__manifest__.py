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
{
    'name': "CRM opportunity Products",

    'summary': """
        CRM Opportunity Leads Products""",

    'description': """
        Add Products and Services to CRM Lead / Opportunity
Add any Product Type "Storable Product - Consumable - Service " To lead/Opportunity in CRM
Support Price List related CRM users defined by default in user partner ID profile. 
Opportunity Expected Revenue Computed by Net Total Amount "Products/Services Lines"
Duplicate opportunity will Duplicate All Products Line .
Add Note Line And Section Line to Opportunity and Transfer to Quotation with Products Lines.
Pricelist Changed Automatics related Customer if customer defined to lead/Opportunity.
Support Multi Currency and currency automatics related Price List Currency.
Support Fiscal Position.
Add Payment Terms Related Opportunity
New menu To Manage Products, Product Variants, Products Attribute and Pricelist  Also from CRM.
When Create Quotation from Opportunity System will transfer All New Fields to Quotation.
#odoo
#branch
odoo 16 accounting
odoo accounting
odoo course
odoo pos
erp odoo
crm odoo
odoo 16 inventory
odoo implementation
odoo inventory
#odoo
#odoo 
#crmp 
#crm 
#opportunity 
#products 
#car 
#service 
#center 
#realestate
    """,

    'author': 'Zero Systems',
    'website': "http://erpzero.com",
    'live_test_url': 'https://youtu.be/643WhbrZ0IE',
    'category': 'Sales',
    'version': '0.6',
    'depends': ['sale_crm'],
    'data': [
        'security/ir.model.access.csv',
        'views/views.xml',
    ],
    "price": 55.00,
    "currency": 'EUR',
    'installable': True,
    'auto_install': False,
    "application": True,
    'pre_init_check_vers': 'pre_init_check_vers',
    'images': ['static/description/crmproduct.png'],
}
