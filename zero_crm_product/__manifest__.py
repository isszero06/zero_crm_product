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
    'name': "CRM Products",

    'summary': """
        Add Products to opportunity/Lead""",

    'description': """
        Add Products to opportunity/Lead
    """,

    'author': 'Zero Systems',
    'website': "http://erpzero.com",
    # 'live_test_url': 'https://youtu.be/L94RQeFL_w8',
    'category': 'Sales',
    'version': '0.6',
    'depends': ['sale_crm'],
    'data': [
        'security/ir.model.access.csv',
        'views/views.xml',
    ],
    "price": 25.00,
    "currency": 'EUR',
    'installable': True,
    'auto_install': False,
    "application": True,
    'pre_init_check_vers': 'pre_init_check_vers',
    'images': ['static/description/crmproduct.png'],
}
