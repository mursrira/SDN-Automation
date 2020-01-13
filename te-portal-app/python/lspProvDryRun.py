from ncs.application import Application
from com.cisco.wae.opm.action import OpmActionBase
from tePortalLauncher import TePortalLauncher
import ncs.application
import device_helper as dh
import time
import subprocess
import ConfigParser


# ---------------------------------------------
# COMPONENT THREAD THAT WILL BE STARTED BY WAE.
# ---------------------------------------------

class LspProvDryRun(Application):

	def setup(self):
		self.log.info('lsp-prov-dryrun service starting..')

		# The class takes care of creating a daemon (related to the
		# service/action point).
		self.register_action('lsp-prov-dryrun-point',
								LspProvDryRunAction, [])

		# When this setup method is finished, all registrations are
		# considered done and the application is 'started'.
		self.log.info('lsp-prov-dryrun service started')

	def teardown(self):
		# When the application is finished, this teardown method will
		# be called.
		self.log.info('lsp-prov-dryrun service stopped')


class LspProvDryRunAction(OpmActionBase):

	config = ConfigParser.RawConfigParser()

	def run(self, net_name, input, output):
		'''
			This run method is used to sync the network, make explicit path
			and provisions lsp.It returns an output object based on the yang
			model defined
		'''
		# Reading configuration file for config params at runtime
		self.config.read(TePortalLauncher.portal_config_file)

		username = self.config.get('WAEServer', 'OPMRestAPIUserName')
		password = self.config.get('WAEServer', 'OPMRestAPIUserPass')
		net_name = self.config.get('WAEServer', 'OPMRestAPILspConfigNimoNetworkName')

		start = time.time()

		tunnel_id = self.get_next_tunnel_id()
		if 'tunnel-te' in input.lsp_name:
			lsp_name = 'tunnel-te' + tunnel_id
		else:
			lsp_name = 'Tunnel' + tunnel_id

		self.log.info("(DRY-RUN) Got request for Tunnel Provisioning: ",lsp_name)


		#Sync network
		'''
		self.log.info("Initiating the network sync")
		try :
			with ncs.maapi.single_write_trans(username, password) as t:
				root = ncs.maagic.get_root(t)
				#put the variables from input to pass to the template
				variables = ncs.template.Variables()
				variables.add('NETWORK_NAME',net_name)
				service = root.networks.network[net_name]
				template = ncs.template.Template(service)
				#apply template
				template.apply('network-sync', variables)
				#apply transaction
				t.apply()
		except Exception as e:
				self.log.error("Unable to sync the network : "+ net_name)
				output.result = False
				output.message = "Unable to sync the network : "+ net_name +" Error at : "+ str(e)
				return
		networkSyncTime = time.time()
		self.log.info("Initial network sync completed sucessfully in ",(networkSyncTime-start), " seconds")
		'''
		networkSyncTime = time.time()

		cmd = "/opt/wae/bin/wae_cli -u %s -C" % username
		
		self.log.info("(DRY-RUN) Initiating Explicit paths creation")

		'''
		try:
			with ncs.maapi.single_write_trans(username, password) as t:
				root = ncs.maagic.get_root(t)
				lsp_name = dh.get_Tunnel_Prefix(root, str(input.source)) + tunnel_id
		except Exception as e:
			self.log.error("Unable to detect device type: " + str(input.source))
			output.result = False
			output.message = "Unable to detect device type: " + str(input.source)+" Error at : " + str(e)
			return
		'''

		# Make explicit paths
		configurations = []
		for lsp in input.lsp_path:
			path_name = str(lsp_name)+"-"+str(input.source)+"-"+str(input.destination)+"-"+str(lsp.path_option)
			pathConfig = "networks network "+net_name+" model nodes node "+input.source+" named-paths named-path "+ path_name +" hops "
			for hop in lsp.hop:
				self.log.info("(DRY-RUN) Path Hop(",hop.step,") being created is ", str(hop.hop_node)+":"+str(hop.hop_if)+":"+str(hop.hop_ip))
				hopConfig="hop "+str(hop.step)+" type loose unresolved-hop "+hop.hop_ip+" interface node-name "+hop.hop_node+" interface-name "+hop.hop_if
				configurations.append(pathConfig+hopConfig)
		pathCreationTime = time.time()
		self.log.info("(DRY-RUN) Explicit path creation completed sucessfully in ",(pathCreationTime - networkSyncTime) , " seconds")


		self.log.info("(DRY-RUN) Initiating Tunnel creation")
		#Configure lsp
		mt=''
		if(input.auto_route):
			mt = " metric-type auto-route"
		lspConfig = "networks network "+net_name+" model nodes node "+input.source+" lsps lsp "+lsp_name+ " destination "+str(input.destination)+mt+" description 'TE_Portal_Tunnel_To_"+str(input.destination)+"' setup-pri 0 hold-pri 0 lsp-paths"
		rawConfig =" raw attribute-set tunnel-id="+tunnel_id+",load-interval=30,loop-back=0"
		for lsp in input.lsp_path:
			self.log.info('(DRY-RUN) Tunnel being created ', lsp_name,' TunnelID: ',tunnel_id)
			path_name = str(lsp_name)+"-"+str(input.source)+"-"+str(input.destination)+"-"+str(lsp.path_option)
			lspPathConfig=" lsp-path "+str(lsp.path_option)+" named-path "+path_name
			configurations.append(lspConfig+lspPathConfig+rawConfig)
		tunnelCreationTime = time.time()
		self.log.info("(DRY-RUN)Tunnel creation completed sucessfully in ",(tunnelCreationTime - pathCreationTime) , " seconds")
		self.log.info("(DRY-RUN)End to End Tunnel provisioning process took ",(tunnelCreationTime - start) , " seconds")

		finalConf = '\n'.join(configurations)

		inputs = "config\n"+finalConf+"\ncommit dry-run outformat native\nabort\nexit\n"
		self.log.debug(inputs)

		##Make sure stdin is set to PIPE else POPEN wont read input
		p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,stdin=subprocess.PIPE, stderr=subprocess.STDOUT)
		stdout,err = p.communicate(inputs)

		self.log.debug(stdout)

		nativeCmd = ''
		lines = stdout.split('\n')
		if(len(lines)==1):
			self.log.error("Error during config application")
			#TODO send to screen
		else:
				headerPassed = False
				for line in lines:
						line = line.strip()
						if(headerPassed):
								if(line == '}' or line == 'exit'):
										break
								nativeCmd = nativeCmd + '\n' + line
						elif("data !" in line):
								nativeCmd = line[5:]
								headerPassed = True

		self.log.info("Final Output:\n",nativeCmd)

		stmt1 = time.time()
		self.log.info("(DRY-RUN) Whole dry-run process took " ,(stmt1-start) ," seconds")

		#Control has reached here, implying that lsp has been configured
		output.message = "! Device Configuration for Provisioning Tunnel: "+ str(lsp_name)+"\n"+nativeCmd
		output.result = True
		self.update_end_status(output.result)

	def get_next_tunnel_id(self):
		tunnel_id_file = self.config.get('WAEPortal', 'NextTunnelIdFile')
		with open(tunnel_id_file) as ifCmdFile:
			content = ifCmdFile.readlines()
			for line in content:
				tunnel_id = str(line).rstrip()
				return tunnel_id
