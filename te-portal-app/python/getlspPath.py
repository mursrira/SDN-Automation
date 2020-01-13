from ncs.application import Application
from com.cisco.wae.opm.action import OpmActionBase
from com.cisco.wae.opm.network import open_plan
from contextlib import contextmanager
from tePortalLauncher import TePortalLauncher
import threading
import com.cisco.wae.design.model
import com.cisco.wae.design.model.net
import ConfigParser
import time

# ---------------------------------------------
# COMPONENT THREAD THAT WILL BE STARTED BY WAE.
# ---------------------------------------------

class GetLspPath(Application):

	def setup(self):
		self.log.info('lsp-get-path service starting..')

		# The class takes care of creating a daemon (related to the
		# service/action point).
		self.register_action('lsp-get-path-action-point',
								GetLspPathAction, [])

		# When this setup method is finished, all registrations are
		# considered done and the application is 'started'.
		self.log.info('lsp-get-path service started')

	def teardown(self):
		# When the application is finished, this teardown method will
		# be called.
		self.log.info('lsp-get-path service stopped')


class GetLspPathAction(OpmActionBase):

	config = ConfigParser.RawConfigParser()

	def run(self, net_name, input, output):
		'''
			This run method provides the WAE network name that this OPM package
			is attached to, the input object with all of the user selected
			options as attributes and an output object to populate with output
			from the package, based on the Yang module defined.
		'''

		# Update opm start status - active state as True and
		# last run time stamp.
		self.update_start_status()

		self.log.info("Got request for current path of Tunnel " + input.lspSrcNode + ":" + input.lspName)
		self.config.read(TePortalLauncher.portal_config_file)
		self.nw_source = self.config.get('WAEServer', 'NetworkModelSource')

		start = time.time()
		network =  self.read_network()
		planReadTime = time.time()
		self.log.info("Network model opened in ", (planReadTime - start), " seconds")

		try:
			lsp = network.model.lsps[{'source': input.lspSrcNode, 'name': input.lspName}]
		except Exception as e:
			raise Exception(
				"Unable to find Tunnel with details source: " + input.lspSrcNode + " and Name: " + input.lspName)
		lspTime = time.time()
		self.log.info("Tunnel identified in ", (lspTime - planReadTime), " seconds")

		lspPathList = lsp.ordered_lsp_paths
		for lspPath in lspPathList:
			self.parse_lsp_path(lspPath.actual_path, True, output)
			self.parse_lsp_path(lspPath, False, output)
		if(lsp.actual_path is not None):
			self.parse_lsp_path(lsp.actual_path, True, output)
		'''
		try:
			self.parse_lsp_path(lsp.lsp_paths.lsp_path.actual_path, True, output)
		except AttributeError:
			self.log.debug("Tunnel has no actual path")
		'''		
		pathTime = time.time()
		self.log.info("Tunnel Path processed ",(pathTime - lspTime)," seconds")
		self.log.info("Total time taken in getting Tunnel path is ",(pathTime - start)," seconds")
		network.remove_from_rpc()
		network.close()
		
	def parse_lsp_path(self, lspPath, is_actual_path, output):
		if lspPath is None:
			self.log.debug("Tunnel has no actual path..")
			return
		allPaths = output.lspPath.create()
		try:
			pathOption = lspPath.path_option
			allPaths.pathOption = pathOption
		except AttributeError:
                        allPaths.pathOption = 0
		allPaths.isActual = is_actual_path

		if not is_actual_path:
			try:
				if(pathOption == 100):
					isActivePath = lspPath.active
				else:
					isActivePath = lspPath.named_path.active
			except AttributeError:
				isActivePath = False
			allPaths.isActive = isActivePath
			
			try:
				hops = lspPath.named_path.hops
			except AttributeError:
				hops = []
			self.log.debug("Parsing Configured paths with hop count:",len(hops))
		else:
			allPaths.isActive = True
			
			try:
				hops = lspPath.hops
			except AttributeError:
				hops = []
			self.log.debug("Parsing Actual paths with hop count:",len(hops))
		

		hopIndex = 1
		delay = 0.0
		for hop in hops:
			pathHops = allPaths.hop.create()
			#self.log.info("Parsing hop:", hop)
			try:
				remoteNode = hop.interface.node.name
			except AttributeError:
				remoteNode = '-'

			try:
				remoteIfName = hop.interface.name
			except AttributeError:
				remoteIfName = '-'

			try:
				remoteIfIpaddress = hop.interface.ip_addresses[0]
			except AttributeError:
				remoteIfIpaddress = '-'

			try:
				localNode = hop.interface.opposite_interface.node.name
			except AttributeError:
				localNode = '-'

			try:
				localIfIpaddress = hop.interface.opposite_interface.ip_addresses[0]
				if(type(hop.interface.circuit.delay) is float):
					hop_delay = hop.interface.circuit.delay
					pathHops.latency = hop_delay
					delay = delay + hop.interface.circuit.delay
				else:
					pathHops.latency = "na"
					
			except AttributeError:
				localIfIpaddress = '-'
			try:
				localIfName = hop.interface.opposite_interface.name
			except AttributeError:
				localIfName = '-'

			
			pathHops.step = hopIndex
			pathHops.local_node = localNode
			pathHops.local_ifname = localIfName
			pathHops.local_ifipadd = localIfIpaddress

			pathHops.remote_node = remoteNode
			pathHops.remote_ifname = remoteIfName
			pathHops.remote_ifipadd = remoteIfIpaddress
			
			hopIndex += 1
		allPaths.latency = str(delay)

	def read_network(self):
		if (self.nw_source == 'PLANFILE'):
			planFile = self.config.get('WAEPortal', 'PlanFileWithDelaynResBW')
			return open_plan(planFile)
		elif (self.nw_source == 'WMD'):
			return TePortalLauncher.get_wmd_client().get_latest_network(refresh=True)
