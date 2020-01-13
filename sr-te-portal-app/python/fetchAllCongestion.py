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


class FetchAllCongestion(Application):

	def setup(self):
		self.log.info('sr-fetch-congestion service starting..')
		self.register_action('sr-fetch-congestion-action-point',FetchAllCongestionAction, [])
		self.log.info('sr-fetch-congestion service started')

	def teardown(self):
		self.log.info('sr-fetch-congestion service stopped')


class FetchAllCongestionAction(OpmActionBase):

	config = ConfigParser.RawConfigParser()

	def run(self, net_name, input, output):		
		self.update_start_status()
		# Reading configuration file for config params at runtime
		self.config.read(TePortalLauncher.portal_config_file)
		# Refreshing LSP Details from UOP
		LspDetailsCache.getInstance(self.log).refreshLSPDetailsFromUOP()

		self.nw_source = 'WMD'
		self.log.info("Got request for Finding Congestion in network")
		start = time.time()
		self.get_all_congestion_wmd(output, float(input.interface_utilization),input.link_off_load_status)
		EndTime = time.time()
		self.log.info("Congestions/SLA Violations identified in ", (EndTime - start), " seconds")


	def get_all_congestion_wmd(self, output, ifaceUtilizationThreshold,linkOffLoadStatus):
		# planFile = self.config.get('WAEPortal', 'PlanFileWithDelaynResBW')
		#self.planFile = '/opt/others/plan-files/etisalat-xtc-dare_sep_3.pln'
		#self.planFile = '/opt/others/plan-files/etisalat-xtc-dare_delay_11.pln'
			
		my_helper = Helpers(self.log)
		
		#with open_plan(self.planFile) as self.network:
		network = my_helper.read_network()
		ifaces = network.model.interfaces
		lsps = network.model.lsps 

		#Filling BW Violation LSPs 
		output = my_helper.helpers_get_congestion(ifaces, output, ifaceUtilizationThreshold,[],linkOffLoadStatus,None)

		#Filling SLA Violation LSPs

		if(linkOffLoadStatus==False):
			my_helper.fillSlaViolatedLsps(lsps,output.sla_violated_lsps)



