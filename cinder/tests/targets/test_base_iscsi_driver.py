#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from oslo.config import cfg

from cinder.openstack.common import timeutils
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.targets import iscsi


class FakeDriver(iscsi.ISCSITarget):
    def create_export(self, context, vref):
        pass

    def ensure_export(self, context, vref,
                      iscsi_name, vol_path,
                      vol_group, cfg):
        pass

    def remove_export(self, context, vref):
        pass

    def terminate_connection(self, vref, **kwargs):
        pass


class FakeIncompleteDriver(iscsi.ISCSITarget):
    def null_method():
        pass


class TestBaseISCSITargetDriver(test.TestCase):

    def setUp(self):
        super(TestBaseISCSITargetDriver, self).setUp()
        self.fake_id_1 = 'ed2c1fd4-5fc0-11e4-aa15-123b93f75cba'
        self.fake_id_2 = 'ed2c2222-5fc0-11e4-aa15-123b93f75cba'
        self.fake_id_3 = 'ed2c236c-5fc0-11e4-aa15-123b93f75cba'
        self.fake_id_4 = 'ed2c2498-5fc0-11e4-aa15-123b93f75cba'
        configuration = conf.Configuration(cfg.StrOpt('iscsi_target_prefix',
                                                      default='foo',
                                                      help='you wish'))
        self.target = FakeDriver(configuration=configuration)

    def test_abc_methods_not_present_fails(self):
        configuration = conf.Configuration(cfg.StrOpt('iscsi_target_prefix',
                                                      default='foo',
                                                      help='you wish'))
        self.assertRaises(TypeError,
                          FakeIncompleteDriver,
                          configuration=configuration)

    def test_get_iscsi_properties(self):
        testvol = {'project_id': self.fake_id_1,
                   'name': 'testvol',
                   'size': 1,
                   'id': self.fake_id_2,
                   'volume_type_id': None,
                   'provider_location': '10.10.7.1:3260 '
                                        'iqn.2010-10.org.openstack:'
                                        'volume-%s 0' % self.fake_id_2,
                   'provider_auth': 'CHAP stack-1-a60e2611875f40199931f2'
                                    'c76370d66b 2FE0CQ8J196R',
                   'provider_geometry': '512 512',
                   'created_at': timeutils.utcnow(), }
        val = self.target._get_iscsi_properties(testvol)
