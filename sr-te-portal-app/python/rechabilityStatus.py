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


class RechabilityStatus(Application):

	def setup(self):
		self.log.info('Checking WAE Rechability service starting..')
		self.register_action('rechability-status-action-point',RechabilityStatusAction, [])
		self.log.info('Checking WAE Rechability service started')

	def teardown(self):
		self.log.info('Checking WAE Rechability service stopped')


class RechabilityStatusAction(OpmActionBase):

  config = ConfigParser.RawConfigParser()

  def run(self, net_name, input, output):

	  	start = time.time()
		self.update_start_status()
		# Reading configuration file for config params at runtime
		self.config.read(TePortalLauncher.portal_config_file)
		self.log.info('Started Checking whether WAE WMD Rechability Status')

		my_helper = Helpers(self.log)

		try:
			network = my_helper.read_network()
			if network.model :
				output.wmd_status = True
			else:
				output.wmd_status = False
		except:
			output.wmd_status = False
			raise ValueError('WMD Process is Down')

		self.log.debug("Finished Checking whether WAE WMD Rechability Status")
		EndTime = time.time()





