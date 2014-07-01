# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
"""
Drivers for volumes.

"""

import time

from oslo.config import cfg

from cinder import exception
from cinder.image import image_utils
from cinder.openstack.common import excutils
from cinder.openstack.common import fileutils
from cinder.openstack.common import importutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils
from cinder import utils
from cinder.volume import rpcapi as volume_rpcapi
from cinder.volume import utils as volume_utils

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.StrOpt('volume_connector',
                   default='cinder.volume.connectors.iscsi.ISCSIConnector',
                   help='Driver to use for volume connector'),
    cfg.IntOpt('num_shell_tries',
               default=3,
               help='Number of times to attempt to run flakey shell commands'),
    cfg.IntOpt('reserved_percentage',
               default=0,
               help='The percentage of backend capacity is reserved'),
    cfg.IntOpt('iscsi_num_targets',
               default=100,
               help='The maximum number of iSCSI target IDs per host'),
    cfg.StrOpt('iscsi_target_prefix',
               default='iqn.2010-10.org.openstack:',
               help='Prefix for iSCSI volumes'),
    cfg.StrOpt('iscsi_ip_address',
               default='$my_ip',
               help='The IP address that the iSCSI daemon is listening on'),
    cfg.IntOpt('iscsi_port',
               default=3260,
               help='The port that the iSCSI daemon is listening on'),
    cfg.IntOpt('num_volume_device_scan_tries',
               deprecated_name='num_iscsi_scan_tries',
               default=3,
               help='The maximum number of times to rescan targets'
                    ' to find volume'),
    cfg.StrOpt('volume_backend_name',
               default=None,
               help='The backend name for a given driver implementation'),
    cfg.BoolOpt('use_multipath_for_image_xfer',
                default=False,
                help='Do we attach/detach volumes in cinder using multipath '
                     'for volume to image and image to volume transfers?'),
    cfg.StrOpt('volume_clear',
               default='zero',
               help='Method used to wipe old voumes (valid options are: '
                    'none, zero, shred)'),
    cfg.IntOpt('volume_clear_size',
               default=0,
               help='Size in MiB to wipe at start of old volumes. 0 => all'),
    cfg.StrOpt('volume_clear_ionice',
               default=None,
               help='The flag to pass to ionice to alter the i/o priority '
                    'of the process used to zero a volume after deletion, '
                    'for example "-c3" for idle only priority.'),
    cfg.StrOpt('iscsi_helper',
               default='tgtadm',
               help='iSCSI target user-land tool to use'),
    cfg.StrOpt('volumes_dir',
               default='$state_path/volumes',
               help='Volume configuration file storage '
               'directory'),
    cfg.StrOpt('iet_conf',
               default='/etc/iet/ietd.conf',
               help='IET configuration file'),
    cfg.StrOpt('lio_initiator_iqns',
               default='',
               help=('Comma-separated list of initiator IQNs '
                     'allowed to connect to the '
                     'iSCSI target. (From Nova compute nodes.)')),
    cfg.StrOpt('iscsi_iotype',
               default='fileio',
               help=('Sets the behavior of the iSCSI target '
                     'to either perform blockio or fileio '
                     'optionally, auto can be set and Cinder '
                     'will autodetect type of backing device')),
    cfg.StrOpt('volume_dd_blocksize',
               default='1M',
               help='The default block size used when copying/clearing '
                    'volumes'),
]

# for backward compatibility
iser_opts = [
    cfg.IntOpt('num_iser_scan_tries',
               default=3,
               help='The maximum number of times to rescan iSER target'
                    'to find volume'),
    cfg.IntOpt('iser_num_targets',
               default=100,
               help='The maximum number of iSER target IDs per host'),
    cfg.StrOpt('iser_target_prefix',
               default='iqn.2010-10.org.iser.openstack:',
               help='Prefix for iSER volumes'),
    cfg.StrOpt('iser_ip_address',
               default='$my_ip',
               help='The IP address that the iSER daemon is listening on'),
    cfg.IntOpt('iser_port',
               default=3260,
               help='The port that the iSER daemon is listening on'),
    cfg.StrOpt('iser_helper',
               default='tgtadm',
               help='The name of the iSER target user-land tool to use'),
]

CONF = cfg.CONF
CONF.register_opts(volume_opts)
CONF.register_opts(iser_opts)


