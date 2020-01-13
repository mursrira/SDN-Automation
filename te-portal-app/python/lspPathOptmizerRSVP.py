from ncs.application import Application
from com.cisco.wae.opm.action import OpmActionBase
from com.cisco.wae.opm.network import open_plan
from tePortalLauncher import TePortalLauncher
from contextlib import contextmanager
import com.cisco.wae.design
import ConfigParser
import time

# ---------------------------------------------
# COMPONENT THREAD THAT WILL BE STARTED BY WAE.
# ---------------------------------------------

class LspPathOptmizerRSVP(Application):

	def setup(self):
		self.log.info('lsp-optm-rsvp service starting..')

		# The class takes care of creating a daemon (related to the
		# service/action point).
		self.register_action('lsp-optm-rsvp-action-point',
								LspPathOptmizerRSVPAction, [])

		# When this setup method is finished, all registrations are
		# considered done and the application is 'started'.
		self.log.info('lsp-optm-rsvp service started')

	def teardown(self):
		# When the application is finished, this teardown method will
		# be called.
		self.log.info('lsp-optm-rsvp service stopped')


class LspPathOptmizerRSVPAction(OpmActionBase):
   
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

		#Reading configuration file for config params at runtime
		self.config.read(TePortalLauncher.portal_config_file)
		self.nw_source = self.config.get('WAEServer', 'NetworkModelSource')

		self.log.info("Got Path Optimization request for Tunnel "+input.lspSrcNode+":"+input.lspName+" , Requested paths-"+str(input.pathCount)+", Considering shutdown of current path -"+str(input.shutdown)+", autoRoute-"+str(input.autoRoute))

		start = time.time()

		network = self.read_network()
		planReadTime = time.time()
		self.log.info("Network model opened in ",(planReadTime - start)," seconds")

		# Exclude inter-continental expensive circuits and update Reservable BW of rest interfaces
		self.log.info("Excluding Trans continental links from optimization process")
		#exclusionLinks = self.getLinkExclusionList()
		exclusionLinks = self.getLinkExclusionListFromInput(input.excludeCircuits)
		for circuit in network.model.circuits:
			#Todo read file n exclude
			exlLink = circuit.key.node_a+":"+circuit.key.interface_a+"::"+circuit.key.node_b+":"+circuit.key.interface_b
			self.log.debug('Checking Cicuit for Exclustion: ',circuit.key)
			if exlLink in exclusionLinks:
				self.log.debug('Excluding Cicuit: ',circuit.key)
				circuit.active = False

		ExclLinkTime = time.time()
		self.log.info("Trans continental link exclusion took ",ExclLinkTime - planReadTime, " seconds")

		self.log.info("Starting RSVP-TE Optimization process")
		lsp = network.model.lsps[{'source': input.lspSrcNode, 'name':input.lspName}]


		if lsp.destination is None:
			errMsg = "Optimization Not Possible: Tunnel(%s:%s) destination device is not yet discovered."%(input.lspSrcNode,input.lspName)
			self.log.error(errMsg)
			raise ValueError(errMsg)

		myLsps = []
		myLspKeys = []
		disjointGrpName = str(long(time.time()))
		self.log.info(disjointGrpName)
		if(input.shutdown == True):
			maxCount = input.pathCount
			network.model.lsps.remove(lsp)
			self.log.debug("Removed LSP")
		else:
			lsp.disjoint_group = disjointGrpName
			myLsps.append(lsp)
			myLspKeys.append(lsp.rpc_key)
			maxCount = input.pathCount


		for count in range(0,maxCount):
			self.log.debug("Adding LSP:",str(count))
			newLsp = network.model.lsps.append({
						'source': input.lspSrcNode,
						'name': input.lspName+'000'+str(count),
						'destination': lsp.destination.name,
						'lsp_type':'rsvp'
						})
			self.log.debug("Added LSP:", str(count))
			newLsp.disjoint_group = disjointGrpName
			myLsps.append(newLsp)
			myLspKeys.append(newLsp.rpc_key)
		self.log.info('For optimization my LSP Keys are ', myLspKeys)

		# Now start optimizing them
		serv = network.service_connection.rpc_service_connection
		toolMgr = serv.getToolManager()
		rsvpOptmizer = toolMgr.newRSVPTEOptimizer()
		options = com.cisco.wae.design.tools.RSVPTEOptimizerOptions(
				optLSPs = myLspKeys,
				initLSPGroups = True,
				initLSPBWReq = com.cisco.wae.design.tools.RSVPTEOptLSPBWReqType.RSVP_TE_OPT_LSP_BW_TRAFF_MEAS,
				initIntBWBound =  com.cisco.wae.design.tools.RSVPTEOptInterfaceBWBoundType.RSVP_TE_OPT_INTERFACE_BW_RESV,
				initIntMetric = com.cisco.wae.design.tools.RSVPTEOptInterfaceMetricType.RSVP_TE_OPT_INTERFACE_METRIC_DELAY,
				disjointPaths = 'DisjointGroups',
				disjointCircuitPriority='1')
		try:
			rsvpOptmizer.run(network.rpc_plan_network,options)
			toolMgr.removeTool(rsvpOptmizer)
		except Exception as ex:
			errMsg = "Unable to optimize:: %s"%str(ex)
			self.log.error(errMsg)
			raise ValueError(errMsg)


		optmTime = time.time()
		self.log.info("Tunnel Optimization took ",optmTime-ExclLinkTime, " seconds")


		# Now return Optimized Paths of above LSPs
		for lsp in myLsps:
			#self.log.info(lsp.source.name+"::"+lsp.name)
			if(lsp.source.name == input.lspSrcNode and lsp.name==input.lspName):
				continue
			lspPathList = lsp.ordered_lsp_paths
			pathOption = 10
			for lspPath in lspPathList:
				allPaths = output.lspPath.create()
				allPaths.pathOption = pathOption
				pathOption += 10
				#isActivePath = lspPath.named_path.active
				#allPaths.isActive = isActivePath

				hops = lspPath.named_path.hops
				hopIndex = 10
				delay = 0.0
				for hop in hops:
					remoteNode = hop.interface.node.name
					remoteIfName = hop.interface.name
					remoteIfIpaddress = hop.interface.ip_addresses[0]
					localNode = hop.interface.opposite_interface.node.name
					localIfIpaddress = hop.interface.opposite_interface.ip_addresses[0]
					localIfName = hop.interface.opposite_interface.name

					pathHops = allPaths.hop.create()
					pathHops.step = hopIndex
					pathHops.local_node = localNode
					pathHops.local_ifname = localIfName
					pathHops.local_ifipadd = localIfIpaddress

					pathHops.remote_node = remoteNode
					pathHops.remote_ifname = remoteIfName
					pathHops.remote_ifipadd = remoteIfIpaddress
					if(type(hop.interface.circuit.delay) is float):
						hop_delay = hop.interface.circuit.delay
						pathHops.latency = hop_delay
						delay = delay + hop.interface.circuit.delay
					else:
						pathHops.latency = "na"
						
					hopIndex += 10
				allPaths.latency = str(delay)
		resultPrepTime = time.time()
		self.log.info("Tunnel path result preparation took ",resultPrepTime-optmTime, " seconds")
		self.log.info("End to End Tunnel Optimization call took ",resultPrepTime-start, " seconds")
		network.remove_from_rpc()
		network.close()
		# Update opm end status - active state as False and
		# last successful run time stamp depending on output.result.
		#output.message = "Successfully Optimized Tunnel: "+ input.lspName
		#output.result = True
		#self.update_end_status(output.result)

	def getLinkExclusionList(self):
		with open(self.config.get('WAEPortal','ExclTransLinksFile')) as f:
			return f.read().splitlines()
			
	def getLinkExclusionListFromInput(self, excludeCircuits):
		excl_circuits = []
		for crt in excludeCircuits:
			excl_circuits.append(crt.SrcNode+":"+crt.SrcInterface+"::"+crt.DestNode+":"+crt.DestInterface)
			excl_circuits.append(crt.DestNode+":"+crt.DestInterface+"::"+crt.SrcNode+":"+crt.SrcInterface)
		return excl_circuits
		
	def read_network(self):
		if(self.nw_source == 'PLANFILE'):
			planFile = self.config.get('WAEPortal', 'PlanFileWithDelaynResBW')
			return open_plan(planFile)
		elif(self.nw_source == 'WMD'):
			return TePortalLauncher.get_wmd_client().get_latest_network(refresh=True)

