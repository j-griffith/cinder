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

import time

from oslo_utils import uuidutils

from cinder import test
from cinder.tests import fake_driver
from cinder.tests.functional.api import client
from cinder.tests.functional import functional_helpers


class VolumesTest(functional_helpers._V3FunctionalTestBase):
    _vol_type_name = 'functional_test_type'

    def setUp(self):
        super(VolumesTest, self).setUp()
        self.api.create_type(self._vol_type_name)
        fake_driver.LoggingVolumeDriver.clear_logs()
        self.auth_url = 'http://%s:%s/v3' % (self.osapi.host, self.osapi.port)

    def _get_flags(self):
        f = super(VolumesTest, self)._get_flags()
        f['volume_driver'] = \
            'cinder.tests.unit.fake_driver.LoggingVolumeDriver'
        f['default_volume_type'] = self._vol_type_name
        return f

    def _poll_while(self, volume_id, continue_states, max_retries=5):
        """Poll (briefly) while the state is in continue_states."""
        retries = 0
        while True:
            try:
                found_volume = self.api.get_volume(volume_id)
            except client.OpenStackApiNotFoundException:
                found_volume = None
                break

            self.assertEqual(volume_id, found_volume['id'])

            if found_volume['status'] not in continue_states:
                break

            time.sleep(1)
            retries = retries + 1
            if retries > max_retries:
                break
        return found_volume

    @test.testtools.skip("bug 1606715")
    def test_create_attachment(self):
        created_volume = self.api.post_volume({'volume': {
            'size': 1, 'name': 'vol1'}})
        self.assertEqual('vol1', created_volume['name'])
        created_volume_id = created_volume['id']
        # Wait (briefly) for creation. Delay is due to the 'message queue'
        found_volume = self._poll_while(created_volume_id, ['creating'])
        # It should be available...
        self.assertEqual('available', found_volume['status'])

        connector = {'host': 'functional-test-host',
                     'initiator': 'iqn.1993-08.org.debian:01:cad181614cec',
                     'ip': '1.1.1.1',
                     'platform': 'x86_64',
                     'os_type': 'linux2',
                     'multipath': False,
                     'instance_uuid': 'ac9b872b-6231-4223-a96e-a5f25334f026'}
        kwargs = {'os-create_attachment': {
            'connector': connector,
            'instance_uuid': 'ac9b872b-6231-4223-a96e-a5f25334f026',
            'mountpoint': '/dev/vdb'}}
        response = self.api.api_post('volumes/%s/action' % created_volume_id,
                                     kwargs)
        self.assertTrue(uuidutils.is_uuid_like(
            response['connection_info']['attachment_id']))