class VolumeDriver(object):
    """Executes commands relating to Volumes."""

    VERSION = "N/A"

    def __init__(self, execute=utils.execute, *args, **kwargs):
        # NOTE(vish): db is set by Manager
        self.db = kwargs.get('db')
        self.host = kwargs.get('host')
        self.configuration = kwargs.get('configuration', None)
        if self.configuration:
            self.configuration.append_config_values(volume_opts)

        self.connector = importutils.import_object(
            self.configuration.get('volume_connector'),
            configuration=self.configuration)

        self.set_execute(execute)
        self._stats = {}

        # set True by manager after successful check_for_setup
        self._initialized = False

    def set_execute(self, execute):
        self._execute = execute

    def set_initialized(self):
        self._initialized = True

    @property
    def initialized(self):
        return self._initialized

    def get_version(self):
        """Get the current version of this driver."""
        return self.VERSION

    def _is_non_recoverable(self, err, non_recoverable_list):
        for item in non_recoverable_list:
            if item in err:
                return True

        return False

    def _try_execute(self, *command, **kwargs):
        # NOTE(vish): Volume commands can partially fail due to timing, but
        #             running them a second time on failure will usually
        #             recover nicely.

        non_recoverable = kwargs.pop('no_retry_list', [])

        tries = 0
        while True:
            try:
                self._execute(*command, **kwargs)
                return True
            except processutils.ProcessExecutionError as ex:
                tries = tries + 1

                if tries >= self.configuration.num_shell_tries or\
                        self._is_non_recoverable(ex.stderr, non_recoverable):
                    raise

                LOG.exception(_("Recovering from a failed execute.  "
                                "Try number %s"), tries)
                time.sleep(tries ** 2)

    def check_for_setup_error(self):
        raise NotImplementedError()

    def create_volume(self, volume):
        """Creates a volume. Can optionally return a Dictionary of
        changes to the volume object to be persisted.
        """
        raise NotImplementedError()

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        raise NotImplementedError()

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        raise NotImplementedError()

    def delete_volume(self, volume):
        """Deletes a volume."""
        raise NotImplementedError()

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        raise NotImplementedError()

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        raise NotImplementedError()

    def local_path(self, volume):
        raise NotImplementedError()

    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a volume."""
        raise NotImplementedError()

    def create_export(self, context, volume):
        """Exports the volume. Can optionally return a Dictionary of changes
        to the volume object to be persisted.
        """
        raise NotImplementedError()

    def remove_export(self, context, volume):
        """Removes an export for a volume."""
        raise NotImplementedError()

    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""
        raise NotImplementedError()

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector"""
        raise NotImplementedError()

    def attach_volume(self, context, volume, instance_uuid, host_name,
                      mountpoint):
        """Callback for volume attached to instance or host."""
        pass

    def detach_volume(self, context, volume):
        """Callback for volume detached."""
        pass

    def get_volume_stats(self, refresh=False):
        """Return the current state of the volume service. If 'refresh' is
           True, run the update first.
        """
        return None

    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        pass

    def validate_connector(self, connector):
        """Fail if connector doesn't contain all the data needed by driver."""
        pass

    @staticmethod
    def validate_connector_has_setting(connector, setting):
        pass

    def copy_volume_data(self, context, src_vol, dest_vol, remote=None):
        """Copy data from src_vol to dest_vol."""
        LOG.debug(_('copy_data_between_volumes %(src)s -> %(dest)s.')
                  % {'src': src_vol['name'], 'dest': dest_vol['name']})

        properties = utils.brick_get_connector_properties()
        dest_remote = True if remote in ['dest', 'both'] else False
        dest_orig_status = dest_vol['status']
        try:
            dest_attach_info = self._attach_volume(context,
                                                   dest_vol,
                                                   properties,
                                                   remote=dest_remote)
        except Exception:
            with excutils.save_and_reraise_exception():
                msg = _("Failed to attach volume %(vol)s")
                LOG.error(msg % {'vol': dest_vol['id']})
                self.db.volume_update(context, dest_vol['id'],
                                      {'status': dest_orig_status})

        src_remote = True if remote in ['src', 'both'] else False
        src_orig_status = src_vol['status']
        try:
            src_attach_info = self._attach_volume(context,
                                                  src_vol,
                                                  properties,
                                                  remote=src_remote)
        except Exception:
            with excutils.save_and_reraise_exception():
                msg = _("Failed to attach volume %(vol)s")
                LOG.error(msg % {'vol': src_vol['id']})
                self.db.volume_update(context, src_vol['id'],
                                      {'status': src_orig_status})
                self._detach_volume(context, dest_attach_info, dest_vol,
                                    properties, force=True, remote=dest_remote)

        copy_error = True
        try:
            size_in_mb = int(src_vol['size']) * 1024    # vol size is in GB
            volume_utils.copy_volume(
                src_attach_info['device']['path'],
                dest_attach_info['device']['path'],
                size_in_mb,
                self.configuration.volume_dd_blocksize)
            copy_error = False
        except Exception:
            with excutils.save_and_reraise_exception():
                msg = _("Failed to copy volume %(src)s to %(dest)s.")
                LOG.error(msg % {'src': src_vol['id'], 'dest': dest_vol['id']})
        finally:
            self._detach_volume(context, dest_attach_info, dest_vol,
                                properties, force=copy_error,
                                remote=dest_remote)
            self._detach_volume(context, src_attach_info, src_vol,
                                properties, force=copy_error,
                                remote=src_remote)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""
        LOG.debug(_('copy_image_to_volume %s.') % volume['name'])

        properties = utils.brick_get_connector_properties()
        attach_info = self._attach_volume(context, volume, properties)

        try:
            image_utils.fetch_to_raw(context,
                                     image_service,
                                     image_id,
                                     attach_info['device']['path'],
                                     self.configuration.volume_dd_blocksize,
                                     size=volume['size'])
        finally:
            self._detach_volume(context, attach_info, volume, properties)

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image."""
        LOG.debug(_('copy_volume_to_image %s.') % volume['name'])

        properties = utils.brick_get_connector_properties()
        attach_info = self._attach_volume(context, volume, properties)

        try:
            image_utils.upload_volume(context,
                                      image_service,
                                      image_meta,
                                      attach_info['device']['path'])
        finally:
            self._detach_volume(context, attach_info, volume, properties)

    def _attach_volume(self, context, volume, properties, remote=False):
        """Attach the volume."""
        if remote:
            # Call remote manager's initialize_connection which includes
            # driver's create_export and initialize_connection
            rpcapi = volume_rpcapi.VolumeAPI()
            conn = rpcapi.initialize_connection(context, volume, properties)
        else:
            # Call local driver's create_export and initialize_connection.
            # NOTE(avishay) This is copied from the manager's code - need to
            # clean this up in the future.
            model_update = None
            try:
                LOG.debug(_("Volume %s: creating export"), volume['id'])
                model_update = self.create_export(context, volume)
                if model_update:
                    volume = self.db.volume_update(context, volume['id'],
                                                   model_update)
            except exception.CinderException as ex:
                if model_update:
                    LOG.exception(_("Failed updating model of volume "
                                    "%(volume_id)s with driver provided model "
                                    "%(model)s") %
                                  {'volume_id': volume['id'],
                                   'model': model_update})
                    raise exception.ExportFailure(reason=ex)

            try:
                conn = self.initialize_connection(volume, properties)
            except Exception as err:
                try:
                    err_msg = (_('Unable to fetch connection information from '
                                 'backend: %(err)s') % {'err': err})
                    LOG.error(err_msg)
                    LOG.debug("Cleaning up failed connect initialization.")
                    self.remove_export(context, volume)
                except Exception as ex:
                    ex_msg = (_('Error encountered during cleanup '
                                'of a failed attach: %(ex)s') % {'ex': ex})
                    LOG.error(err_msg)
                    raise exception.VolumeBackendAPIException(data=ex_msg)
                raise exception.VolumeBackendAPIException(data=err_msg)

        # Use Brick's code to do attach/detach
        use_multipath = self.configuration.use_multipath_for_image_xfer
        device_scan_attempts = self.configuration.num_volume_device_scan_tries
        protocol = conn['driver_volume_type']
        connector = utils.brick_get_connector(protocol,
                                              use_multipath=use_multipath,
                                              device_scan_attempts=
                                              device_scan_attempts,
                                              conn=conn)
        device = connector.connect_volume(conn['data'])
        host_device = device['path']

        if not connector.check_valid_device(host_device):
            raise exception.DeviceUnavailable(path=host_device,
                                              reason=(_("Unable to access "
                                                        "the backend storage "
                                                        "via the path "
                                                        "%(path)s.") %
                                                      {'path': host_device}))
        return {'conn': conn, 'device': device, 'connector': connector}

    def _detach_volume(self, context, attach_info, volume, properties,
                       force=False, remote=False):
        """Disconnect the volume from the host."""
        # Use Brick's code to do attach/detach
        connector = attach_info['connector']
        connector.disconnect_volume(attach_info['conn']['data'],
                                    attach_info['device'])

        if remote:
            # Call remote manager's terminate_connection which includes
            # driver's terminate_connection and remove export
            rpcapi = volume_rpcapi.VolumeAPI()
            rpcapi.terminate_connection(context, volume, properties,
                                        force=force)
        else:
            # Call local driver's terminate_connection and remove export.
            # NOTE(avishay) This is copied from the manager's code - need to
            # clean this up in the future.
            try:
                self.terminate_connection(volume, properties, force=force)
            except Exception as err:
                err_msg = (_('Unable to terminate volume connection: %(err)s')
                           % {'err': err})
                LOG.error(err_msg)
                raise exception.VolumeBackendAPIException(data=err_msg)

            try:
                LOG.debug(_("volume %s: removing export"), volume['id'])
                self.remove_export(context, volume)
            except Exception as ex:
                LOG.exception(_("Error detaching volume %(volume)s, "
                                "due to remove export failure."),
                              {"volume": volume['id']})
                raise exception.RemoveExportException(volume=volume['id'],
                                                      reason=ex)

    def clone_image(self, volume, image_location, image_id, image_meta):
        """Create a volume efficiently from an existing image.

        image_location is a string whose format depends on the
        image service backend in use. The driver should use it
        to determine whether cloning is possible.

        image_id is a string which represents id of the image.
        It can be used by the driver to introspect internal
        stores or registry to do an efficient image clone.

        image_meta is a dictionary that includes 'disk_format' (e.g.
        raw, qcow2) and other image attributes that allow drivers to
        decide whether they can clone the image without first requiring
        conversion.

        Returns a dict of volume properties eg. provider_location,
        boolean indicating whether cloning occurred
        """
        return None, False

    def backup_volume(self, context, backup, backup_service):
        """Create a new backup from an existing volume."""
        volume = self.db.volume_get(context, backup['volume_id'])

        LOG.debug(_('Creating a new backup for volume %s.') %
                  volume['name'])

        properties = utils.brick_get_connector_properties()
        attach_info = self._attach_volume(context, volume, properties)

        try:
            volume_path = attach_info['device']['path']
            with utils.temporary_chown(volume_path):
                with fileutils.file_open(volume_path) as volume_file:
                    backup_service.backup(backup, volume_file)

        finally:
            self._detach_volume(context, attach_info, volume, properties)

    def restore_backup(self, context, backup, volume, backup_service):
        """Restore an existing backup to a new or existing volume."""
        LOG.debug(_('Restoring backup %(backup)s to '
                    'volume %(volume)s.') %
                  {'backup': backup['id'],
                   'volume': volume['name']})

        properties = utils.brick_get_connector_properties()
        attach_info = self._attach_volume(context, volume, properties)

        try:
            volume_path = attach_info['device']['path']
            with utils.temporary_chown(volume_path):
                with fileutils.file_open(volume_path, 'wb') as volume_file:
                    backup_service.restore(backup, volume['id'], volume_file)

        finally:
            self._detach_volume(context, attach_info, volume, properties)

    def clear_download(self, context, volume):
        """Clean up after an interrupted image copy."""
        pass

    def extend_volume(self, volume, new_size):
        msg = _("Extend volume not implemented")
        raise NotImplementedError(msg)

    def migrate_volume(self, context, volume, host):
        """Migrate the volume to the specified host.

        Returns a boolean indicating whether the migration occurred, as well as
        model_update.

        :param ctxt: Context
        :param volume: A dictionary describing the volume to migrate
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        """
        return (False, None)

    def retype(self, context, volume, new_type, diff, host):
        """Convert the volume to be of the new type.

        Returns a boolean indicating whether the retype occurred.

        :param ctxt: Context
        :param volume: A dictionary describing the volume to migrate
        :param new_type: A dictionary describing the volume type to convert to
        :param diff: A dictionary with the difference between the two types
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        """
        return False

    def accept_transfer(self, context, volume, new_user, new_project):
        """Accept the transfer of a volume for a new user/project."""
        pass

    def manage_existing(self, volume, existing_ref):
        """Brings an existing backend storage object under Cinder management.

        existing_ref is passed straight through from the API request's
        manage_existing_ref value, and it is up to the driver how this should
        be interpreted.  It should be sufficient to identify a storage object
        that the driver should somehow associate with the newly-created cinder
        volume structure.

        There are two ways to do this:

        1. Rename the backend storage object so that it matches the,
           volume['name'] which is how drivers traditionally map between a
           cinder volume and the associated backend storage object.

        2. Place some metadata on the volume, or somewhere in the backend, that
           allows other driver requests (e.g. delete, clone, attach, detach...)
           to locate the backend storage object when required.

        If the existing_ref doesn't make sense, or doesn't refer to an existing
        backend storage object, raise a ManageExistingInvalidReference
        exception.

        The volume may have a volume_type, and the driver can inspect that and
        compare against the properties of the referenced backend storage
        object.  If they are incompatible, raise a
        ManageExistingVolumeTypeMismatch, specifying a reason for the failure.
        """
        msg = _("Manage existing volume not implemented.")
        raise NotImplementedError(msg)

    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of volume to be managed by manage_existing.

        When calculating the size, round up to the next GB.
        """
        msg = _("Manage existing volume not implemented.")
        raise NotImplementedError(msg)

    def unmanage(self, volume):
        """Removes the specified volume from Cinder management.

        Does not delete the underlying backend storage object.

        For most drivers, this will not need to do anything.  However, some
        drivers might use this call as an opportunity to clean up any
        Cinder-specific configuration that they have associated with the
        backend storage object.
        """
        pass
