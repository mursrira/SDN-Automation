from ncs.application import Application
from com.cisco.wae.opm.action import OpmActionBase
from com.cisco.wae.opm.network import open_plan
from tePortalLauncher import TePortalLauncher
import threading
import ConfigParser
import time
import subprocess

# ---------------------------------------------
# COMPONENT THREAD THAT WILL BE STARTED BY WAE.
# ---------------------------------------------

class FetchAllLSPs(Application):

	def setup(self):
		self.log.info('lsp-fetch-all service starting..')

		# The class takes care of creating a daemon (related to the
		# service/action point).
		self.register_action('lsp-fetch-all-action-point',
                                FetchAllLSPsAction, [])

		# When this setup method is finished, all registrations are
        # considered done and the application is 'started'.
		self.log.info('lsp-fetch-all service started')

	def teardown(self):
		# When the application is finished, this teardown method will
		# be called.
		self.log.info('lsp-fetch-all service stopped')


class FetchAllLSPsAction(OpmActionBase):

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
		# Reading configuration file for config params at runtime
		self.config.read(TePortalLauncher.portal_config_file)
		self.nw_source = self.config.get('WAEServer', 'NetworkModelSource')

		self.log.info("Got request for Fetching Tunnels in network")
		self.start = time.time()

		if (self.nw_source == 'PLANFILE'):
			self.get_all_lsps_mate_sql(output)
		elif (self.nw_source == 'WMD'):
			self.get_all_lsps_wmd(output)
		#self.get_all_lsps_opm(net_name, output)

		EndTime = time.time()
		self.log.info("Getting all Tunnel names from network took ",(EndTime - self.planReadTime)," seconds")
		self.log.info("Total Time taken to return all Tunnel names ",(EndTime - self.start)," seconds")

		# Update opm end status - active state as False and
        # last successful run time stamp depending on output.result.
        #self.update_end_status(output.result)

	def get_all_lsps_mate_sql(self, output):
		planFile = self.config.get('WAEPortal', 'PlanFileWithDelaynResBW')
		mate_sql_cmd = self.config.get('WAEServer', 'mate_sql_cmd')
		with open_plan(planFile) as network:
			self.planReadTime = time.time()
			self.log.info("Plan file opened in ", (self.planReadTime - self.start), " seconds")
			#APPROACH 1, took 10 seconds to verify 4000 interface
			sql = "select Name,Source from LSPs order by Name"
			cmd = mate_sql_cmd +" -file "+ planFile +"  -sql \""+sql+"\""
			self.log.debug(cmd)
			p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
			out, err = p.communicate()
			#out = p.stdout.read()
			self.log.debug(out)

			lines = out.split('\n')
			headerPassed = False
			for line in lines:
				#line = line.strip()
				if(headerPassed):
					vals = line.split('\t')
					if(len(vals)<2):
						continue
					returnlsp = output.lspKeys.create()
					returnlsp.lspName = vals[0]
					returnlsp.lspSrcNode = vals[1]
				elif("Name	Source" in line):
						headerPassed = True
		self.log.info("Found %s Tunnels in network" % (len(output.lspKeys)))


	def get_all_lsps_opm(self, net_name, output):
		with self.get_wae_network(net_name) as network:
			self.planReadTime = time.time()
			for lsp in network.model.lsps:
				#self.log.info(lsp.name+lsp.source.name)
				returnlsp = output.lspKeys.create()
				returnlsp.lspName = lsp.name
				returnlsp.lspSrcNode = lsp.source.name

	def get_all_lsps_wmd(self, output):
		network = TePortalLauncher.get_wmd_client().get_latest_network(refresh=True)
		self.planReadTime = time.time()
		self.log.info("WMD Network accessed in ", (self.planReadTime - self.start), " seconds")
		#self.log.info("Found %s Tunnels in network" % (len(network.model.lsps)))
		ignored_count = 0
		processed_count = 0
		for lsp in network.model.lsps:
			if lsp.destination is None:
				self.log.debug("Ignoring Tunnel:",lsp," as its destination is not known")
				ignored_count += 1
				continue
			processed_count += 1
			#self.log.info(lsp.name+lsp.source.name)
			returnlsp = output.lspKeys.create()
			returnlsp.lspName = lsp.name
			returnlsp.lspSrcNode = lsp.source.name
		self.log.warning("Ignored ",ignored_count," Tunnels because of un-known destination")
		self.log.info(processed_count," Tunnels are being reported to portal")
		network.remove_from_rpc()
		network.close()
