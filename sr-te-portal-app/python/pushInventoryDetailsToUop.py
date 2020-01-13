
from ncs.application import Application
from com.cisco.wae.opm.action import OpmActionBase
from com.cisco.wae.opm.network import open_plan
import com.cisco.wae.design
import threading
import ConfigParser
import subprocess,requests
from requests.auth import HTTPBasicAuth
from com.cisco.wae.design import ServiceConnectionManager
from helpers import Helpers
import logging
import ncs
from ncs.dp import Action
import json,os
from treelib import Node, Tree

#
# Push Inventory details to UOP
#
class PushInventoryDetailsToUop(Application):
		def setup(self):
			
			self.log.info('Start Push Inventory details to UOP, Action.........')
			self.register_action('push-inventory-details-to-uop-action-point',PushInventoryDetailsToUopAction, [])

		def teardown(self):
			self.log.info('Push Inventory details to UOP Action stopped')

#
# Push Inventory details to UOP Action 
#
class PushInventoryDetailsToUopAction(OpmActionBase):

	def run(self, net_name, input, output):


		my_helper = Helpers(self.log)
		#
		# WAE API CALL to PULL PLAN-FILES
		# 
		# TODO Uncomment after demo	
		output = my_helper.invokeWaeOpmRestApi("plan-archive/list","POST",None) #NO PAYLOAD RECQUIRED
		lastFile = output['cisco-wae-archive:output']['planfiles']['planfiles'][-1]
		planFile = str(lastFile['abspath']) #[-1] For fetching latest pln file
		
		self.log.debug('net_name is {}'.format(net_name))
		
		total_payload = {}
		# TODO Comment after demo
		#planFile = '/opt/wae713_run/scripts/etisalat-inventory-1.pln'

		with open_plan(planFile) as network:
			if 'etisalat' in net_name or 'emix' in net_name:
				net_name = 'EMIX'
			elif 'isg' in net_name:
				net_name = 'ISG'
			total_payload["network"] = net_name
			interfaces = network.model.interfaces
			ports = network.model.ports
			netint_tables = network.model.netint_tables
			self.log.info('Started preparing interface status dictionary')
			statusDict = self.getStatusofLink(netint_tables)
			self.log.info('Completed preparation of interface status dictionary')
			interfacesDict = self.getInterfaceDetails(interfaces, ports,statusDict)
			for netint_table in netint_tables:
				if str(netint_table.name) == 'NetIntNodeInventory':
					rows = netint_table.rows
					break
			node_list = []
			for row in rows:
				for (key, value) in zip(row.keys(), row.values()):	
					if key == 'Node':
						try:
							node = value
						except:
							node = None
					if node != None:
						node_list.append(node)
					break
			node_list = list(set(node_list))
			self.log.debug(node_list)
			self.log.debug(len(node_list))
			dict_list = []
			for nodename in node_list:
				node_name = nodename
				inv_list = []
				tree = Tree()
				self.add_inventory(rows, "Chassis", inv_list, node_name)
				self.add_inventory(rows, "Slot", inv_list, node_name)
				self.add_inventory(rows, "Linecard", inv_list, node_name)
				self.add_inventory(rows, "ModuleSlot", inv_list, node_name)
				self.add_inventory(rows, "Module", inv_list, node_name)
				self.add_inventory(rows, "PortSlot", inv_list, node_name)
				self.add_inventory(rows, "Port", inv_list, node_name)
				self.add_inventory(rows, "Transceiver", inv_list, node_name)

				i = 0
				first_element = {'node': node_name}
				tree.create_node(node_name, 0, data = first_element)
				for item in inv_list:
					val = item['typeOf']+":"+item['name']
					try:
						if i == 0:
							tree.create_node(val, item['id'], parent=0, data = item )
						else:
							if "Port" == item['typeOf']:
								if str(node_name+':::'+item['name']) in interfacesDict.keys():
									interfaceDet = interfacesDict[node_name+':::'+item['name']]
									item.update(interfaceDet)
								tree.create_node(val, item['id'] , parent=item['parentId'], data = item)
							else:
								tree.create_node(val, item['id'] , parent=item['parentId'], data = item)
						i = i + 1
					except:
						self.log.error( "Err",val)
						continue
				result = tree.to_json(with_data=True)
				result = json.loads(result)
				dict_list.append(result)

			total_payload["inventory_payload"] = dict_list
			total_payload = json.dumps(total_payload)
			self.log.info(total_payload)
		#
		# TODO UOP API CALL to PUSH Inventory Details 
		# 	
		resp = my_helper.invokeUOPRestApi('capacity_inventory_wae',"POST",total_payload)
		self.log.info('Response from UOP {} and the message is {}'.format(resp['meta']['success'],resp['meta']['info']))



	def getStatusofLink(self, netint_tables):

			#Extract NetIntInterfaces Table
			for netint_table in netint_tables:
				if str(netint_table.name) == 'NetIntInterfaces':
					rows1 = netint_table.rows
					break
			#Return StatusDict
			statusDict = {}
			for row in rows1:
				for (key, value) in zip(row.keys(), row.values()):
					if key == 'Node' or key == 'Interface' or key == 'NetIntAdminStatus' or key == 'NetIntOperStatus':
						if key == 'Node':
							try:
								node = value
							except:
								node = None
						if key == 'Interface':
							try:
								intf = value
								if 'tunnel-te' in intf or 'TU' in intf or 'SONET' in intf or \
									'Serial' in intf or 'PTP' in intf or 'POS' in intf or \
									'Null0' in intf or 'POS' in intf or 'MgmtEth' in intf or \
									'Loopback' in intf or 'dwdm' in intf:
									break
							except:
								intf = None
						if key == 'NetIntAdminStatus':
							try:
								intfAdminStatus = value
							except:
								intfAdminStatus = None
						if key == 'NetIntOperStatus':
							try:
								intfOperStatus = value
							except:
								intfOperStatus = None

							statusDictKey = str(node) + ':::' + str(intf)
							#TODO Changed intfAdminStatus to intfOperStatus
							statusDictValue = str(intfOperStatus) + ':::' + str(intfAdminStatus)
							statusDict[statusDictKey] = statusDictValue
							break  # AS Filled Dictionary
					else:
						continue

			return statusDict
	#
	# Get Interfaces table and Ports table details
	#
	def getInterfaceDetails(self, interfaces, ports, statusDict):
		interfacesDict = {}
		self.log.info('Processing interfaces data ....')
		for interface in interfaces:
			interfaceDict = {}
			oppInterface = interface.opposite_interface
			if "Bundle-Ether" in interface.name or "Vlan" in interface.name or "Bundle-Ether" in oppInterface.name or "Vlan" in oppInterface.name:
					continue
			else:
				#
				# OUTBOUND
				#
				try:
					interfaceDict['interface_description'] = interface.description
				except:
					interfaceDict['interface_description'] = 'NA'
				interfaceDict['router_name'] = interface.node.name
				interfaceDict['iface_name'] = interface.name
				if interface.configured_capacity is not None:
					interfaceDict['capacity'] = round(interface.configured_capacity, 2)
				else:
					interfaceDict['capacity'] = 0
				
				if "psn" in interfaceDict['router_name'] or "BgpPsn" in interfaceDict['router_name'] or "ASN" in interfaceDict['router_name']:
					interfaceDict['iface_operation_status'], interfaceDict['iface_admin_status'] = 'NA', 'NA'
				else:
					try:
						interfaceDict['iface_operation_status'], interfaceDict['iface_admin_status'] = statusDict[str(interfaceDict['router_name']) +
																												':::' + str(interfaceDict['iface_name'])].strip().split(':::')
					except:
						interfaceDict['iface_operation_status'], interfaceDict['iface_admin_status'] = 'NA', 'NA'
				#
				# INBOUND
				#
				try:
					interfaceDict['target_interface_description'] = oppInterface.description
				except:
					interfaceDict['target_interface_description'] = 'NA'

				interfaceDict['target_parent_bundle_id'] = 'NA'
				interfaceDict['target_router_name'] = oppInterface.node.name
				interfaceDict['target_iface_name'] = oppInterface.name
				interfaceDict['parent_bundle_id'] = 'NA'

				self.log.info("prepared dict from Interfaces table ",interfaceDict)
				interfacesDict[interface.node.name+':::'+interface.name] = interfaceDict
		self.log.info('Processing Ports data ....')
		portParamsDict=self.getPortParams(ports)
		for port in ports:
			if port.description or port.interface:
				portsDict={}

				if "FREE" in str(port.description).upper():
					continue
				else:
					port_circuit = port.port_circuit

					if port_circuit is not None:
						if port.node.name == port_circuit.port_a.node.name:
							port_a = port_circuit.port_a
							port_b = port_circuit.port_b
						elif port.node.name == port_circuit.port_b.node.name:
							port_a = port_circuit.port_b
							port_b = port_circuit.port_a
						else:
							self.log.debug("port node {} does not belong to {} or {}".format(port.node.name,port_circuit.port_a.node.name,port_circuit.port_b.node.name))
							continue

						inbound_capacity = port_b.capacity
						outbound_capacity=port_a.capacity
					else:
						self.log.debug("port node {} does not have port cicuit".format(port.node.name))

						decs_capacity_traffic = portParamsDict[port.node.name+":"+port.name]
						self.log.debug("node: {} port : {} have capacity and traffic {}".format(port.node.name,port.name,decs_capacity_traffic))					
						# portParams --> [description, traffic,capacity]
						portParams = decs_capacity_traffic.split(':::')
						port_desc = portParams[2].split('_')
						try:
							remote_node = port_desc[1]
							remote_port = port_desc[2]
						except:
							remote_node = "NA"
							remote_port = "NA"
						self.log.debug("Remote node: {}".format(port_desc))
						self.log.debug("Remote node: {} Remote port : {} ".format(remote_node,remote_port))
						remote_port_params = []
						remote_node_key = str(remote_node)+":"+str(remote_port)
						if remote_node_key in portParamsDict.keys():
							capacity_traffic = portParamsDict[remote_node_key]
							remote_port_params = capacity_traffic.split(':::')
						try:
							remote_desc = str(remote_port_params[2])
						except:
							remote_desc = "NA"
						try:
							remote_interface = str(remote_port_params[3])
						except:
							remote_interface = "NA"

					try:
						portsDict['capacity']=port.capacity
					except:
						portsDict['capacity']='NA'
					try:	
						if port.description:
							portsDict['port_description']=port.description
						else:
							portsDict['port_description']='NA'
					except:
						portsDict['port_description']='NA'
					try:						
						portsDict['iface_name']=port.name
					except:
						portsDict['iface_name']='NA'
					try:
						portsDict['router_name']=port.node.name
					except:
						portsDict['router_name']='NA'
					try:
						if remote_node is not None:
							portsDict['target_router_name']=  remote_node
						else:
							portsDict['target_router_name']= port_b.node.name
					except:
						portsDict['target_router_name']='NA'
					try:
						if remote_port is not None:
							portsDict['target_iface_name'] = remote_port
						else:
							portsDict['target_iface_name']=port.remote_port.name
					except:
						portsDict['target_iface_name']='NA'		
					try:	
						portsDict['parent_bundle_id']=port.interface.name
					except:
						portsDict['parent_bundle_id']='NA'
					try:
						if remote_desc is not None:
							portsDict['target_interface_description'] = remote_desc
						else:
							portsDict['target_interface_description']=port_b.description
					except:
						portsDict['target_interface_description']='NA'
					try:
						if remote_interface is not None:
							portsDict['target_parent_bundle_id'] = remote_interface
						else:
							portsDict['target_parent_bundle_id']=port_b.interface.name
					except:
						portsDict['target_parent_bundle_id']='NA'
					try:
						portsDict['iface_operation_status'],portsDict['iface_admin_status'] = statusDict[str(portsDict['router_name']) + \
							':::' + str(portsDict['iface_name'])].strip().split(':::')
					except:
						portsDict['iface_operation_status'],portsDict['iface_admin_status'] = 'NA','NA'

					self.log.info("prepared dict from PORTS table ",portsDict)
					interfacesDict[port.node.name+':::'+port.name] = portsDict	
			
		return interfacesDict
	#
	# To add inventory details in inv_list
	#
	def add_inventory(self,rows, inv_type, inv_list, node_name):
		for row in rows:
			statusDict = {}
			for (key, value) in zip(row.keys(), row.values()):
				if key == 'Node':
					try:
						node = value
					except:
						node = None
					statusDict['node'] = node
				if key == 'Id':
					try:
						node = value
					except:
						node = None
					statusDict['id'] = node
				if key == 'Type':
					try:
						typeOf = value
					except:
						typeOf = None
					statusDict['typeOf'] = typeOf

				if key == 'Name':
					try:
						name = value
					except:
						name = None
					statusDict['name'] = name
				if key == 'Description':
					try:
						description = value
					except:
						description = None
					statusDict['description'] = description
				if key == 'SerialNumber':
					try:
						serialNumber = value
					except:
						serialNumber = None
					statusDict['serialNumber'] = serialNumber
				if key == 'ParentId':
					try:
						parentId = value
					except:
						parentId = None
					statusDict['parentId'] = parentId
			if(statusDict['typeOf'] == inv_type and statusDict['node'] == node_name):
				del statusDict['node']
				inv_list.append(statusDict)
	# This method returns dictionary of capacity , traffic ,descrition and interface value
	def getPortParams(self, ports):
		portParamsDict={}
		for port in ports:
			if port.description:
				if "FREE" in str(port.description).upper():
					continue

				key = port.node.name+":"+ port.name
				portParamsDict[key]= str(port.capacity)+":::"+str(port.measured_traffic)+":::"+str(port.description) + ":::"+ str(port.interface)
		self.log.info("{} ports have Capacity and traffic  {}".format(len(portParamsDict),portParamsDict))		
		return portParamsDict
