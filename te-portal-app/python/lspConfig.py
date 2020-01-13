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

class LspConfig(Application):

	def setup(self):
		self.log.info('lsp-prov-commit service starting..')

		# The class takes care of creating a daemon (related to the
		# service/action point).
		self.register_action('lsp-prov-commit-point',
								LspConfigAction, [])

		# When this setup method is finished, all registrations are
		# considered done and the application is 'started'.
		self.log.info('lsp-prov-dryrun service started')


	def teardown(self):
		# When the application is finished, this teardown method will
		# be called.
		self.log.info('lsp-prov-dryrun service stopped')


class LspConfigAction(OpmActionBase):

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

		source_node = str(input.source)
		tunnel_id = self.get_next_tunnel_id()
		if 'tunnel-te' in input.lsp_name:
			lsp_name = 'tunnel-te' + tunnel_id
		else:
			lsp_name = 'Tunnel' + tunnel_id
		self.log.info("[",input.action_type,"] Got request for Tunnel Provisioning %s:%s"%(source_node,lsp_name))
		'''
		self.log.info("Initiating the network sync")
		#Sync network
		try :
			with ncs.maapi.single_write_trans('admin', 'system') as t:
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

		self.log.info("[",input.action_type,"] Initiating Explicit paths creation")

		#Make explicit paths
		try :
			for lsp in input.lsp_path:
				#for every lsp start step at 10 and increment by 10
				with ncs.maapi.single_write_trans(username, password) as t:
					for hop in lsp.hop:
						root = ncs.maagic.get_root(t)
						#get device type of the source
						#deviceType = dh.get_device_type(root,input.source)
						#put the variables from input to pass to the template
						variables = ncs.template.Variables()
						service = root.networks.network[net_name]
						#deviceType = dh.get_device_type(root,hop.hop_node) ##commented
						#get loopback address of the hop (has to be changed)
						#variables.add('HOP_LOOPBACK',dh.get_loopback_address(root,hop.hop_node,deviceType,0))
						self.log.info("Path Hop(",hop.step,") being created is ", str(hop.hop_node)+":"+str(hop.hop_if)+":"+str(hop.hop_ip))
						variables.add('HOP_IF',hop.hop_if)
						variables.add('HOP_NODE',hop.hop_node)
						variables.add('HOP_LOOPBACK',hop.hop_ip) ##added
						path_name = lsp_name+"-"+source_node.replace(".","_")+"-"+str(input.destination).replace(".","_")+"-"+str(lsp.path_option)
						variables.add('PATH_NAME',path_name)
						variables.add('STEP', hop.step)
						variables.add('NETWORK_NAME',net_name)
						variables.add('SOURCE', input.source)
						template = ncs.template.Template(service)
						template.apply('make-explicit-path-template', variables)
						#self.dry_run(root)
						#apply transaction
						#t.apply()
					# Creating LSP
					description = "TE_Portal_Tunnel_To_"+str(input.destination)
					variables.add('DESCRIPTION', description)
					variables.add('NETWORK_NAME', net_name)
					variables.add('SOURCE', input.source)
					variables.add('LSP_NAME', lsp_name)
					variables.add('AUTO_ROUTE',input.auto_route)
					path_name = lsp_name+"-"+source_node.replace(".","_")+"-"+str(input.destination).replace(".","_")+"-"+str(lsp.path_option)
					self.log.info("PATH:",path_name)
					variables.add('PATH_NAME',path_name)
					variables.add('PATH_OPTION',lsp.path_option)
					variables.add('DESTINATION_LOOPBACK',input.destination)
					variables.add('TUNNEL_ID', tunnel_id)
					template = ncs.template.Template(service)
					template.apply('lsp-config-template', variables)
					
					dryRun = root.services.commit_dry_run
					drInput = dryRun.get_input()
					drInput.outformat = 'native'
					drOutput = dryRun(drInput)
					
					if(input.action_type == "dry-run"):
						if drOutput.native != None:
							nativeCmd = drOutput.native.device[1].data
							self.log.info('Dry-run output : ', nativeCmd)
							output.message = "! Device Configuration for Provisioning Tunnel: "+ str(lsp_name)+"\n"+nativeCmd
							output.result = True
							self.update_end_status(output.result)
					else:
						if drOutput.native != None:
							nativeCmd = drOutput.native.device[1].data
							self.log.info('Trying to commit : ', nativeCmd)
						t.apply()
						self.update_next_tunnel_id(tunnel_id)
		except Exception as e:
			self.log.error("[",input.action_type,"] Unable to make explicit paths for the network : "+ net_name)
			output.result = False
			output.message = "Unable to make explicit paths for the network : "+ net_name +" Error at : "+ str(e)
			return
		pathCreationTime = time.time()
		self.log.info("[",input.action_type,"] Explicit path creation completed sucessfully in ",(pathCreationTime - networkSyncTime) , " seconds")

		'''
		self.log.info("Initiating Tunnel creation")
		#Configure lsp
		try :
			for lsp in input.lsp_path:
				self.log.info('Tunnel being created %s:%s'%(source_node,lsp_name))
				with ncs.maapi.single_write_trans(username, password) as t:
					root = ncs.maagic.get_root(t)
					service = root.networks.network[net_name]
					description = "TE_Portal_Tunnel_To_"+str(input.destination)
					#put the variables from input to pass to the template
					variables.add('DESCRIPTION', description)
					variables.add('NETWORK_NAME', net_name)
					variables.add('SOURCE', input.source)
					variables.add('LSP_NAME', lsp_name)
					variables.add('AUTO_ROUTE',input.auto_route)
					path_name = lsp_name+"-"+source_node+"-"+str(input.destination)+"-"+str(lsp.path_option)
					variables.add('PATH_NAME',path_name)
					variables.add('PATH_OPTION',lsp.path_option)
					#deviceType = dh.get_device_type(root,input.destination)

					#self.log.info("Destination Loopback IP is " + str(dh.get_loopback_address(root,input.destination,deviceType,0)))
					variables.add('DESTINATION_LOOPBACK',input.destination)
					#dh.get_loopback_address(root,input.destination,deviceType,0))
					variables.add('TUNNEL_ID', tunnel_id)
					template = ncs.template.Template(service)
					#apply template
					template.apply('lsp-config-template', variables)
					dryRun = root.services.commit_dry_run
					drInput = dryRun.get_input()
					drInput.outformat = 'native'
					drOutput = dryRun(drInput)
					if drOutput.native != None:
						self.log.info('Dry-run output : ', drOutput.native.device[1].data)
					self.dry_run(root)
					#apply transaction
					#t.apply()
					self.update_next_tunnel_id(tunnel_id)
		except Exception as e:
			self.log.error("Unable to make lsp for the network : "+ net_name)
			output.result = False
			output.message = "Unable to make lsp for the network : "+ net_name +" Error at : "+ str(e)
			return
		'''
		tunnelCreationTime = time.time()
		self.log.info("[",input.action_type,"] Tunnel creation completed sucessfully in ",(tunnelCreationTime - pathCreationTime) , " seconds")
		self.log.info("[",input.action_type,"] End to End Tunnel provisioning process took ",(tunnelCreationTime - start) , " seconds")

		#Control has reached here, implying that lsp has been configured
		if(input.action_type == "commit"):
			output.message = "Successfully Provisioned Tunnel: "+ lsp_name
			output.result = True
			self.update_end_status(output.result)

	def get_next_tunnel_id(self):
		tunnel_id_file = self.config.get('WAEPortal', 'NextTunnelIdFile')
		with open(tunnel_id_file) as ifCmdFile:
			content = ifCmdFile.readlines()
			for line in content:
				tunnel_id = str(line).rstrip()
				return tunnel_id

	def update_next_tunnel_id(self,tunnel_id):
		next_tunnel_id = str(int(tunnel_id)+1)
		tunnel_id_file = self.config.get('WAEPortal', 'NextTunnelIdFile')
		with open(tunnel_id_file, 'w') as ifCmdFile:
			ifCmdFile.write(next_tunnel_id + "\n")
		self.log.info("Updated nexttunnel_id to: ",next_tunnel_id)
