import ncs
import time
import sys
import logging
from ncs.application import Service
from ncs.dp import Action
from helpers import Helpers


class LspCreatorAction(ncs.application.Application):
    def setup(self):

        self.log.info('lsp-create action Running')

        self.register_action('lsp-creater-action-point',
                             LspCreatorActionImpl)

    def teardown(self):
        self.log.info('lsp-create action FINISHED')


class LspCreatorActionImpl(Action):

	@Action.action
	def cb_action(self, uinfo, name, kp, input, output):

		#output handling for non sucessfull provision of LSP

		output.result = False

		# FETCH INPUT
		device = str(input.source)  # SOURCE NODE
		destination = str(input.destination)
		lspSrcNodeEgressintfName = str(input.lsp_name)
		tunnel_id = str(input.tunnel_id)
		#stunnel_id = 123
		
		#TODO
		'''if 'tunnel-te' in input.lsp_name:
			lsp_name = 'tunnel-te' + tunnel_id
		else:
			lsp_name = 'Tunnel' + tunnel_id
		self.log.info("[",input.action_type,"] Got request for Tunnel Provisioning %s:%s"%(device,lsp_name))'''

		my_helpers = Helpers(self.log)

		try:
			with ncs.maapi.Maapi() as maapi_obj:
				with ncs.maapi.Session(maapi_obj, "admin", "system"):
					with maapi_obj.start_write_trans() as maapi_trans:

						self.log.debug("Mappi Transaction Started")
						root = ncs.maagic.get_root(maapi_trans)

						self.log.info("Got Request to Create New LSP to decongest interfaces")

						#TODO ADD destination device also
						#DEVICES LIST who should be in SYNC with NSO (Source Node and Destination Node of LSP)
						#nsoDevicesSyncList = [device,destination]
						nsoDevicesSyncList = [device]
						not_synced_devices = self.sync_devices(root,nsoDevicesSyncList)

						if(len(not_synced_devices)>0):
							errMsg = "Unable to sync devices @ NSO : {} ".format(not_synced_devices)
							self.log.error(errMsg)
							output.result = False
							output.message = errMsg
							raise ValueError(errMsg)
						
						# HEAD END ROUTER DEVICE TYPE
						deviceTypeSrc = my_helpers.getDeviceType(root,device)
						deviceTypeDest = my_helpers.getDeviceType(root,destination)  

						
						loopbackAddressDest = my_helpers.get_loopback_address(root,destination,deviceTypeDest)		

						try:
							for lsp in input.lsp_path:
								self.log.info('Filling Template on headrouter {} for Explict Path Configuration'.format(device))
								for hop in lsp.hop:
									
									#
									# CREATING EXPLICIT PATH
									#
									templateApplyLevel = root.devices.device
									variables = ncs.template.Variables()
									self.log.info("Path Hop(",hop.step,") being created is ", str(hop.hop_node)+":"+str(hop.hop_if)+":"+str(hop.hop_ip))
									variables.add('HOP_LOOPBACK',hop.hop_ip) ##added
									#TODO
									#path_name = lsp_name+"-"+device.replace(".","_")+"-"+destination.replace(".","_")+"-"+str(lsp.path_option)
									path_name = device.replace('.','-') + '_' + lspSrcNodeEgressintfName.replace('/','-').replace('_','-') + '_' + destination.replace('.','-') 
									self.log.info("name is {}".format(path_name))
									
									variables.add('STEP', hop.step)
									variables.add('DEVICE', device) #HEAD ROUTER FOR LSP Deployment
									
									# Based on HEAD END ROUTER Type of template to APPLY
	
									if deviceTypeSrc == '{tailf-ned-cisco-ios}':
										variables.add('DEVICE_TYPE','CISCO_IOS')
										path_name = 'Tunnel'+str(tunnel_id)+'_'+path_name
									elif deviceTypeSrc == '{tailf-ned-cisco-ios-xr}':
										variables.add('DEVICE_TYPE','CISCO_IOSXR')
										path_name = 'tunnel-te'+str(tunnel_id)+'_'+path_name
									else:
										self.log.error('Tunnel Head Router is not of type IOS/IOSXR!!!') 

									variables.add('PATH_NAME',path_name)


									template = ncs.template.Template(templateApplyLevel)

									template.apply('make-explicit-path-template', variables)
								self.log.info('Successfully Filled Template on headrouter {} for Explict Path'.format(device))

							#
							# CONFIGURING LSP
							#
							self.log.info('Filling Template on headrouter {} for LSP configuration'.format(device))
							description = "TE_Portal_Tunnel_To_"+destination
							variables.add('DESCRIPTION', description)
							variables.add('DEVICE', device)
							variables.add('AUTO_ROUTE',input.auto_route)
							#TODO
							#path_name = lsp_name+"-"+device.replace(".","_")+"-"+str(input.destination).replace(".","_")+"-"+str(lsp.path_option)
							path_name = device.replace('.','-') + '_' + lspSrcNodeEgressintfName.replace('/','-').replace('_','-') + '_' + destination.replace('.','-')
							self.log.info("PATH:",path_name)
							variables.add('PATH_OPTION',lsp.path_option)
							variables.add('DESTINATION_LOOPBACK',loopbackAddressDest)
							#TODO
							variables.add('TUNNEL_ID', tunnel_id)

							# Based on HEAD END ROUTER Type of template to APPLY

							if deviceTypeSrc == '{tailf-ned-cisco-ios}':
								variables.add('DEVICE_TYPE','CISCO_IOS')
								path_name = 'Tunnel'+str(tunnel_id)+'_'+path_name
							elif deviceTypeSrc == '{tailf-ned-cisco-ios-xr}':
								variables.add('DEVICE_TYPE','CISCO_IOSXR')
								path_name = 'tunnel-te'+str(tunnel_id)+'_'+path_name
							else:
								self.log.info('Tunnel Head Router is not of type IOS/IOSXR!!!')
							variables.add('PATH_NAME',path_name)

							template = ncs.template.Template(templateApplyLevel)
							template.apply('lsp-config-template', variables)

							self.log.info('Sucessfully Filled Template on headrouter {} for LSP configuration'.format(device))


							#
							# DRY-RUN/COMMIT (LSP)
							#
							if(input.action_type == "dry-run"):

								self.log.debug("Invoking Dry-run")
								dryRun = root.services.commit_dry_run
								try:
									drInput = dryRun.get_input()
									drInput.outformat = 'native'
									drOutput = dryRun(drInput)

									output.message = ''
									if drOutput.native != None:
										self.log.debug('drOutput.native : ', drOutput.native)

										if(len(drOutput.native.device)>0):
											'''for i in range(len(drOutput.native.device)):
												nativeCmd = drOutput.native.device[i].data'''
											
                                        						for device in drOutput.native.device:
                                            							nativeCmd = device.data
												self.log.debug('Dry-run output : ', nativeCmd)
												output.result = True

												#output.message = output.message + "! Device Configuration for New LSP deployment on router: " +str(drOutput.native.device[i].name)+ "\n"
												output.message = output.message + "! Device Configuration for New LSP deployment on router: " +str(device.name)+ "\n"
												output.message = output.message + str(nativeCmd)
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

							elif (input.action_type == "commit"):

								self.log.debug("Applying Template as commit is being performed")
								maapi_trans.apply()
								self.log.debug("Successfully applied template")
								output.result = True
								output.message = "Successfully Provisioned Tunnel With ID: "+ tunnel_id + " and Explict Path name: " + path_name

						except (KeyError, IndexError, ValueError, NameError) as err:
							#logging.exception(err)
							raise err
						except Exception as e:
							logging.exception(e)
							raise Exception("Failed due to internal error. Details are logged.")


		except (KeyError, IndexError, ValueError, NameError) as err:
			#logging.exception(err)
			raise err
		except Exception as e:
			logging.exception(e)
			raise Exception("Failed due to internal error. Details are logged.")

	def sync_devices(self, root, nsoDevicesSyncList):
		not_synced_devices = []
		for device in nsoDevicesSyncList:
			my_helpers = Helpers(self.log)
			is_synced = my_helpers.sync_device(device)
			if not is_synced:
				not_synced_devices.append(device)
				self.log.error("Could not sync device: ",device)
		return not_synced_devices
