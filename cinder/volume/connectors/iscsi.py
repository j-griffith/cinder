# Copyright (c) 2014 OpenStack Foundation.
# All Rights Reserved.
#
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

from cinder.volume.connectors import connector
from cinder import exception
from cinder.image import image_utils
from cinder.openstack.common import excutils
from cinder.openstack.common import fileutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils
from cinder import utils
from cinder.volume import iscsi
from cinder.volume import rpcapi as volume_rpcapi
from cinder.volume import utils as volume_utils


class ISCSIConnector(connector.Connector):
    """Connector object for block storage devices.

    Base class for connector object, where connector
    is data transport mechanism specific calls.  This
    includes things like create targets, attach, detach
    etc.
    """

    def __init__(self, *args, **kwargs):
        super(ISCSIConnector, self).__init__(*args, **kwargs)

    def _get_iscsi_properties(self, volume):
        """Gets iscsi configuration

        We ideally get saved information in the volume entity, but fall back
        to discovery if need be. Discovery may be completely removed in future
        The properties are:

        :target_discovered:    boolean indicating whether discovery was used

        :target_iqn:    the IQN of the iSCSI target

        :target_portal:    the portal of the iSCSI target

        :target_lun:    the lun of the iSCSI target

        :volume_id:    the id of the volume (currently used by xen)

        :auth_method:, :auth_username:, :auth_password:

            the authentication details. Right now, either auth_method is not
            present meaning no authentication, or auth_method == `CHAP`
            meaning use CHAP with the specified credentials.

        :access_mode:    the volume access mode allow client used
                         ('rw' or 'ro' currently supported)
        """

        properties = {}

        location = volume['provider_location']

        if location:
            # provider_location is the same format as iSCSI discovery output
            properties['target_discovered'] = False
        else:
            location = self._do_iscsi_discovery(volume)

            if not location:
                msg = (_("Could not find iSCSI export for volume %s") %
                        (volume['name']))
                raise exception.InvalidVolume(reason=msg)

            LOG.debug(_("ISCSI Discovery: Found %s") % (location))
            properties['target_discovered'] = True

        results = location.split(" ")
        properties['target_portal'] = results[0].split(",")[0]
        properties['target_iqn'] = results[1]
        try:
            properties['target_lun'] = int(results[2])
        except (IndexError, ValueError):
            if (self.configuration.volume_driver in
                    ['cinder.volume.drivers.lvm.LVMISCSIDriver',
                     'cinder.volume.drivers.lvm.ThinLVMVolumeDriver'] and
                    self.configuration.iscsi_helper == 'tgtadm'):
                properties['target_lun'] = 1
            else:
                properties['target_lun'] = 0

        properties['volume_id'] = volume['id']

        auth = volume['provider_auth']
        if auth:
            (auth_method, auth_username, auth_secret) = auth.split()

            properties['auth_method'] = auth_method
            properties['auth_username'] = auth_username
            properties['auth_password'] = auth_secret

        geometry = volume.get('provider_geometry', None)
        if geometry:
            (physical_block_size, logical_block_size) = geometry.split()
            properties['physical_block_size'] = physical_block_size
            properties['logical_block_size'] = logical_block_size

        encryption_key_id = volume.get('encryption_key_id', None)
        properties['encrypted'] = encryption_key_id is not None

        return properties

    def ensure_export(self, volume, volume_path=None):
        raise NotImplementedError()

    def create_export(self, context, volume):
        raise NotImplementedError()

    def remove_export(self, context, volume):
        raise NotImplementedError()

    def attach_volume(self, context,
                      volume, instance_uuid,
                      host_name, mountpoint):
        raise NotImplementedError()

    def terminate_connection(volume, **kwargs):
        raise NotImplementedError()

    def detach_volume(self, context, volume):
        self._init_connection_properties(volume)
        iscsi_properties = self._get_iscsi_properties(volume)

    def initialize_connection(self, volume, **kwargs):
        """Initializes the connection and returns connection info.

        The iscsi driver returns a driver_volume_type of 'iscsi'.
        The format of the driver data is defined in _get_iscsi_properties.
        Example return value::

            {
                'driver_volume_type': 'iscsi'
                'data': {
                    'target_discovered': True,
                    'target_iqn': 'iqn.2010-10.org.openstack:volume-00000001',
                    'target_portal': '127.0.0.0.1:3260',
                    'volume_id': 1,
                    'access_mode': 'rw'
                }
            }

        """

        # LIO is the only one that needs/implements this currently
        self._add_iqns_to_acl(volume)
        iscsi_properties = self._get_iscsi_properties(volume)
        return {
            'driver_volume_type': 'iscsi',
            'data': iscsi_properties
        }

    def validate_connector(self):
        # BOOKMARK:  api passes in connector which is initiator info
        # consider renaming this stuff from connector --> transport | target
        pass
