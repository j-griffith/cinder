#!/usr/bin/env python
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

"""Starter script for Cinder CSI Service."""

import logging as python_logging
import sys

from cinder import objects

from oslo_config import cfg
from oslo_log import log as logging

# Need to register global_opts
from cinder.csi import csi_service
from cinder import rpc
from cinder import version


CONF = cfg.CONF


if __name__ == '__main__':
    objects.register_all()
    CONF(sys.argv[1:], project='cinder',
         version=version.version_string())
    logging.setup(CONF, "cinder")
    python_logging.captureWarnings(True)
    rpc.init(CONF)
    csi_service.serve()
