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


class Connector(object):
    """Connector object for block storage devices.

    Base class for connector object, where connector
    is data transport mechanism specific calls.  This
    includes things like create targets, attach, detach
    etc.
    """

    def __init__(*args, **kwargs):
        raise NotImplementedError()

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

    def detach_volume(self, context, volume):
        raise NotImplementedError()

    def initialize_connection(self, volume, **kwargs):
        raise NotImplementedError()

    def terminate_connection(volume, **kwargs):
        raise NotImplementedError()
