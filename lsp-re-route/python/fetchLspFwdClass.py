# -*- mode: python; python-indent: 4 -*-
import ncs
from ncs.application import Service
import sys
import logging
from ncs.dp import Action

class FetchLspFwdClassAction(Action):
	@Action.action
	def cb_action(self, uinfo, name, kp, input, output):
		try:
			#Reading class info from devices
        		with ncs.maapi.Maapi() as maapi_obj:
				with ncs.maapi.Session(maapi_obj, "admin", "system"):
					with maapi_obj.start_write_trans() as maapi_trans:
						try:
							self.log.info("MAAPI TRANSACTION CREATED")
							te_count = 0	
							root = ncs.maagic.get_root(maapi_trans)
							self.log.info("MAAPI OPENED")	
							TYPE_CISCO_IOSXR = '{tailf-ned-cisco-ios-xr}'
							TYPE_NEXUS ='{tailf-ned-cisco-nx}'
							DEVICE_LOOKUP = {
								'TYPE_CISCO_IOSXR': 'iosxr',
								'TYPE_NEXUS' :'cisco-nx'
							}
							for each_device in root.ncs__devices.ncs__device:
								device_type = each_device.device_type.cli.ned_id
								self.log.info("Device Type : ", device_type)
								if DEVICE_LOOKUP['TYPE_CISCO_IOSXR'] in device_type:
									for each_te in each_device.ncs__config.cisco_ios_xr__interface.tunnel_te:
										if each_te.id:
											self.log.info("Forward class input ",input.forwardClass)
											if(input.forwardClass == "non-zero"):
												if(each_te.forward_class):
													self.fetch_lspFwdClassess(output,each_device,each_te)
											else:
												self.fetch_lspFwdClassess(output,each_device,each_te)
								else:
									continue
						except (KeyError, IndexError, ValueError, NameError) as err:
							logging.exception(err)
							raise err
						except Exception as e:
							logging.exception(e)
							raise Exception("Failed due to internal error. Details are logged.")
						finally:
							maapi_trans.apply()
		except (KeyError, IndexError, ValueError, NameError) as err:
			logging.exception(err)
			raise err
		except Exception as e:
			logging.exception(e)
			raise Exception("Failed due to internal error. Details are logged.")

	def fetch_lspFwdClassess(self,output,each_device,each_te):
		try:
			lspClass = output.lspClasses.create(each_device.name,each_te.id)
			#lspClass.deviceName = each_device.name
			#lspClass.te_name = each_te.id
			#TODO Replace destination with class in future
			lspClass.forwardClass = 0
		except (KeyError, IndexError, ValueError, NameError) as err:
                        logging.exception(err)
                        raise err
                except Exception as e:
                        logging.exception(e)
                        raise Exception("Failed due to internal error. Details are logged.")


class FetchLspFwdClass(ncs.application.Application):
	def setup(self):
        # The application class sets up logging for us. It is accessible
        # through 'self.log' and is a ncs.log.Log instance.
		self.log.info('Action RUNNING')

	# When using actions, this is how we register them:
        #
		self.register_action('fetchAction',FetchLspFwdClassAction)


        # If we registered any callback(s) above, the Application class
        # took care of creating a daemon (related to the service/action point).

        # When this setup method is finished, all registrations are
        # considered done and the application is 'started'.

	def teardown(self):
        # When the application is finished (which would happen if NCS went
        # down, packages were reloaded or some error occurred) this teardown
        # method will be called.

		self.log.info('Action FINISHED')
