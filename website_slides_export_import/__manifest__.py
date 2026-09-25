{
    'name': 'eLearning Export Import',
'author': 'Vertel Sverige AB',
'website': 'https://vertel.se/apps/odoo-lms/website_slides_export_import',
    'version': '18.0.1.0.0',
    'category': 'eLearning',
    'summary': 'Export and import eLearning courses easily.',
    'description': '''
eLearning Export Import
=======================

    Export and import eLearning courses easily.

    Features:

        - Guided Wizards: Step-by-step dialogs for data entry.
        - UI Integration: Extends 1 view(s) in the Odoo interface.
    ''',
    'depends': ['website_slides'],
    'data': [
        'security/ir.model.access.csv',
        'views/elearning_wizard_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'AGPL-3',
}
