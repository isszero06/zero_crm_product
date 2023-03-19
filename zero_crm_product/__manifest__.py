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
    'name': "CRM Opportunity Products",

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
crm odoo
#odoo
#odoo 
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
    'category': 'Sales/CRM',
    'version': '0.6',
    "sequence": 0,
    'license': 'OPL-1',
    'depends': ['sale_crm'],
    'data': [
        'security/ir.model.access.csv',
        'security/ir_rules.xml',
        'views/views.xml',
    ],
    "price": 35.00,
    "currency": 'EUR',
    'installable': True,
    'auto_install': False,
    "application": True,
    'pre_init_check_vers': 'pre_init_check_vers',
    'images': ['static/description/crmproduct.png'],
}
