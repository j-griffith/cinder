
class ConnectorDriver(object):
    VERSION = 0.1

    def __init__(*args, **kwargs):
        pass

    def ensure_export(self, volume, volume_path=None):
        pass

    def create_export(self, context, volume):
        pass

    def remove_export(self, context, volume):
        pass

    def attach_volume(self, context, volume, instance_uuid, host_name, mountpoint):
        pass

    def detach_volume(self, context, volume):
        pass

    def initialize_connection(self, volume, **kwargs):
        pass

    def terminate_connection(volume, **kwargs):
        pass
