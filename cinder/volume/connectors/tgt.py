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


import os

from oslo.config import cfg

from cinder import exception
from cinder.image import image_utils
from cinder.openstack.common import excutils
from cinder.openstack.common import fileutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils as putils
from cinder import utils
from cinder.volume.connector import iscsi

LOG = logging.getLogger(__name__)


class TgtAdm(iscsi.iSCSIConnector):
    """Connector object for block storage devices.

    Base class for connector object, where connector
    is data transport mechanism specific calls.  This
    includes things like create targets, attach, detach
    etc.
    """
    VOLUME_CONF = """
                <target %s>
                    backing-store %s
                    lld iscsi
                </target>
                  """
    VOLUME_CONF_WITH_CHAP_AUTH = """
                                <target %s>
                                    backing-store %s
                                    lld iscsi
                                    %s
                                </target>
                                 """

    def __init__(self, *args, **kwargs):
        super(TgtAdm, self).__init__(*args, **kwargs)

    def _create_iscsi_target(self, name, tid, lun, path,
                             chap_auth=None, **kwargs):
        # Note(jdg) tid and lun aren't used by TgtAdm but remain for
        # compatibility

        fileutils.ensure_tree(self.volumes_dir)

        vol_id = name.split(':')[1]
        if chap_auth is None:
            volume_conf = self.VOLUME_CONF % (name, path)
        else:
            volume_conf = self.VOLUME_CONF_WITH_CHAP_AUTH % (name,
                                                             path, chap_auth)

        LOG.info(_('Creating iscsi_target for: %s') % vol_id)
        volumes_dir = self.volumes_dir
        volume_path = os.path.join(volumes_dir, vol_id)

        f = open(volume_path, 'w+')
        f.write(volume_conf)
        f.close()
        LOG.debug(_('Created volume path %(vp)s,\n'
                    'content: %(vc)s')
                  % {'vp': volume_path, 'vc': volume_conf})

        old_persist_file = None
        old_name = kwargs.get('old_name', None)
        if old_name is not None:
            old_persist_file = os.path.join(volumes_dir, old_name)

        try:
            # with the persistent tgts we create them
            # by creating the entry in the persist file
            # and then doing an update to get the target
            # created.
            (out, err) = self._execute('tgt-admin', '--update', name,
                                       run_as_root=True)
            LOG.debug("StdOut from tgt-admin --update: %s", out)
            LOG.debug("StdErr from tgt-admin --update: %s", err)

            # Grab targets list for debug
            # Consider adding a check for lun 0 and 1 for tgtadm
            # before considering this as valid
            (out, err) = self._execute('tgtadm',
                                       '--lld',
                                       'iscsi',
                                       '--op',
                                       'show',
                                       '--mode',
                                       'target',
                                       run_as_root=True)
            LOG.debug("Targets after update: %s" % out)
        except putils.ProcessExecutionError as e:
            LOG.warning(_("Failed to create iscsi target for volume "
                        "id:%(vol_id)s: %(e)s")
                        % {'vol_id': vol_id, 'e': e})

            # Don't forget to remove the persistent file we created
            os.unlink(volume_path)
            raise exception.ISCSITargetCreateFailed(volume_id=vol_id)

        iqn = '%s%s' % (self.iscsi_target_prefix, vol_id)
        tid = self._get_target(iqn)
        if tid is None:
            LOG.error(_("Failed to create iscsi target for volume "
                        "id:%(vol_id)s. Please ensure your tgtd config file "
                        "contains 'include %(volumes_dir)s/*'") % {
                      'vol_id': vol_id,
                      'volumes_dir': volumes_dir, })
            raise exception.NotFound()

        # NOTE(jdg): Sometimes we have some issues with the backing lun
        # not being created, believe this is due to a device busy
        # or something related, so we're going to add some code
        # here that verifies the backing lun (lun 1) was created
        # and we'll try and recreate it if it's not there
        if not self._verify_backing_lun(iqn, tid):
            try:
                self._recreate_backing_lun(iqn, tid, name, path)
            except putils.ProcessExecutionError:
                os.unlink(volume_path)
                raise exception.ISCSITargetCreateFailed(volume_id=vol_id)

            # Finally check once more and if no go, fail and punt
            if not self._verify_backing_lun(iqn, tid):
                os.unlink(volume_path)
                raise exception.ISCSITargetCreateFailed(volume_id=vol_id)

        if old_persist_file is not None and os.path.exists(old_persist_file):
            os.unlink(old_persist_file)

        return tid

    def ensure_export(self, volume, volume_path=None):
        chap_auth = None
        old_name = None

        # FIXME (jdg): This appears to be broken in existing code
        # we recreate the iscsi target but we pass in None
        # for CHAP, so we just recreated without CHAP even if
        # we had it set on initial create
        self._create_iscsi_target(
            self.configuration.get('iscsi_target_prefix'),
            1, 0, volume_path,
            chap_auth, check_exit_code=False,
            old_name=old_name)

    def create_export(self, context, volume, volume_path):
        """Creates an export for a logical volume."""
        iscsi_name = "%s%s" % (self.configuration.iscsi_target_prefix,
                               volume['name'])
        iscsi_target, lun = self._get_target_and_lun(context, volume)
        chap_username = utils.generate_username()
        chap_password = utils.generate_password()
        chap_auth = self._iscsi_authentication('IncomingUser', chap_username,
                                               chap_password)
        # NOTE(jdg): For TgtAdm case iscsi_name is the ONLY param we need
        # should clean this all up at some point in the future
        tid = self.create_iscsi_target(iscsi_name,
                                       iscsi_target,
                                       0,
                                       volume_path,
                                       chap_auth)
        data = {}
        data['location'] = self._iscsi_location(
            self.configuration.iscsi_ip_address, tid, iscsi_name, lun)
        data['auth'] = self._iscsi_authentication(
            'CHAP', chap_username, chap_password)
        return data

    def remove_export(self, context, volume):
        try:
            iscsi_target = self._get_iscsi_target(context, volume['id'])
        except exception.NotFound:
            LOG.info(_("Skipping remove_export. No iscsi_target "
                       "provisioned for volume: %s"), volume['id'])
            return
        try:

            # NOTE: provider_location may be unset if the volume hasn't
            # been exported
            location = volume['provider_location'].split(' ')
            iqn = location[1]

            # ietadm show will exit with an error
            # this export has already been removed
            self.show_target(iscsi_target, iqn=iqn)

        except Exception:
            LOG.info(_("Skipping remove_export. No iscsi_target "
                       "is presently exported for volume: %s"), volume['id'])
            return

        self.remove_iscsi_target(iscsi_target, 0, volume['id'], volume['name'])

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
