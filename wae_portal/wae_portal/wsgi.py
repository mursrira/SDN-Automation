"""
WSGI config for wae_portal project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/1.11/howto/deployment/wsgi/
"""

import os
import sys
import ssl

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "wae_portal.settings")

path='/opt/wae_portal'
if path not in sys.path:
        sys.path.append(path)
path='/opt/wae_portal/env/lib/python2.7/site-packages'
if path not in sys.path:
        sys.path.append(path)

if (not os.environ.get('PYTHONHTTPSVERIFY', '') and getattr(ssl, '_create_unverified_context', None)): 
    ssl._create_default_https_context = ssl._create_unverified_context

application = get_wsgi_application()
