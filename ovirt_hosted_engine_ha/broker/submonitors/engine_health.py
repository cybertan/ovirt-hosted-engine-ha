#
# ovirt-hosted-engine-ha -- ovirt hosted engine high availability
# Copyright (C) 2013 Red Hat, Inc.
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
#

import logging
import subprocess

from ovirt_hosted_engine_ha.broker import constants
from ovirt_hosted_engine_ha.broker import submonitor_base
from ovirt_hosted_engine_ha.lib import exceptions as exceptions
from ovirt_hosted_engine_ha.lib import log_filter
from ovirt_hosted_engine_ha.lib import util as util
from ovirt_hosted_engine_ha.lib import vds_client as vdsc


def register():
    return "engine-health"


class Submonitor(submonitor_base.SubmonitorBase):
    def setup(self, options):
        self._log = logging.getLogger("EngineHealth")
        self._log.addFilter(log_filter.IntermittentFilter())

        self._address = options.get('address')
        self._use_ssl = util.to_bool(options.get('use_ssl'))
        self._vm_uuid = options.get('vm_uuid')
        if (self._address is None
                or self._use_ssl is None
                or self._vm_uuid is None):
            raise Exception("engine-health requires"
                            " address, use_ssl, and vm_uuid")
        self._log.debug("address=%s, use_ssl=%r, vm_uuid=%s",
                        self._address, self._use_ssl, self._vm_uuid)

    def action(self, options):
        # First, see if vdsm tells us it's up
        try:
            stats = vdsc.run_vds_client_cmd(self._address, self._use_ssl,
                                            'getVmStats', self._vm_uuid)
        except Exception as e:
            if isinstance(e, exceptions.DetailedError) \
                    and e.detail == "Virtual machine does not exist":
                # Not on this host
                self._log.info("VM not on this host",
                               extra=log_filter.lf_args('status', 60))
                self.update_result('vm-down')
                return
            else:
                self._log.error("Failed to getVmStats: %s", str(e))
                self.update_result(None)
                return
        vm_status = stats['statsList'][0]['status'].lower()
        if vm_status in ('powering up',
                         'powering down',
                         'waitforlaunch',
                         'migration source',
                         'rebootinprogress',
                         'restoringstate',
                         'savingstate',
                         'paused'):
            self._log.info("VM status: %s", vm_status,
                           extra=log_filter.lf_args('status', 60))
            self.update_result('vm-up bad-health-status')
            return
        if vm_status not in ('up', 'running'):
            self._log.info("VM not running on this host, status %s", vm_status,
                           extra=log_filter.lf_args('status', 60))
            self.update_result('vm-down')
            return

        # VM is up, let's see if engine is up by polling health status page
        p = subprocess.Popen([constants.HOSTED_ENGINE_BINARY,
                              '--check-liveliness'],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output = p.communicate()
        if p.returncode == 0:
            self._log.info("VM is up on this host with healthy engine",
                           extra=log_filter.lf_args('status', 60))
            self.update_result("vm-up good-health-status")
            return
        self._log.warning("bad health status: %s", output[0])
        self.update_result("vm-up bad-health-status")
        # FIXME remote db down status
