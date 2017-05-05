#!/usr/bin/python

import os

import brick_cinderclient_ext
from cinderclient import client
from cinderclient.contrib import noauth
from keystoneauth1 import loading
from keystoneauth1 import session

bypass_url = "http://127.0.0.1:8776/v3"
project_id = "cinderflex"

auth_plugin = noauth.CinderNoAuthPlugin('',
                                        project_id,
                                        None,
                                        bypass_url)

loader = loading.get_plugin_loader('noauth')
auth = loader.load_from_options(endpoint=bypass_url,
                                user_id="foo",
                                project_id="foo")
sess = session.Session(auth=auth)

c = client.Client(
            3,
            'password', 'cinderflex', bypass_url,
            tenant_id='cinderflex',
            bypass_url=bypass_url,
            auth_plugin=auth_plugin,
            session=sess)

print(c.volumes.list())
