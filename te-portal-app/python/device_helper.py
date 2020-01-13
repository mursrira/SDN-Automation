TYPE_CISCO_IOS = '{tailf-ned-cisco-ios}'
TYPE_CISCO_IOSXR = '{tailf-ned-cisco-ios-xr}'
TYPE_JUNIPER_JUNOS = '{juniper-junos}'
DEVICE_LOOKUP = {
	TYPE_CISCO_IOS: 'ios',
	TYPE_CISCO_IOSXR: 'iosxr',
	TYPE_JUNIPER_JUNOS: 'junos'
}
def get_device_type(root, device):
	"""Return the YANG module name used by the device
	Arguments:
	root -- Maagic CDB root
	device -- name of the device
	"""
	modules = root.devices.device[device].module.keys()
	return str(modules[0])

def get_loopback_address(root, device, device_type,
	loopback_interface):
	"""Return the loopback IP address for the given device and id
	Arguments:
	root -- Maagic CDB root
	device -- name of the device
	device_type -- device type (YANG module name)
	loopback_interface -- Loopback interface ID
	"""
	device_config = root.ncs__devices.ncs__device[device].ncs__config
	address = None
	if device_type == TYPE_CISCO_IOS:
		loopback = device_config.ios__interface.ios__Loopback[loopback_interface]
		address = loopback.ip.address.primary.address
	elif device_type == TYPE_CISCO_IOSXR:
		loopback = device_config.cisco_ios_xr__interface.Loopback[loopback_interface]
		address = loopback.ipv4.address.ip
	elif device_type == TYPE_JUNIPER_JUNOS:
		loopback = device_config.junos__configuration.interfaces.interface[loopback_interface]
		address = loopback.unit['0'].family.inet.address[0].name
	else:
		raise Exception('Unknown device type ' + device_type)

	return address
