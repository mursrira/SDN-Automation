from builtins import str
from builtins import range
import ncs
import time
import sys
import logging
from etisalat_utils.helpers import Helpers
from ncs.application import Service
from ncs.dp import Action
import re


class LspReRouterActionImpl(Action):	
	
	@Action.action
	def cb_action(self, uinfo, name, kp, input, output):
		try:
			with ncs.maapi.Maapi() as maapi_obj:
				with ncs.maapi.Session(maapi_obj, "admin", "system"):
					with maapi_obj.start_write_trans() as maapi_trans:
						self.log.debug("Mappi Transaction Started")
					
						root = ncs.maagic.get_root(maapi_trans)
						self.log.info("Request received for %s LSPs, action: %s" % (
							(len(input.te_interfaces)), input.action_type))
						helpers = Helpers(self)
						not_synced_devices = helpers.sync_devices(
							input.te_interfaces)
						lsp_status_message = {}

						if len(not_synced_devices) > 0:
							errMsg = "Unable to sync devices @ NSO : {} ".format(
								not_synced_devices)
							self.log.error(errMsg)
							output.result = False
							output.message = errMsg
							raise ValueError(errMsg)
					
						for te_interface in input.te_interfaces:
							PATH_NAME_EXISTS = 'false'
							self.log.info("Processing Tunnel ID(%s), on device (%s)" %(te_interface.te_name, te_interface.srcNode))

							if te_interface.srcNode in list(lsp_status_message.keys()):
								self.log.info('DO NOTHING')
							else:
								lsp_status_message[te_interface.srcNode] = []
							try:
								dev = root.devices.device
								# To get the interface
								interface_level = root.devices.device[
									te_interface.srcNode].config.cisco_ios_xr__interface
								# To get explicit path
								explicit_path = root.devices.device[te_interface.srcNode].config.cisco_ios_xr__explicit_path
								#
								# Re-route explicit Path
								#
								if(te_interface.operation_type == "re-routed") and (te_interface.te_name in interface_level.tunnel_te):
									pathName = interface_level.tunnel_te[te_interface.te_name].path_option[te_interface.pathOption].explicit.name
									self.log.debug("Existing PathName: ",pathName)

									# Delete Hops from Path
									if(input.action_type != "dry-run"):
										self.log.info("Deleting hops from Path:" ,pathName)
										# To Delete the explicit path index
										del explicit_path.name[pathName].index

									self.log.debug("Filling up Template")
									# To add LSP message status into dictionary for device
									lsp_status_message[te_interface.srcNode].append("Re-routed tunnel_id:"+ str(te_interface.te_name)+ ", path_name:"+ str(pathName))
									# Filling up Template
									vars = ncs.template.Variables()
									vars.add('DEVICE', te_interface.srcNode)
									vars.add('TUNNEL_ID',te_interface.te_name)
									vars.add('DEST_IP', helpers.get_loopback_address(
										root, te_interface.destNode))
									vars.add('PATH_OPTION',
										te_interface.pathOption)
									# To check te_interface contains path name
									vars.add('PATH_NAME',pathName)
									# To retrieve te_interface hops details
									for hopnode in te_interface.hop:
										vars.add('STEP',hopnode.step)
										vars.add('HOP_ADDRESS',hopnode.ipaddress)
										self.log.debug("Adding step %s and hop address %s" %(hopnode.step, hopnode.ipaddress))
										self.log.debug("Variables filled in template = ",vars)
										template = ncs.template.Template(dev)
										template.apply('wae-device-config', vars)
								#
								# Create Tunnel_te and explicit Path
								#		
								if(te_interface.operation_type == "created"):
									# To add LSP message status into dictionary for device
									lsp_status_message[te_interface.srcNode].append("Created tunnel_id:" + str(te_interface.te_name)+ ", path_name:"+ str(te_interface.pathName))
									# Filling up Template
									create_vars = ncs.template.Variables()
									create_vars.add(
										'DEVICE', te_interface.srcNode)
									create_vars.add(
										'TUNNEL_ID', te_interface.te_name)
									create_vars.add('DEST_IP',
													helpers.get_loopback_address(root, te_interface.destNode))
									create_vars.add(
										'PATH_OPTION', te_interface.pathOption)
									# To check te_interface contains path name
									if te_interface.pathName is not None:
										self.log.debug("Path name is given as : ",te_interface.pathName)
										create_vars.add('PATH_NAME',te_interface.pathName)
									else:
										self.log.debug('For Device {} and tunnel-ID {} explict path does not exist in WAE model'.format(te_interface.srcNode,te_interface.te_name))
									# To retrieve te_interface hops details
									for hopnode in te_interface.hop:
										create_vars.add('STEP',hopnode.step)
										create_vars.add('HOP_ADDRESS',hopnode.ipaddress)
										self.log.debug("Adding step %s and hop address %s" %(hopnode.step, hopnode.ipaddress))
										self.log.debug("Variables filled in template = ",create_vars)
										template = ncs.template.Template(dev)
										template.apply('wae-device-create-config', create_vars)
								#
								# Delete Tunnel_te and explicit Path
								#
								if(te_interface.operation_type == "deleted") and (te_interface.te_name in interface_level.tunnel_te):
									self.log.debug("Deleting tunnel_te:" ,te_interface.te_name)
									# To Retrieve the explicit name from device
									pathName = interface_level.tunnel_te[te_interface.te_name].path_option[te_interface.pathOption].explicit.name
									# To add LSP message status into dictionary for device
									lsp_status_message[te_interface.srcNode].append("Deleted tunnel_id:"+ str(te_interface.te_name)+ ", path_name:"+ str(pathName))

									# To Delete the interface tunnel_te from Device
									del interface_level.tunnel_te[te_interface.te_name]
									# To Delete the explicit path
									del explicit_path.name[pathName]


								lsp_status_message[te_interface.srcNode] = list(set(lsp_status_message[te_interface.srcNode]))
							except (KeyError, IndexError, ValueError, NameError) as err:
								logging.exception(err)
								raise err
							except Exception as e:
								logging.exception(e)
								raise Exception("Failed due to internal error. Details are logged.")

						if(input.action_type == "dry-run"):
							self.log.debug("Invoking Dry-run")
							dryRun = root.services.commit_dry_run
							try:
								output.message = ""
								drInput = dryRun.get_input()
								drInput.outformat = 'native'
								drOutput = dryRun(drInput)
								if drOutput.native != None:
									self.log.debug('drOutput.native : ', drOutput.native)
									if(len(drOutput.native.device)>0):
										for device in drOutput.native.device:
											nativeCmd = device.data
											self.log.debug('Dry-run output : ', nativeCmd)
											mapping = self.responseMapping(str(device.name), str(nativeCmd), lsp_status_message[device.name])
											output.result = True
											output.message = output.message + "\n! Device Configuration Changes on : " +str(device.name)+ " for LSPs "
											for messages in mapping.values():
												for message in messages:
													output.message = output.message + str(message)
											#output.message = output.message + str(nativeCmd)
											self.log.debug("Output message: ",str(output.message))
									else:
										output.result = True
										output.message = "! No Configuration Change expected for this action"+ "\n"
										self.log.debug("Output message: ",str(output.message))
							except (KeyError, IndexError, ValueError, NameError) as err:
								logging.exception(err)
								raise err
							except Exception as e:
								logging.exception(e)
								raise Exception("Failed due to internal error. Details are logged.")
						else:
							self.log.debug("Applying Template as commit is being performed")
							maapi_trans.apply()
							output.result = True
							output.message = "LSP Changed Successfully."
							self.log.info(output.message)
		except (KeyError, IndexError, ValueError, NameError) as err:
			logging.exception(err)
			raise err
		except Exception as e:
			logging.exception(e)
			raise Exception("Failed due to internal error. Details are logged.")



	def responseMapping(self, devicename, devicedata,lsp_message_list):

		config_dict = {}

		for lsp_message in lsp_message_list:

			tunnel_ids = re.findall(r':\w+[^\s.!?]*',lsp_message)
			te_id = tunnel_ids[0][1:][:-1]
			pathname = tunnel_ids[1][1:]
			lsp_status = re.findall(r'\w+\s',lsp_message)
			self.log.debug("lsp_status",lsp_status)
			conf_list = [str("\n! " + lsp_message.split(',')[0] + "\n!\n")]
			# Delete configuration
			confs = re.findall(r'no\s+[^\n.!?]*[\.!?]*',devicedata)
			for conf in confs:
				if (te_id in conf or pathname in conf) and 'no' in conf:
					devicedata = devicedata.replace(conf,'')
					conf_list.append(conf+'\n')
			# Create configuration
			if 'Created ' in lsp_status:
				confs1 = re.findall(r'explicit-path\s\w*\s'+pathname+'[^\]*[$!]+[^\n]*[$!]',devicedata)
				for conf in confs1:
					if (te_id in conf or pathname in conf) and 'explicit' in conf:
						conf_list.append(conf)
						break

				confs2 = re.findall(r'\ninterface\stunnel-te\s'+te_id+'[^\]*[$!]+[$\nexit.!?]',devicedata)
				for conf in confs2:
					if (te_id in conf or pathname in conf) and 'interface' in conf:
						conf_list.append(conf)
			# Re-route configuration
			else:
				confs1 = re.findall(r'explicit-path\s\w*\s'+pathname+'[^\]*[$!]+[^\n]*[$!]',devicedata)
				for conf in confs1:
					if (te_id in conf or pathname in conf) and 'explicit' in conf:
						conf_list.append(conf)
						break
			config_dict[devicename + "_t"+te_id] = conf_list
		return config_dict

class LspReRouterAction(ncs.application.Application):
	def setup(self):
		'''The application class sets up logging for us. It is accessible
		through 'self.log' and is a ncs.log.Log instance.'''
		self.log.info('lsp-re-route action Running')

		'''When using actions, this is how we register them'''

		self.register_action('lsp-re-router-action-point',LspReRouterActionImpl)

		'''If we registered any callback(s) above, the Application class
		took care of creating a daemon (related to the service/action point).

		When this setup method is finished, all registrations are
		considered done and the application is 'started'.'''

	def teardown(self):
		'''When the application is finished (which would happen if NCS went
		down, packages were reloaded or some error occurred) this teardown
		method will be called.'''
		
		self.log.info('lsp-re-route FINISHED')
