from ncs.application import Application
from com.cisco.wae.opm.action import OpmActionBase
from com.cisco.wae.opm.network import open_plan
import com.cisco.wae.design
import threading
import ConfigParser
import time,subprocess,requests
from requests.auth import HTTPBasicAuth
from com.cisco.wae.design import ServiceConnectionManager
from helpers import Helpers
import logging
import ncs
from ncs.dp import Action
import json,os
import calendar
import datetime
import time

class UpdateIptWithTrafficInfo(Application):
		def setup(self):
			
			self.log.info('Start Update IPT with Traffic Information, Action.........')
			self.register_action('update-ipt-with-traffic-info-action-point',UpdateIptWithTrafficInfoAction, [])

		def teardown(self):
			self.log.info('Update IPT with Traffic Information Action stopped')


class UpdateIptWithTrafficInfoAction(OpmActionBase):

	def run(self, net_name, input, output):


		my_helper = Helpers(self.log)

		#
		# WAE API CALL to PULL PLAN-FILES
		# 	
		output = my_helper.invokeWaeOpmRestApi("plan-archive/list","POST",None) #NO PAYLOAD RECQUIRED
		lastFile = output['cisco-wae-archive:output']['planfiles']['planfiles'][-1]
		planFile = str(lastFile['abspath']) #[-1] For fetching latest pln file
		timestamp = str(lastFile['timestamp'])
		time_str = timestamp + '_UTC'
		self.log.debug('TIMESTAMP is {}'.format(time_str))
		# TODO Uncomment after demo

		'''
		utc_time = time.strptime(timestamp, "%y%m%d_%H%M")
		utc_seconds = calendar.timegm(utc_time)
		local_time = time.localtime(utc_seconds)
		time_str = time.strftime('%Y-%m-%d %H:%M:%S',local_time)
		'''

		#planFile = '/opt/others/plan-files/etisalat-xtc-dare_delay_11.pln'

		total_payload = {}
		with open_plan(planFile) as network:
			self.log.info('Preparing data for IPT dashboard from plan-file {}'.format(planFile))
			interfaces = network.model.interfaces
			ports=network.model.ports
			netint_tables = network.model.netint_tables
			payloadList = []

			if 'etisalat' in net_name or 'emix' in net_name:
				net_name = 'EMIX'
			elif 'isg' in net_name:
				net_name = 'ISG'
			total_payload["network"] = net_name
			self.log.debug('Started preparing interface status dictionary')
			statusDict = my_helper.getStatusofLink(netint_tables)
			self.log.debug('Completed preparation of interface status dictionary')

			self.log.debug('Processing interfaces data ....')
			for interface in interfaces:
				interfaceDict = {}
				oppInterface = interface.opposite_interface
				if "Bundle-Ether" in interface.name or "Vlan" in interface.name or "Bundle-Ether" in oppInterface.name or "Vlan" in oppInterface.name:
					continue

				interfaceDict['timestamp'] = time_str

				#
				# OUTBOUND
				#
				try:
					interfaceDict['description'] = interface.description
				except:
					interfaceDict['description'] = 'NA'
				interfaceDict['router_name'] = interface.node.name
				interfaceDict['iface_name'] = interface.name

				#TODO
				'''try:
					interfaceDict['capacity'] = interface.configured_capacity
				except:
					interfaceDict['capacity'] = 'NA'''
				
				if interface.configured_capacity is not None:
					interfaceDict['capacity'] = round(interface.configured_capacity,2)
				else:
					interfaceDict['capacity'] = 0
				if interface.measured_utilization is not None:
					interfaceDict['utilization'] = round(interface.measured_utilization,2)
				else:
					interfaceDict['utilization'] = 0
				if interface.measured_traffic is not None:
					interfaceDict['outbound_traffic'] = round(interface.measured_traffic,2)
				else:
					interfaceDict['outbound_traffic'] = 0

				if "psn" in interfaceDict['router_name'] or "BgpPsn" in interfaceDict['router_name'] or "ASN" in interfaceDict['router_name']:
					interfaceDict['iface_operation_status'],interfaceDict['iface_admin_status'] = 'NA','NA'
				else:
					try:
						interfaceDict['iface_operation_status'],interfaceDict['iface_admin_status'] = statusDict[str(interfaceDict['router_name']) + \
						':::' + str(interfaceDict['iface_name'])].strip().split(':::')
					except:
						interfaceDict['iface_operation_status'],interfaceDict['iface_admin_status'] = 'NA','NA'

				#
				# INBOUND
				#
				try:
					interfaceDict['target_interface_description']=oppInterface.description
				except:
					interfaceDict['target_interface_description']='NA'

				interfaceDict['target_parent_bundle_id']='NA'
				interfaceDict['target_router_name'] = oppInterface.node.name
				interfaceDict['target_iface_name'] = oppInterface.name
				if oppInterface.measured_utilization is not None:
					interfaceDict['inbound_utilization'] = round(oppInterface.measured_utilization,2)
				else:
					interfaceDict['inbound_utilization'] = 0
				if oppInterface.measured_traffic is not None:
					interfaceDict['inbound_traffic'] = round(oppInterface.measured_traffic,2)
				else:
					interfaceDict['inbound_traffic'] = 0
				interfaceDict['parent_bundle_id']='NA'
				self.log.info('Successfully Completed processing interface data ....')
				payloadList.append(interfaceDict)
			self.log.info("Iterating over ports table")
			
			portParamsDict=self.getPortParams(ports)
			
			for port in ports:
				if port.description or port.interface:
					portsDict={}

					if "FREE" in str(port.description).upper():
						continue

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
						#inbound_traffic = port_b.measured_traffic
						outbound_capacity=port_a.capacity

						#INBOUND
						if port_b.measured_traffic is not None:
							inbound_traffic=port_b.measured_traffic
						else:
							inbound_traffic = 0

						#OUTBOUND
						if port_a.measured_traffic is not None:
							outbound_traffic=port_a.measured_traffic
						else:
							outbound_traffic = 0
					else:
						self.log.debug("port node {} does not have port cicuit".format(port.node.name))
						decs_capacity_traffic = portParamsDict[port.node.name+":"+port.name]
						self.log.debug("node: {} port : {} have capacity and traffic {}".format(port.node.name,port.name,decs_capacity_traffic))					
						# portParams --> [description, traffic,capacity]
						portParams = decs_capacity_traffic.split(':::')
						try:
							outbound_capacity = float(portParams[0])
						except:
							outbound_capacity = 0
						try:
							outbound_traffic = float(portParams[1])
						except:
							outbound_traffic = 0
						port_desc = portParams[2].split("_")

						try:
							remote_node = port_desc[1]
							remote_port = port_desc[2]
						except:
							remote_node = "NA"
							remote_port = "NA"
						self.log.debug("Remote node: {}".format(port_desc))
						self.log.debug("Remote node: {} Remote port : {} ".format(remote_node,remote_port))
						remote_capacity_traffic = []
						remote_node_key = str(remote_node)+":"+str(remote_port)
						if remote_node_key in portParamsDict.keys():
							capacity_traffic = portParamsDict[remote_node_key]
							remote_capacity_traffic = capacity_traffic.split(':::')
						try:
							inbound_capacity = float(remote_capacity_traffic[0])
						except:
							inbound_capacity = 0
						try:
							inbound_traffic = float(remote_capacity_traffic[1])
						except:
							inbound_traffic = 0

						try:
							remote_desc = str(remote_capacity_traffic[2])
						except:
							remote_desc = "NA"
					try:
						portsDict['capacity']=port.capacity
					except:
						portsDict['capacity']='NA'
					try:
						if port.description:
							portsDict['description']=port.description
						else:
							portsDict['description']='NA'
					except:
						portsDict['description']='NA'
					try:
						portsDict['iface_name']=port.name
					except:
						portsDict['iface_name']='NA'
					try:
						portsDict['router_name']=port.node.name
					except:
						portsDict['router_name']='NA'
					try:
						portsDict['timestamp']=time_str
					except:
						portsDict['timestamp']='NA'
					try:
						if remote_node:
							portsDict['target_router_name']=  remote_node
						else:
							portsDict['target_router_name']= port_b.node.name
					except:
						portsDict['target_router_name']='NA'
					try:
						portsDict['inbound_traffic']=round(inbound_traffic,2)
					except:
						portsDict['inbound_traffic']=0
					try:
						if remote_port:
							portsDict['target_iface_name'] = remote_port
						else:
							portsDict['target_iface_name']=port.remote_port.name
					except:
						portsDict['target_iface_name']='NA'
					try:
						portsDict['outbound_traffic']=round(outbound_traffic,2)
					except:
						portsDict['outbound_traffic']=0
					try:
						portsDict['parent_bundle_id']=port.interface.name
					except:
						portsDict['parent_bundle_id']='NA'
					try:
						if remote_desc:
							portsDict['target_interface_description'] = remote_desc
						else:
							portsDict['target_interface_description']=port_b.description
					except:
						portsDict['target_interface_description']='NA'

					try:
						portsDict['target_parent_bundle_id']=port_b.interface.name
					except:
						portsDict['target_parent_bundle_id']='NA'
					try:
						portsDict['inbound_utilization']=round((inbound_traffic/inbound_capacity)*100,2)
					except:
						portsDict['inbound_utilization']=0
					try:
						portsDict['utilization']=round((outbound_traffic/outbound_capacity)*100,2)
					except:
						portsDict['utilization']=0
					try:
						portsDict['iface_operation_status'],portsDict['iface_admin_status'] = statusDict[str(portsDict['router_name']) + \
							':::' + str(portsDict['iface_name'])].strip().split(':::')
					except:
						portsDict['iface_operation_status'],portsDict['iface_admin_status'] = 'NA','NA'

					self.log.info("prepared dict from PORTS table ",portsDict)
					self.log.info("appending portsDict in payloadList ")
					payloadList.append(portsDict)
			self.log.info('Successfully Completed processing ports data ....')

			total_payload["link_utilization_payload"] = payloadList
			payload = str(json.dumps(total_payload))

			self.log.info('payload to UOP API to push link utilization is {}'.format(payload))

		#
		# UOP API CALL to PUSH LINK UTILIZATION
		# 	
		resp = my_helper.invokeUOPRestApi('link_utilization_wae',"POST",payload)
		self.log.info('Response from UOP {} and the message is {}'.format(resp['meta']['success'],resp['meta']['info']))
	# This method returns dictionary of capacity , traffic and descrition value
	def getPortParams(self, ports):
		portParamsDict={}
		for port in ports:
			if port.description:
				if "FREE" in str(port.description).upper():
					continue

				key = port.node.name+":"+ port.name
				portParamsDict[key]= str(port.capacity)+":::"+str(port.measured_traffic)+":::"+str(port.description)
		self.log.info("{} ports have Capacity and traffic  {}".format(len(portParamsDict),portParamsDict))		
		return portParamsDict
