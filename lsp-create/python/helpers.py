import ncs
import time
import sys
import logging
from ncs.application import Service
from ncs.dp import Action

class Helpers(object):

	def __init__(self,log):
                self.log = log
                self.headers = {
                        'content-type': "application/vnd.yang.operation+json"
                        }

	def checkSync(self,device_name):
                try:
                        with ncs.maapi.Maapi() as maapi_obj:
                                with ncs.maapi.Session(maapi_obj, "admin", "system"):
                                        with maapi_obj.start_write_trans() as maapi_trans:
                                                root = ncs.maagic.get_root(maapi_trans)
                                                output = root.ncs__devices.device[device_name].check_sync()
                                                self.log.debug("checkSync Result: %s" % output.result)

                except (KeyError, IndexError, ValueError, NameError) as err:
                        logging.exception(err)
                        raise err
                except Exception as e:
                        logging.exception(e)
                        raise Exception("Failed due to internal error. Details are logged.")

                return str(output.result)


	def syncFrom(self, device_name):
         	sync = False
		try:
			with ncs.maapi.Maapi() as maapi_obj:
				with ncs.maapi.Session(maapi_obj, "admin", "system"):
					with maapi_obj.start_write_trans() as maapi_trans:
						root = ncs.maagic.get_root(maapi_trans)
                                                self.log.info("Syncing Device: ",device_name)
                    				output = root.ncs__devices.device[device_name].sync_from()
                    				self.log.info("Result for device: ",device_name," sync is: %s" % output.result)
                    				if not output.result:
                        				self.log.error("Error: %s" % output.info)
                    				else:
                        				sync = True
                        				self.log.info("Sync successful for device :",device_name, sync)
                    			maapi_trans.finish()
         	except Exception as e:
             		self.log.error("Getting error while doing sync-from : ", str(e))
         	return sync

	def sync_device(self, device_name):
                sync = self.checkSync(device_name)
                if (sync != "in-sync"):
                        self.log.info("Device was found not in-sync: ",device_name)
                        sync = self.syncFrom(device_name)
                        sync = self.checkSync(device_name)
                        if(sync != "in-sync"):
                                return False
		return True


	def get_loopback_address(self, root, device, deviceType):
                TYPE_CISCO_IOS = '{tailf-ned-cisco-ios}'
                TYPE_CISCO_IOSXR = '{tailf-ned-cisco-ios-xr}'
                TYPE_JUNIPER_JUNOS = '{juniper-junos}'
                DEVICE_LOOKUP = {
                        TYPE_CISCO_IOS: 'ios',
                        TYPE_CISCO_IOSXR: 'iosxr',
                        TYPE_JUNIPER_JUNOS: 'junos'
                }
                #TODO FIx device type
                '''modules = root.devices.device[device].module.keys()
                device_type = str(modules[0])

                device_type = TYPE_CISCO_IOSXR
                
                address = None'''
                device_config = root.ncs__devices.ncs__device[device].ncs__config
                if deviceType == TYPE_CISCO_IOS:
                        loopback = device_config.ios__interface.ios__Loopback[0]
                        address = loopback.ip.address.primary.address
                        device_type = 'CISCO_IOS'
                elif deviceType == TYPE_CISCO_IOSXR:
                        loopback = device_config.cisco_ios_xr__interface.Loopback[0]
                        address = loopback.ipv4.address.ip
                        device_type = 'CISCO_IOSXR'
                elif deviceType == TYPE_JUNIPER_JUNOS:
                        loopback = device_config.junos__configuration.interfaces.interface[0]
                        address = loopback.unit['0'].family.inet.address[0].name
                else:
                        raise Exception('Unknown device type ' + device_type)
                return address


        def getDeviceNode(self, root, deviceName):
                
                devicesList = root.ncs__devices.device
                self.log.info(devicesList)
                iterObj = iter(devicesList)
                for device in iterObj:
                        if(device.name == deviceName):
                                
                                self.log.info("Got request to know type of device - {}".format(device.name)) 
                                return device
        
        def getDeviceType(self,root,device):

                device=self.getDeviceNode(root,device)
                if device:
                        deviceNodeType = device.device_type.cli.ned_id

                        if deviceNodeType == 'cisco-ios':
                                self.log.info("Requested device - {} and type {}".format(device.name,deviceNodeType))
                                return '{tailf-ned-cisco-ios}'
                        elif deviceNodeType == 'cisco-ios-xr':
                                self.log.info("Requested device - {} and type {}".format(device.name,deviceNodeType))
                                return '{tailf-ned-cisco-ios-xr}'
                        else:
                                self.log.error("device {} is of type {} is not handeled!(does not belong to IOS/IOSXR)".format(device.name,deviceNodeType))

