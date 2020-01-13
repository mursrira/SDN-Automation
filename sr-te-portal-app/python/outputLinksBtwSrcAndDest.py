from ncs.application import Application
from helpers import Helpers
from com.cisco.wae.opm.action import OpmActionBase
from com.cisco.wae.opm.network import open_plan
from tePortalLauncher import TePortalLauncher
from lspDetailsCache import LspDetailsCache
import threading
import ConfigParser
import time
import subprocess
from helpers import Helpers

# ---------------------------------------------
# COMPONENT THREAD THAT WILL BE STARTED BY WAE.
# ---------------------------------------------


class OutputLinks(Application):

	def setup(self):
		self.log.info('Fetch-Links service starting..')
		self.register_action('output-links-btw-src-and-dest-action-point',OutputLinksCongestionAction, [])
		self.log.info('Fetch-Links service started')

	def teardown(self):
		self.log.info('Fetch-Links service stopped')


class OutputLinksCongestionAction(OpmActionBase):

  config = ConfigParser.RawConfigParser()

  def run(self, net_name, input, output):
		self.update_start_status()
		# Reading configuration file for config params at runtime
		self.config.read(TePortalLauncher.portal_config_file)
		# Refreshing LSP Details from UOP
		LspDetailsCache.getInstance(self.log).refreshLSPDetailsFromUOP()

		self.nw_source = 'WMD'
		self.log.info("Got request to publish interfaces between source and destination")
		start = time.time()
		self.get_interfaces_btw_src_and_dest(output, input.source_node, input.destination_node)
		EndTime = time.time()
		self.log.debug("Finished Publishing all interfaces between source and destination nodes")


  def get_interfaces_btw_src_and_dest(self, output, srcNode,destNode):
		# planFile = self.config.get('WAEPortal', 'PlanFileWithDelaynResBW')
		#self.planFile = '/opt/others/plan-files/etisalat-xtc-dare_sep_3.pln'
		#self.planFile = '/opt/others/plan-files/etisalat-xtc-dare_delay_11.pln'

		#with open_plan(self.planFile) as self.network:

        my_helper = Helpers(self.log)
        network = my_helper.read_network()
        ifaces = network.model.interfaces

        for iface  in ifaces:

            if srcNode == iface.node.name and destNode == iface.opposite_interface.node.name:
                obj = output.output_interfaces_list.create()
                obj.capacity = iface.simulated_capacity
                obj.interface_name = iface.name



