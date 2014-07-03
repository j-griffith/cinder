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


class Connector(object):
    """Connector object for block storage devices.

    Base class for connector object, where connector
    is data transport mechanism specific calls.  This
    includes things like create targets, attach, detach
    etc.

    Base class here does nothing more than set an executor and db as
    well as force implementation of required methods.

    """

    def __init__(self, *args, **kwargs):
        self.db = kwargs.get('db')
        self.configuration = kwargs.safe_get('configuration')
        self._execute = kwargs.safe_get('executor')

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
