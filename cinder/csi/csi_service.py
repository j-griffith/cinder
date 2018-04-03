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

    def __init__(self, cinder_context):
        self.volume_api = cinder_volume.API()
        self.cctxt = cinder_context

    def Probe(self, req, context):
        response = csi_pb2_grpc.ProbeResponse()
        return response

    def GetPluginCapabilities(self, req, context):
        response = csi_pb2.GetPluginCapabilitiesResponse()
        return response

    def GetPluginInfo(self, req, context):
        response = csi_pb2.GetPluginInfoResponse()
        response.name = 'cinder-native'
        response.vendor_version = '0.3.0'
        return response


    def CreateVolume(self, req, context):
        """CreateVolume implements csi CreateVolume."""
        response = csi_pb2.CreateVolumeResponse()
        if not req.name or req.name == "":
            context.set_details("Name is required for create!")
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            return response
        volume_name = req.name
        if len(req.name) < 1:
            volume_name = str(uuid.uuid4())

        volume_size_gig = 1
        volume_type_name = req.parameters.get('type', None)
        volume_az = req.parameters.get('availability', None)
        vref = self.volume_api.create(self.cctxt,
                                      volume_size_gig,
                                      volume_name,
                                      None)

        csi_volume = csi_pb2.Volume()
        csi_volume.id = vref.id
        csi_volume.capacity_bytes = 1 * 1048576 * 1024

        # We can set this here and that's cool; but we're missing something
        # important, the serializer is expecting
        #  response.volume.attributes_entry to be set?
        # FIXME(jdg)
        csi_volume.attributes.update({"foo": "bar"})
        response.volume.CopyFrom(csi_volume)
        return response

    def DeleteVolume(self, req, context):
        """DeleteVolume implements csi DeleteVolume."""
        # Delete requires a Cinder Volume Object, so do a get
        # first, we're using volume_id here
        vref = self.volume_api.get(self.cctxt, req.volume_id)
        self.volume_api.delete(self.cctxt, vref)
        return csi_pb2.DeleteVolumeResponse()

    def ControllerPublishVolume(self, req, context):
        pass

    def ControllerUnpublishVolume(self, req, context):
        pass

    def ValidateVolumeCapabilities(self, req, context):
        pass

    def ListVolumes(self, req, context):
        list_response = csi_pb2.ListVolumesResponse()
        c_vols = self.volume_api.get_all(self.cctxt)
        for v in c_vols:
            vol = csi_pb2.Volume()
            vol.id = v.id
            vol.capacity_bytes = v.size * 1048576 * 1024

            # I can create an *entry* but I can't add it?
            entry = csi_pb2.ListVolumesResponse.Entry(volume=vol)

            # This gives us what I *think* we want, except we get multiple
            # *entries* fields, instead of a list of volumes under entries?
            # list_response
            # entries {
            # volume {
                # capacity_bytes: 1073741824
                # id: "8723a9ab-c51e-4d89-8947-e0f83bf42573"
            # }
            # }
            # entries {
            # volume {
                # capacity_bytes: 1073741824
                # id: "6d5242d8-e4e3-4283-812a-a46617e0db6e"
            # }
            # }
            list_response.entries.add(volume=vol)
        return list_response

    def GetCapacity(self, req, context):
        pass


    def ControllerGetCapabilities(self, req, context):
        pass


def serve(cinder_context):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    csi_pb2_grpc.add_ControllerServicer_to_server(
        CinderServicer(cinder_context), server)
    csi_pb2_grpc.add_IdentityServicer_to_server(
        CinderServicer(cinder_context), server)
    server.add_insecure_port('[::]:50051')
    server.start()
    LOG.info('Serving CSI at port: %s', 50051)

    try:
        while True:
            time.sleep(_ONE_DAY_IN_SECONDS)
    except KeyboardInterrupt:
        server.stop(0)
