from concurrent import futures
import grpc
import time
import uuid

from oslo_config import cfg
from oslo_log import log as logging

from cinder.csi.proto_files import csi_pb2
from cinder.csi.proto_files import csi_pb2_grpc
from cinder import context as cinder_context
from cinder import volume as cinder_volume

CONF = cfg.CONF
LOG = logging.getLogger(__name__)
VOLUME_API = None

_ONE_DAY_IN_SECONDS = 60 * 60 * 24


class CinderServicer(csi_pb2_grpc.ControllerServicer):
    """Implements the ControllerServicer."""

    def __init__(self):
        self.volume_api = cinder_volume.API()
        self.cctxt = cinder_context.get_admin_context()

    def CreateVolume(self, req, context):
        """CreateVolume implements csi CreateVolume."""
        volume_name = req.name
        if len(req.name) < 1:
            volume_name = str(uuid.uuid4())

        # FIXME(jdg):  Figure out sizing, should be able to just
        # use a similar pattern as above with name, but there are
        # some details around using "range" etc and the conversion
        # from bytes to GiB
        volume_size_gig = 1
        volume_type_name = req.parameters.get('type', None)
        volume_az = req.parameters.get('availability', None)
        vref = self.volume_api.create(self.cctxt,
                                      volume_size_gig,
                                      volume_name,
                                      None)

        # FIXME(jdg): This is still wrong, it doesn't serialize correctly for a grpc response, but
        # I haven't figured out what's wrong yet
        csi_create_response = csi_pb2.CreateVolumeResponse()
        csi_create_response.volume.id = vref.id
        csi_create_response.volume.capacity_bytes = 1
        return csi_create_response

    def DeleteVolume(self, req, context):
        """DeleteVolume implements csi DeleteVolume."""
        # Delete requires a Cinder Volume Object, so do a get
        # first, we're using volume_id here
        vref = self.volume_api.get(self.cctxt, req.volume_id)
        self.volume_api.delete(self.cctxt, vref)
        return csi_pb2.CreateVolumeResponse()

    def ControllerPublishVolume(self, req, context):
        pass

    def ControllerUnpublishVolume(self, req, context):
        pass

    def ValidateVolumeCapabilities(self, req, context):
        pass

    def ListVolumes(self, req, context):
        list_response = csi_pb2.ListVolumesResponse()

        # FIXME(jdg): This is a train wreck down here,
        # I can't figure out how the heck to get the
        # volume elements added to the response.entries
        c_vols = self.volume_api.get_all(self.cctxt)
        # For now we're just returning nada
        return list_response

    def GetCapacity(self, req, context):
        pass


    def ControllerGetCapabilities(self, req, context):
        pass


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    csi_pb2_grpc.add_ControllerServicer_to_server(
        CinderServicer(), server)
    server.add_insecure_port('[::]:50051')
    server.start()
    LOG.info('Serving CSI at port: %s', 50051)

    try:
        while True:
            time.sleep(_ONE_DAY_IN_SECONDS)
    except KeyboardInterrupt:
        server.stop(0)
